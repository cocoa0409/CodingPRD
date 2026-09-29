"""Model runs, their four parallel status dimensions, and channel contributions.

PRD sections 3.4 (fit, holdout), 3.5 (publication, stability) and 3.7 (calibration).
"""

from flask import Blueprint, request

import db as store
from db import base_row, db
from errors import ApiError
from lookup import must, must_field
from middleware import ANALYTICS_LEAD, MODELER, READ_ROLES, authenticate
from response import created, listing, ok
from services import ordering
from services.model import perform_fit, perform_publish, perform_recalibrate, perform_validate
from validation import (field_array, field_bool, field_enum, field_id_array, field_int,
                        get_body, invalid)

bp = Blueprint("model_runs", __name__)

CONTROL_VARIABLES = ("PRICE_INDEX", "DISTRIBUTION_INDEX", "MACRO_INDEX",
                     "SEASONALITY_WEEK_OF_YEAR")
SEASONALITY_MODES = ("NONE", "WEEK_OF_YEAR", "MONTH_OF_YEAR")
ATTRIBUTION_MODES = ("EFFECT_PERIOD", "SPEND_PERIOD")

FIT_STATUSES = ("PENDING", "FITTED", "STALE_FIT")
VALIDATION_STATUSES = ("UNVALIDATED", "HOLDOUT_PASSED", "HOLDOUT_FAILED")
CALIBRATION_STATUSES = ("NOT_REQUIRED", "PENDING_CALIBRATION", "CALIBRATED", "STALE")
PUBLICATION_STATUSES = ("UNPUBLISHED", "PUBLISHED", "SUPERSEDED")


@bp.post("/mmm/model-runs")
def create_model_run():
    authenticate((MODELER,))
    body = get_body()
    included = field_id_array(body, "included_channel_ids", min_items=1, max_items=8,
                              distinct=True)
    controls = field_array(body, "control_variables", required=False, default=None)
    if controls is None:
        controls = []
    else:
        for item in controls:
            if not isinstance(item, str) or item not in CONTROL_VARIABLES:
                raise invalid("control_variables must be drawn from %s."
                              % ", ".join(CONTROL_VARIABLES))
    seasonality_mode = field_enum(body, "seasonality_mode", SEASONALITY_MODES,
                                  required=False, default="WEEK_OF_YEAR")
    # PRD 3.4: the attribution mode must be stated explicitly on creation.
    attribution_mode = field_enum(body, "carryover_attribution_mode", ATTRIBUTION_MODES)
    holdout_periods = field_int(body, "holdout_periods", required=False, default=1, minimum=1)

    market = must_field("markets", body, "market_id")
    window = must_field("data_windows", body, "data_window_id")
    channels = [must("media_channels", channel_id) for channel_id in included]

    if window["market_id"] != market["id"]:
        raise invalid("The data window does not belong to the referenced market.")
    if holdout_periods >= window["expected_period_count"]:
        raise invalid("holdout_periods must be strictly less than the window's "
                      "expected_period_count.")
    for channel in channels:
        if channel["market_id"] != market["id"]:
            raise ApiError("ERR_CHANNEL_NOT_IN_MARKET",
                           "Channel %s does not belong to the referenced market."
                           % channel["channel_code"])

    row = base_row("model_runs")
    row.update({
        "market_id": market["id"],
        "data_window_id": window["id"],
        "included_channel_ids": list(included),
        "control_variables": list(controls),
        "seasonality_mode": seasonality_mode,
        "carryover_attribution_mode": attribution_mode,
        "holdout_periods": holdout_periods,
        "fit_status": "PENDING",
        "validation_status": "UNVALIDATED",
        "calibration_status": "NOT_REQUIRED",
        "publication_status": "UNPUBLISHED",
        "previous_published_run_id": None,
        "unit_price_cents": None,
        "modeled_sales_units": None,
        "baseline_sales_units": None,
        "observation_period_count": None,
        "holdout_mape_pct": None,
        "stability_score": None,
        "refresh_generation": 1,
        "fitted_by_user_id": None,
        "published_by_user_id": None,
    })
    db.add("model_runs", row)
    return created(row)


@bp.get("/mmm/model-runs")
def list_model_runs():
    authenticate(READ_ROLES)
    rows = db.all("model_runs")
    for param, field in (("market_id", "market_id"),
                         ("data_window_id", "data_window_id"),
                         ("previous_published_run_id", "previous_published_run_id"),
                         ("fit_status", "fit_status"),
                         ("validation_status", "validation_status"),
                         ("calibration_status", "calibration_status"),
                         ("publication_status", "publication_status")):
        value = request.args.get(param)
        if value:
            rows = [r for r in rows if r[field] == value]
    return listing(ordering.sort_rows("model_runs", rows), request.args)


@bp.get("/mmm/model-runs/<run_id>")
def get_model_run(run_id):
    authenticate(READ_ROLES)
    return ok(must("model_runs", run_id))


@bp.post("/mmm/model-runs/<run_id>/fit")
def fit_model_run(run_id):
    user_id = authenticate((MODELER,))
    run = must("model_runs", run_id)
    return ok(perform_fit(run, user_id))


@bp.post("/mmm/model-runs/<run_id>/validate")
def validate_model_run(run_id):
    authenticate((MODELER,))
    run = must("model_runs", run_id)
    return ok(perform_validate(run))


@bp.post("/mmm/model-runs/<run_id>/publish")
def publish_model_run(run_id):
    user_id = authenticate((ANALYTICS_LEAD,))
    run = must("model_runs", run_id)
    body = get_body()
    override = field_bool(body, "override_stability", required=False, default=None)
    return ok(perform_publish(run, user_id, override))


@bp.post("/mmm/model-runs/<run_id>/recalibrate")
def recalibrate_model_run(run_id):
    authenticate((MODELER,))
    run = must("model_runs", run_id)
    return ok(perform_recalibrate(run))


# ---------------------------------------------------- channel contributions

@bp.get("/mmm/channel-contributions")
def list_channel_contributions():
    authenticate(READ_ROLES)
    rows = db.all("channel_contributions")
    run_id = request.args.get("model_run_id")
    if run_id:
        rows = [r for r in rows if r["model_run_id"] == run_id]
    channel_id = request.args.get("channel_id")
    if channel_id:
        rows = [r for r in rows if r["channel_id"] == channel_id]
    is_current = request.args.get("is_current")
    if is_current is not None and is_current != "":
        wanted = str(is_current).strip().lower() in ("true", "1", "yes")
        rows = [r for r in rows if r["is_current"] == wanted]
    mode = request.args.get("attribution_mode_used")
    if mode:
        rows = [r for r in rows if r["attribution_mode_used"] == mode]
    return listing(ordering.sort_rows("channel_contributions", rows), request.args)


@bp.get("/mmm/channel-contributions/<contribution_id>")
def get_channel_contribution(contribution_id):
    authenticate(READ_ROLES)
    return ok(must("channel_contributions", contribution_id))
