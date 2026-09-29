"""Experiment lifecycle (PRD section 3.6)."""

from datetime import timedelta

from flask import Blueprint, request

import db as store
from db import base_row, db, touch
from errors import ApiError
from lookup import must, must_field
from middleware import ANALYTICS_LEAD, EXPERIMENT_DESIGNER, READ_ROLES, authenticate
from response import created, listing, ok
from services import ordering
from services.experiment import (POWER_FLOOR, REDESIGN_LIMIT, assert_channel_unoccupied,
                                 assert_holdout_share, computed_power, power_index,
                                 read_out_lift)
from services.market import require_posture_not_frozen, sync_market
from services.model import cascade_experiment_accepted
from services.numeric import ZERO
from validation import (date_style, field_date, field_decimal, field_enum, field_id_array,
                        field_int, field_string, format_date, get_body, invalid)

bp = Blueprint("experiments", __name__)

DESIGN_TYPES = ("GEO_HOLDOUT", "AUDIENCE_SPLIT")
READOUT_METHODS = ("DIFF_IN_DIFF", "SYNTHETIC_CONTROL")


@bp.post("/mmm/experiments")
def create_experiment():
    user_id = authenticate((EXPERIMENT_DESIGNER,))
    body = get_body()
    design_type = field_enum(body, "design_type", DESIGN_TYPES)
    readout_method = field_enum(body, "readout_method", READOUT_METHODS)
    start_raw, start = field_date(body, "start_date")
    end_raw, end = field_date(body, "end_date")
    washout_days = field_int(body, "washout_days", minimum=0, maximum=60)
    mde = field_decimal(body, "minimum_detectable_effect_pct", exclusive_minimum=0,
                        maximum=100, max_places=1)
    rate = field_decimal(body, "baseline_conversion_rate", exclusive_minimum=0,
                         exclusive_maximum=1, max_places=4)
    planned_treatment = field_int(body, "planned_treatment_population", minimum=1)
    planned_control = field_int(body, "planned_control_population", minimum=1)
    if end <= start:
        raise invalid("end_date must be strictly after start_date.")

    market = must_field("markets", body, "market_id")
    channel = must_field("media_channels", body, "channel_id")
    if channel["market_id"] != market["id"]:
        raise ApiError("ERR_CHANNEL_NOT_IN_MARKET",
                       "Channel %s does not belong to the referenced market."
                       % channel["channel_code"])

    row = base_row("experiments")
    row.update({
        "market_id": market["id"],
        "channel_id": channel["id"],
        "design_type": design_type,
        "readout_method": readout_method,
        "start_date": start_raw,
        "end_date": end_raw,
        "washout_days": washout_days,
        "minimum_detectable_effect_pct": mde,
        "baseline_conversion_rate": rate,
        "planned_treatment_population": planned_treatment,
        "planned_control_population": planned_control,
        "power_index": None,
        "computed_power": None,
        "treatment_population": 0,
        "control_population": 0,
        "treatment_conversions": None,
        "control_conversions": None,
        "pre_treatment_conversions": None,
        "pre_control_conversions": None,
        "synthetic_control_weight": None,
        "measured_lift_pct": None,
        "lift_ci_half_width_pct": None,
        "lift_ci_low_pct": None,
        "lift_ci_high_pct": None,
        "status": "DRAFT",
        "redesign_count": 0,
        "designed_by_user_id": user_id,
        "decided_by_user_id": None,
        "rejection_reason": None,
        "_start_date": start,
        "_end_date": end,
        "_date_style": date_style(end_raw),
    })
    db.add("experiments", row)
    return created(row)


@bp.get("/mmm/experiments")
def list_experiments():
    authenticate(READ_ROLES)
    rows = db.all("experiments")
    for param in ("market_id", "channel_id", "status", "design_type", "readout_method"):
        value = request.args.get(param)
        if value:
            rows = [r for r in rows if r[param] == value]
    return listing(ordering.sort_rows("experiments", rows), request.args)


@bp.get("/mmm/experiments/<experiment_id>")
def get_experiment(experiment_id):
    authenticate(READ_ROLES)
    return ok(must("experiments", experiment_id))


@bp.post("/mmm/experiments/<experiment_id>/lock-design")
def lock_design(experiment_id):
    authenticate((EXPERIMENT_DESIGNER,))
    experiment = must("experiments", experiment_id)
    market = db.markets[experiment["market_id"]]
    if experiment["status"] != "DRAFT":
        raise ApiError("ERR_EXPERIMENT_INVALID_STATE",
                       "Only a DRAFT experiment can have its design locked.")
    require_posture_not_frozen(market)

    index = power_index(experiment)
    power = computed_power(index)
    if power < POWER_FLOOR:
        raise ApiError("ERR_EXPERIMENT_UNDERPOWERED",
                       "Computed power %s is below the 0.80 design floor." % power)

    if experiment["design_type"] == "GEO_HOLDOUT":
        assert_holdout_share(market, experiment["planned_treatment_population"]
                             + experiment["planned_control_population"])

    assert_channel_unoccupied(experiment)

    experiment["power_index"] = index
    experiment["computed_power"] = power
    if experiment["design_type"] == "AUDIENCE_SPLIT":
        experiment["treatment_population"] = experiment["planned_treatment_population"]
        experiment["control_population"] = experiment["planned_control_population"]
    experiment["status"] = "DESIGN_LOCKED"
    touch(experiment)
    return ok(experiment)


@bp.post("/mmm/experiments/<experiment_id>/assign-cells")
def assign_cells(experiment_id):
    authenticate((EXPERIMENT_DESIGNER,))
    experiment = must("experiments", experiment_id)
    market = db.markets[experiment["market_id"]]
    body = get_body()
    treatment_ids = field_id_array(body, "treatment_cell_ids")
    control_ids = field_id_array(body, "control_cell_ids")

    # Existence of every named cell resolves before the experiment's own state.
    treatment_cells = [must("geo_cells", cell_id) for cell_id in treatment_ids]
    control_cells = [must("geo_cells", cell_id) for cell_id in control_ids]
    named = treatment_cells + control_cells

    if experiment["status"] != "DESIGN_LOCKED":
        raise ApiError("ERR_EXPERIMENT_INVALID_STATE",
                       "Cells may only be assigned to a DESIGN_LOCKED experiment.")

    # Availability outranks both the design-type and the market-membership checks.
    for cell in named:
        if cell["assignment_state"] != "UNASSIGNED":
            raise ApiError("ERR_GEO_CELL_UNAVAILABLE",
                           "Cell %s is %s." % (cell["cell_code"], cell["assignment_state"]))
    if experiment["design_type"] != "GEO_HOLDOUT":
        raise ApiError("ERR_DESIGN_TYPE_MISMATCH",
                       "Only a GEO_HOLDOUT experiment consumes geographic cells.")
    for cell in named:
        if cell["market_id"] != experiment["market_id"]:
            raise ApiError("ERR_GEO_CELL_NOT_IN_MARKET",
                           "Cell %s does not belong to the experiment's market."
                           % cell["cell_code"])

    unique = {}
    for cell in named:
        unique[cell["id"]] = cell
    assert_holdout_share(market, sum(c["population"] for c in unique.values()))

    for cell in treatment_cells:
        cell["assignment_state"] = "TREATMENT"
        cell["assigned_experiment_id"] = experiment["id"]
        touch(cell)
    for cell in control_cells:
        cell["assignment_state"] = "CONTROL"
        cell["assigned_experiment_id"] = experiment["id"]
        touch(cell)

    experiment["treatment_population"] = sum(c["population"] for c in treatment_cells)
    experiment["control_population"] = sum(c["population"] for c in control_cells)
    experiment["status"] = "CELLS_ASSIGNED"
    touch(experiment)
    sync_market(market)
    return ok(experiment)


@bp.post("/mmm/experiments/<experiment_id>/start")
def start_experiment(experiment_id):
    authenticate((EXPERIMENT_DESIGNER,))
    experiment = must("experiments", experiment_id)
    status = experiment["status"]
    if status not in ("DESIGN_LOCKED", "CELLS_ASSIGNED"):
        raise ApiError("ERR_EXPERIMENT_INVALID_STATE",
                       "An experiment in %s cannot be started." % status)
    if status == "DESIGN_LOCKED" and experiment["design_type"] == "GEO_HOLDOUT":
        raise ApiError("ERR_CELLS_NOT_ASSIGNED",
                       "A GEO_HOLDOUT experiment needs its cells assigned before it starts.")
    if db.clock.date() < experiment["_start_date"]:
        raise ApiError("ERR_EXPERIMENT_NOT_STARTED",
                       "The logical clock has not reached start_date.")
    if experiment["design_type"] == "AUDIENCE_SPLIT":
        experiment["treatment_population"] = experiment["planned_treatment_population"]
        experiment["control_population"] = experiment["planned_control_population"]
    experiment["status"] = "RUNNING"
    touch(experiment)
    return ok(experiment)


@bp.post("/mmm/experiments/<experiment_id>/read-out")
def read_out(experiment_id):
    authenticate((EXPERIMENT_DESIGNER,))
    experiment = must("experiments", experiment_id)
    body = get_body()
    treatment_conversions = field_int(body, "treatment_conversions", minimum=0)
    control_conversions = field_int(body, "control_conversions", minimum=1)
    pre_treatment_conversions = field_int(body, "pre_treatment_conversions", minimum=0)
    pre_control_conversions = field_int(body, "pre_control_conversions", minimum=1)

    if experiment["status"] != "RUNNING":
        raise ApiError("ERR_EXPERIMENT_INVALID_STATE",
                       "Only a RUNNING experiment can be read out.")

    treatment_population = experiment["treatment_population"]
    control_population = experiment["control_population"]
    if (treatment_conversions > treatment_population
            or pre_treatment_conversions > treatment_population
            or control_conversions > control_population
            or pre_control_conversions > control_population):
        raise ApiError("ERR_CONVERSIONS_EXCEED_POPULATION",
                       "A conversion count exceeds its arm's realised population.")

    if db.clock.date() < experiment["_end_date"]:
        raise ApiError("ERR_EXPERIMENT_NOT_ELAPSED",
                       "The logical clock has not reached end_date.")

    figures = read_out_lift(experiment, treatment_conversions, control_conversions,
                            pre_treatment_conversions, pre_control_conversions)
    experiment["treatment_conversions"] = treatment_conversions
    experiment["control_conversions"] = control_conversions
    experiment["pre_treatment_conversions"] = pre_treatment_conversions
    experiment["pre_control_conversions"] = pre_control_conversions
    experiment.update(figures)
    experiment["status"] = "READ_OUT"
    touch(experiment)
    return ok(experiment)


def _assert_duty(experiment, user_id):
    # The duty check outranks the state check (PRD 3.6).
    if user_id == experiment["designed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The designing operator may not decide this readout.")


@bp.post("/mmm/experiments/<experiment_id>/accept")
def accept_experiment(experiment_id):
    user_id = authenticate((ANALYTICS_LEAD,))
    experiment = must("experiments", experiment_id)
    market = db.markets[experiment["market_id"]]
    _assert_duty(experiment, user_id)
    if experiment["status"] != "READ_OUT":
        raise ApiError("ERR_EXPERIMENT_INVALID_STATE",
                       "Only a READ_OUT experiment can be accepted.")
    if store.published_run_of_market(market["id"]) is None:
        raise ApiError("ERR_NO_PUBLISHED_MODEL_RUN")
    if experiment["lift_ci_low_pct"] is None or experiment["lift_ci_low_pct"] <= 0:
        raise ApiError("ERR_LIFT_NOT_SIGNIFICANT",
                       "lift_ci_low_pct must be strictly greater than 0.00.")
    experiment["status"] = "ACCEPTED"
    experiment["decided_by_user_id"] = user_id
    touch(experiment)
    cascade_experiment_accepted(market)
    return ok(experiment)


@bp.post("/mmm/experiments/<experiment_id>/reject")
def reject_experiment(experiment_id):
    user_id = authenticate((ANALYTICS_LEAD,))
    experiment = must("experiments", experiment_id)
    body = get_body()
    reason = field_string(body, "rejection_reason", min_len=1)
    if reason.strip() == "":
        raise invalid("rejection_reason must be non-empty.")
    _assert_duty(experiment, user_id)
    if experiment["status"] != "READ_OUT":
        raise ApiError("ERR_EXPERIMENT_INVALID_STATE",
                       "Only a READ_OUT experiment can be rejected.")
    experiment["status"] = "REJECTED"
    experiment["rejection_reason"] = reason
    experiment["decided_by_user_id"] = user_id
    touch(experiment)
    # No cascade whatsoever fires on the reject arm.
    return ok(experiment)


@bp.post("/mmm/experiments/<experiment_id>/release-cells")
def release_cells(experiment_id):
    authenticate((EXPERIMENT_DESIGNER,))
    experiment = must("experiments", experiment_id)
    status = experiment["status"]
    if status not in ("ACCEPTED", "REJECTED"):
        raise ApiError("ERR_EXPERIMENT_INVALID_STATE",
                       "Cells may only be released from ACCEPTED or REJECTED.")
    if status == "REJECTED" and experiment["redesign_count"] >= REDESIGN_LIMIT:
        raise ApiError("ERR_REDESIGN_LIMIT_REACHED",
                       "This experiment has already been redesigned twice.")

    washout_until = experiment["_end_date"] + timedelta(days=experiment["washout_days"])
    for cell in store.cells_of_market(experiment["market_id"]):
        if cell["assigned_experiment_id"] != experiment["id"]:
            continue
        if cell["assignment_state"] not in ("TREATMENT", "CONTROL"):
            continue
        cell["assignment_state"] = "WASHOUT"
        cell["_washout_until_date"] = washout_until
        cell["washout_until_date"] = format_date(washout_until, experiment["_date_style"])
        touch(cell)

    if status == "ACCEPTED":
        experiment["status"] = "CLOSED"
    else:
        experiment["status"] = "DRAFT"
        experiment["redesign_count"] = experiment["redesign_count"] + 1
        experiment["computed_power"] = None
        experiment["power_index"] = None
        experiment["treatment_conversions"] = None
        experiment["control_conversions"] = None
        experiment["pre_treatment_conversions"] = None
        experiment["pre_control_conversions"] = None
        experiment["measured_lift_pct"] = None
        experiment["lift_ci_half_width_pct"] = None
        experiment["lift_ci_low_pct"] = None
        experiment["lift_ci_high_pct"] = None
        experiment["treatment_population"] = 0
        experiment["control_population"] = 0
    touch(experiment)
    # The market's held_out_population is explicitly unchanged: WASHOUT is still held out.
    return ok(experiment)
