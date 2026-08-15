"""FiscalYear endpoints plus everything keyed directly beneath a fiscal year:
rates settings, activity records, capital projects, settlement compute,
PFC applications, agreements (reverse reachability)."""
from flask import Blueprint

import errors
import helpers
import services
from db import store
from helpers import (authenticate, get_path, json_body, paginate, resolve_fk,
                     req_string, req_int, opt_int, req_enum, opt_bool,
                     req_iso_datetime, require_ownership, READ_ROLES,
                     METHODOLOGIES, COST_CENTERS, SIGNATURE_STATUSES)
from response import success_object, success_list
from services import (ser_fiscal_year, ser_rates_setting, ser_activity,
                      ser_capital_project, ser_settlement, ser_pfc,
                      ser_agreement, touch, stamp, now_dt, check_fy_open_guard,
                      derive_rates, adopted_rates_setting, landing_fee_charge,
                      pfc_amount, recompute_fy_activity_totals, run_true_up)
from util import new_id, fmt_iso

bp = Blueprint("fiscal_years", __name__)


def _get_fy(fy_id):
    return get_path(store.fiscal_years, fy_id, "FiscalYear")


# ---------------------------------------------------------------------------
# FiscalYear
# ---------------------------------------------------------------------------
@bp.post("/airport/fiscal_years")
def create_fiscal_year():
    authenticate(("AirportFinance",))
    body = json_body()
    # field shape (priority 5)
    year_label = req_string(body, "year_label")
    methodology = req_enum(body, "methodology", METHODOLOGIES)
    airfield_opex = req_int(body, "airfield_opex_cents", minimum=0)
    terminal_opex = req_int(body, "terminal_opex_cents", minimum=0)
    nonair_air = req_int(body, "nonairline_airfield_revenue_cents", minimum=0)
    nonair_term = req_int(body, "nonairline_terminal_revenue_cents", minimum=0)
    total_space = req_int(body, "terminal_total_space_sqft", strictly_positive=True)
    forecast = req_int(body, "forecast_landed_weight_kg", strictly_positive=True)
    surplus = opt_int(body, "prior_year_surplus_cents", default=0)
    # uniqueness of year_label
    for fy in store.fiscal_years.values():
        if fy["year_label"] == year_label:
            raise errors.invalid_request("year_label must be unique")
    # PRD §3.1 places no methodology restriction on the creation payload (the
    # carry-forward "is optional and defaults to zero; it may be negative");
    # §2.7 excludes it from derivation under COMPENSATORY — see derive_rates.
    ts = stamp()
    fy = {
        "id": new_id(),
        "year_label": year_label,
        "methodology": methodology,
        "status": "DRAFT",
        "airfield_opex_cents": airfield_opex,
        "terminal_opex_cents": terminal_opex,
        "nonairline_airfield_revenue_cents": nonair_air,
        "nonairline_terminal_revenue_cents": nonair_term,
        "terminal_total_space_sqft": total_space,
        "forecast_landed_weight_kg": forecast,
        "prior_year_surplus_cents": surplus if surplus is not None else 0,
        "total_projected_landed_weight_kg": 0,
        "total_signatory_landed_weight_kg": 0,
        "total_rented_space_sqft": 0,
        "settlement_id": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_created_dt": now_dt(),
        "_seq": next(store.seq),
    }
    store.fiscal_years[fy["id"]] = fy
    return success_object(ser_fiscal_year(fy), status=201)


@bp.get("/airport/fiscal_years")
def list_fiscal_years():
    authenticate(READ_ROLES)
    items = list(store.fiscal_years.values())
    status = helpers.request.args.get("status")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    methodology = helpers.request.args.get("methodology")
    if methodology is not None:
        items = [f for f in items if f["methodology"] == methodology]
    data, meta = paginate(items, ser_fiscal_year)
    return success_list(data, meta)


@bp.get("/airport/fiscal_years/<fy_id>")
def get_fiscal_year(fy_id):
    authenticate(READ_ROLES)
    fy = _get_fy(fy_id)
    return success_object(ser_fiscal_year(fy))


@bp.post("/airport/fiscal_years/<fy_id>/open")
def open_fiscal_year(fy_id):
    authenticate(("AirportFinance",))
    fy = _get_fy(fy_id)
    if fy["status"] != "DRAFT":
        raise errors.invalid_state("Only a DRAFT fiscal year can be opened")
    fy["status"] = "OPEN"
    touch(fy)
    return success_object(ser_fiscal_year(fy))


# ---------------------------------------------------------------------------
# RatesSetting (create + per-year list)
# ---------------------------------------------------------------------------
@bp.post("/airport/fiscal_years/<fy_id>/rates_settings")
def create_rates_setting(fy_id):
    authenticate(("AirportFinance",))
    fy = _get_fy(fy_id)
    body = json_body()
    # priority 5: expected_fiscal_year_version must be carried (PRD §2.10)
    expected = body.get("expected_fiscal_year_version")
    if not helpers._is_int(expected):
        raise errors.invalid_request(
            "Field 'expected_fiscal_year_version' is required and must be an integer")
    # priority 7: OCC on the parent fiscal year's version
    if expected != fy["version"]:
        raise errors.stale_version(
            "expected_fiscal_year_version does not match the fiscal year's current version")
    # priority 9: year-closed guard
    check_fy_open_guard(fy)
    # priority 14: derivability
    derived = derive_rates(fy)
    ts = stamp()
    rs = {
        "id": new_id(),
        "fiscal_year_id": fy["id"],
        "status": "DRAFT",
        "airfield_requirement_cents": derived["airfield_requirement_cents"],
        "signatory_landing_fee_per_1000kg_cents": derived["signatory_landing_fee_per_1000kg_cents"],
        "non_signatory_landing_fee_per_1000kg_cents": derived["non_signatory_landing_fee_per_1000kg_cents"],
        "terminal_rental_rate_per_sqft_year_cents": derived["terminal_rental_rate_per_sqft_year_cents"],
        "adopted_at": None,
        "consultation_comment_count": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_created_dt": now_dt(),
        "_adopted_dt": None,
        "_seq": next(store.seq),
    }
    store.rates_settings[rs["id"]] = rs
    touch(fy)  # creating a schedule advances the parent year's version
    return success_object(ser_rates_setting(rs), status=201)


@bp.get("/airport/fiscal_years/<fy_id>/rates_settings")
def list_rates_settings(fy_id):
    authenticate(READ_ROLES)
    fy = _get_fy(fy_id)
    items = [r for r in store.rates_settings.values() if r["fiscal_year_id"] == fy["id"]]
    for rs in items:
        services.rederive_rates_onto(rs)  # readers always see current-input rates
    data, meta = paginate(items, ser_rates_setting)
    return success_list(data, meta)


# ---------------------------------------------------------------------------
# ActivityRecord
# ---------------------------------------------------------------------------
@bp.post("/airport/fiscal_years/<fy_id>/activity_records")
def create_activity_record(fy_id):
    authenticate(("AirportFinance",))
    fy = _get_fy(fy_id)
    body = json_body()
    airline = resolve_fk(body, "airline_id", store.airlines)  # priority 4
    airline_id = req_string(body, "airline_id")               # priority 5
    activity_date_raw, activity_dt = req_iso_datetime(body, "activity_date")
    landed_weight = req_int(body, "landed_weight_kg", strictly_positive=True)
    snapshot = req_enum(body, "signature_status_at_activity", SIGNATURE_STATUSES)
    # priority 6: an adopted rate schedule must exist to bill against
    adopted = adopted_rates_setting(fy["id"])
    if adopted is None:
        raise errors.invalid_state(
            "No adopted rate schedule exists for this fiscal year")
    # priority 8: activity date must not be in the future on the logical clock
    if activity_dt > now_dt():
        raise errors.temporal_violation(
            "activity_date falls outside the fiscal-year window")
    # priority 9: year-closed guard (evaluated before the carrier guard, §3.3)
    check_fy_open_guard(fy)
    # priority 10: suspended carrier grounded for billing
    ag = services.active_agreement(fy["id"], airline_id)
    if ag is not None and ag["credit_standing"] == "SUSPENDED":
        raise errors.airline_suspended()
    services.rederive_rates_onto(adopted)
    billed = landing_fee_charge(landed_weight, snapshot, adopted)
    ts = stamp()
    record = {
        "id": new_id(),
        "fiscal_year_id": fy["id"],
        "airline_id": airline["id"],
        "activity_date": activity_date_raw,
        "landed_weight_kg": landed_weight,
        "signature_status_at_activity": snapshot,
        "billed_landing_fee_cents": billed,
        "created_at": ts,
        "_created_dt": now_dt(),
        "_activity_dt": activity_dt,
        "_seq": next(store.seq),
    }
    store.activity_records[record["id"]] = record
    recompute_fy_activity_totals(fy)
    return success_object(ser_activity(record), status=201)


@bp.get("/airport/fiscal_years/<fy_id>/activity_records")
def list_activity_records(fy_id):
    authenticate(READ_ROLES)
    fy = _get_fy(fy_id)
    items = [r for r in store.activity_records.values() if r["fiscal_year_id"] == fy["id"]]
    airline_id = helpers.request.args.get("airline_id")
    if airline_id is not None:
        items = [r for r in items if r["airline_id"] == airline_id]
    snap = helpers.request.args.get("signature_status_at_activity")
    if snap is not None:
        items = [r for r in items if r["signature_status_at_activity"] == snap]
    data, meta = paginate(items, ser_activity)
    return success_list(data, meta)


# ---------------------------------------------------------------------------
# CapitalProject (create + per-year list)
# ---------------------------------------------------------------------------
@bp.post("/airport/fiscal_years/<fy_id>/capital_projects")
def create_capital_project(fy_id):
    authenticate(("AirportFinance",))
    fy = _get_fy(fy_id)
    body = json_body()
    project_name = req_string(body, "project_name")
    cost_center = req_enum(body, "cost_center", COST_CENTERS)
    budget = req_int(body, "budget_cents", strictly_positive=True)
    threshold = req_int(body, "mii_threshold_pct", minimum=50, maximum=100)
    check_fy_open_guard(fy)  # priority 9
    ts = stamp()
    project = {
        "id": new_id(),
        "fiscal_year_id": fy["id"],
        "project_name": project_name,
        "cost_center": cost_center,
        "budget_cents": budget,
        "mii_threshold_pct": threshold,
        "status": "PROPOSED",
        "votes_for_count": 0,
        "votes_for_weight_kg": 0,
        "votes_against_weight_kg": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_created_dt": now_dt(),
        "_seq": next(store.seq),
    }
    store.capital_projects[project["id"]] = project
    return success_object(ser_capital_project(project), status=201)


@bp.get("/airport/fiscal_years/<fy_id>/capital_projects")
def list_capital_projects(fy_id):
    authenticate(READ_ROLES)
    fy = _get_fy(fy_id)
    items = [p for p in store.capital_projects.values() if p["fiscal_year_id"] == fy["id"]]
    data, meta = paginate(items, ser_capital_project)
    return success_list(data, meta)


# ---------------------------------------------------------------------------
# AnnualSettlement compute (+ per-year reverse reachability)
# ---------------------------------------------------------------------------
@bp.post("/airport/fiscal_years/<fy_id>/settlement/compute")
def compute_settlement(fy_id):
    authenticate(("AirportFinance",))
    fy = _get_fy(fy_id)
    json_body(required=False)
    # priority 6: state preconditions
    if fy["status"] == "DRAFT":
        raise errors.invalid_state("Fiscal year must be OPEN to compute its settlement")
    if fy["settlement_id"] is not None:
        raise errors.invalid_state("This fiscal year already has a settlement")
    # priority 9
    check_fy_open_guard(fy)
    # priority 15
    records = [r for r in store.activity_records.values() if r["fiscal_year_id"] == fy["id"]]
    if not records:
        raise errors.no_activity()
    ts = stamp()
    settlement = {
        "id": new_id(),
        "fiscal_year_id": fy["id"],
        "status": "DRAFT",
        "actual_airfield_requirement_cents": 0,
        "actual_terminal_requirement_cents": 0,
        "total_billed_landing_cents": 0,
        "total_billed_terminal_cents": 0,
        "total_true_up_cents": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_created_dt": now_dt(),
        "_seq": next(store.seq),
        "_published_review_dt": None,
        "_resolved_dt": None,
    }
    store.settlements[settlement["id"]] = settlement
    _apply_true_up(settlement, fy, create_missing_only=False)
    settlement["status"] = "COMPUTED"
    touch(settlement)  # DRAFT -> COMPUTED increments the settlement version
    fy["settlement_id"] = settlement["id"]
    touch(fy)          # compute increments the fiscal year version
    return success_object(ser_settlement(settlement), status=201)


def _apply_true_up(settlement, fy, create_missing_only):
    """Run the waterfall and persist results onto settlement + lines.
    Existing lines keep their payment_status / due-date bookkeeping; new
    airlines that gained activity or space since compute get fresh lines."""
    settlement_fields, line_fields = run_true_up(fy)
    settlement.update(settlement_fields)
    existing = {l["airline_id"]: l for l in store.settlement_lines.values()
                if l["annual_settlement_id"] == settlement["id"]}
    ts = stamp()
    for airline_id, fields in line_fields.items():
        line = existing.get(airline_id)
        if line is None:
            line = {
                "id": new_id(),
                "annual_settlement_id": settlement["id"],
                "airline_id": airline_id,
                "actual_airfield_share_cents": fields["actual_airfield_share_cents"],
                "actual_terminal_share_cents": fields["actual_terminal_share_cents"],
                "billed_landing_cents": fields["billed_landing_cents"],
                "billed_terminal_cents": fields["billed_terminal_cents"],
                "true_up_cents": fields["true_up_cents"],
                "payment_status": "PENDING",
                "created_at": ts,
                "updated_at": ts,
                "version": 1,
                "_created_dt": now_dt(),
                "_seq": next(store.seq),
                "_due_dt": None,
            }
            store.settlement_lines[line["id"]] = line
        else:
            for key in ("actual_airfield_share_cents", "actual_terminal_share_cents",
                        "billed_landing_cents", "billed_terminal_cents", "true_up_cents"):
                line[key] = fields[key]
            touch(line)


@bp.get("/airport/fiscal_years/<fy_id>/settlement")
def get_fy_settlement(fy_id):
    authenticate(READ_ROLES)
    fy = _get_fy(fy_id)
    items = []
    if fy["settlement_id"] is not None:
        settlement = store.settlements.get(fy["settlement_id"])
        if settlement is not None:
            items.append(settlement)
    data, meta = paginate(items, ser_settlement)
    return success_list(data, meta)


# ---------------------------------------------------------------------------
# PFCApplication (create + per-year list)
# ---------------------------------------------------------------------------
@bp.post("/airport/fiscal_years/<fy_id>/pfc_applications")
def create_pfc_application(fy_id):
    uid, _ = authenticate(("SignatoryAirline",))
    fy = _get_fy(fy_id)
    body = json_body()
    airline = resolve_fk(body, "airline_id", store.airlines)  # priority 4
    airline_id = req_string(body, "airline_id")               # priority 5
    enplaned = req_int(body, "enplaned_passengers", minimum=0)
    require_ownership(uid, airline_id)                        # ownership
    # priority 9 then 10
    check_fy_open_guard(fy)
    ag = services.active_agreement(fy["id"], airline_id)
    if ag is not None and ag["credit_standing"] == "SUSPENDED":
        raise errors.airline_suspended()
    # priority 17: eligibility
    if airline["carrier_class"] != "PASSENGER" or not airline["pfc_approved"]:
        raise errors.pfc_ineligible()
    ts = stamp()
    app = {
        "id": new_id(),
        "fiscal_year_id": fy["id"],
        "airline_id": airline["id"],
        "enplaned_passengers": enplaned,
        "pfc_amount_cents": pfc_amount(enplaned),
        "status": "SUBMITTED",
        "rejection_reason": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_created_dt": now_dt(),
        "_seq": next(store.seq),
    }
    store.pfc_applications[app["id"]] = app
    return success_object(ser_pfc(app), status=201)


@bp.get("/airport/fiscal_years/<fy_id>/pfc_applications")
def list_pfc_applications(fy_id):
    authenticate(READ_ROLES)
    fy = _get_fy(fy_id)
    items = [p for p in store.pfc_applications.values() if p["fiscal_year_id"] == fy["id"]]
    airline_id = helpers.request.args.get("airline_id")
    if airline_id is not None:
        items = [p for p in items if p["airline_id"] == airline_id]
    status = helpers.request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    data, meta = paginate(items, ser_pfc)
    return success_list(data, meta)


# ---------------------------------------------------------------------------
# Agreements keyed to a fiscal year (reverse reachability)
# ---------------------------------------------------------------------------
@bp.get("/airport/fiscal_years/<fy_id>/agreements")
def list_fy_agreements(fy_id):
    authenticate(READ_ROLES)
    fy = _get_fy(fy_id)
    items = [a for a in store.agreements.values() if a["fiscal_year_id"] == fy["id"]]
    data, meta = paginate(items, ser_agreement)
    return success_list(data, meta)
