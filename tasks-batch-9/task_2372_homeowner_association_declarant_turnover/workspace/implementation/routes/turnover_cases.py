"""Turnover cases: creation, reads, trigger certification and dimension advance."""
from datetime import timedelta

from flask import Blueprint

import auth
import calc
import cascades
import clock
import constants
import response
import util
import validation as v
from db import db, new_record, serialize, serialize_list, touch
from errors import ApiError
from routes import common

bp = Blueprint("turnover_cases", __name__)


# ------------------------------------------------------------------ create ---
@bp.post("/hoa/turnover-cases")
def create_turnover_case():
    auth.require_roles(constants.ROLE_PLATFORM_ADMIN)
    body = v.body()

    association = common.body_association_or_404(v.get_fk(body, "association_id"))
    if association is None:
        raise ApiError("ERR_INVALID_REQUEST", "association_id is required.")

    total_seats = v.get_int(body, "total_seats", minimum=3, maximum=9)
    if total_seats % 2 == 0:
        raise ApiError("ERR_INVALID_REQUEST", "total_seats must be an odd number.")

    if calc.case_for_association(association["id"]) is not None:
        raise ApiError("ERR_TURNOVER_CASE_EXISTS")

    case = new_record({
        "association_id": association["id"],
        "total_seats": total_seats,
        "governance_status": "DECLARANT_CONTROL",
        "financial_status": "SUBSIDY_ACTIVE",
        "turnover_posture": "DECLARANT_CONTROL_OPEN",
        "trigger_basis": None,
        "trigger_certified_at": None,
        "trigger_certified_by_user_id": None,
        "declarant_appointed_seats": 0,
        "owner_elected_seats": 0,
        "vacant_seats": total_seats,
        "owner_elected_seats_required": 0,
        "records_transfer_completeness_pct": 100.00,
        "settlement_blocked": False,
    })
    db.turnover_cases[case["id"]] = case
    return response.object_response(serialize(case), 201)


# -------------------------------------------------------------------- read ---
@bp.get("/hoa/turnover-cases/<case_id>")
def read_turnover_case(case_id):
    auth.require_roles(*constants.ALL_ROLES)
    case = common.turnover_case_or_404(case_id, scoped=True)
    return response.object_response(serialize(case))


@bp.get("/hoa/turnover-cases/<case_id>/records-items")
def list_records_items(case_id):
    auth.require_roles(*constants.ALL_ROLES)
    common.turnover_case_or_404(case_id, scoped=True)
    records = calc.records_items_of(case_id)
    for field in ("category", "status"):
        value = v.query_filter(field)
        if value is not None:
            records = [r for r in records if r[field] == value]
    window, pagination = response.paginate(records)
    return response.array_response(serialize_list(window), pagination)


@bp.get("/hoa/turnover-cases/<case_id>/directors")
def list_directors(case_id):
    auth.require_roles(*constants.ALL_ROLES)
    common.turnover_case_or_404(case_id, scoped=True)
    records = calc.directors_of(case_id)
    for field in ("seat_type", "status"):
        value = v.query_filter(field)
        if value is not None:
            records = [r for r in records if r[field] == value]
    window, pagination = response.paginate(records)
    return response.array_response(serialize_list(window), pagination)


# -------------------------------------------------------- certify trigger ---
@bp.post("/hoa/turnover-cases/<case_id>/certify-trigger")
def certify_trigger(case_id):
    auth.require_roles(constants.ROLE_TRANSITION_COMMITTEE)
    case = common.turnover_case_or_404(case_id, scoped=True)
    body = v.body()
    trigger_basis = v.get_enum(body, "trigger_basis", constants.TRIGGER_BASES)

    cascades.require_not_settled_locked(case["association_id"])

    if case["governance_status"] != "DECLARANT_CONTROL":
        raise ApiError("ERR_TURNOVER_STAGE_INVALID")

    association = db.associations[case["association_id"]]
    now = clock.now()

    if trigger_basis == "PERCENT_SOLD":
        sold = util.to_decimal(association["sold_lot_pct"])
        threshold = util.to_decimal(association["turnover_threshold_pct"])
        if sold < threshold:
            raise ApiError("ERR_TURNOVER_THRESHOLD_NOT_MET")
    else:
        fixed = util.parse_dt(association["fixed_turnover_date"])
        if fixed is None or now < fixed:
            raise ApiError("ERR_FIXED_TURNOVER_DATE_NOT_REACHED")

    # ---- CASCADE-1 hop A ----
    certified_at = util.fmt_dt(now)
    case["governance_status"] = "ELECTION_CALLED"
    case["trigger_basis"] = trigger_basis
    case["trigger_certified_at"] = certified_at
    case["trigger_certified_by_user_id"] = auth.current_user_id()

    # ---- CASCADE-1 hop B: resign the declarant's appointed seats ----
    for director in calc.directors_of(case["id"]):
        if director["seat_type"] != "DECLARANT_APPOINTED" or director["status"] != "SEATED":
            continue
        director["status"] = "RESIGNED"
        director["vacated_at"] = util.fmt_dt(now)
        touch(director)

    calc.apply_seat_ledger(case)
    calc.derive_posture(case)
    touch(case)

    # ---- CASCADE-1 hop C: affiliated active contracts become cancellable ----
    window_end = util.fmt_dt(now + timedelta(days=constants.CANCELLATION_WINDOW_DAYS))
    for contract in calc.contracts_of(association["id"]):
        if not contract["developer_affiliated"] or contract["status"] != "ACTIVE":
            continue
        contract["status"] = "CANCELLABLE"
        contract["cancellation_window_end"] = window_end
        touch(contract)

    # ---- CASCADE-1 hops D and E ----
    cascades.mark_forecast_stale(association)

    return response.object_response(serialize(case))


# --------------------------------------------------------------- advance ---
@bp.post("/hoa/turnover-cases/<case_id>/advance")
def advance(case_id):
    auth.require_roles(constants.ROLE_TRANSITION_COMMITTEE)
    case = common.turnover_case_or_404(case_id, scoped=True)
    body = v.body()
    dimension = v.get_enum(body, "dimension", constants.DIMENSIONS)

    subsidy_end_date = None
    if dimension == "FINANCIAL" and case["financial_status"] == "SUBSIDY_ACTIVE":
        subsidy_end_date, _ = v.get_datetime(body, "subsidy_end_date")

    cascades.require_not_settled_locked(case["association_id"])

    association = db.associations[case["association_id"]]

    if dimension == "GOVERNANCE":
        if case["governance_status"] != "ELECTION_HELD":
            raise ApiError("ERR_TURNOVER_STAGE_INVALID")
        if cascades.has_overdue_unbuilt_amenity(association["id"]):
            raise ApiError("ERR_UNBUILT_AMENITY_OUTSTANDING")
        if cascades.records_pct(case) < constants.GOVERNANCE_RECORDS_THRESHOLD_PCT:
            raise ApiError("ERR_RECORDS_INCOMPLETE")
        case["governance_status"] = "OWNER_CONTROL"
        calc.derive_posture(case)
        touch(case)
        return response.object_response(serialize(case))

    # ---------------------------------------------------------- FINANCIAL ---
    if case["financial_status"] == "SUBSIDY_ACTIVE":
        engaged = [
            e for e in calc.engagements_of(association["id"])
            if e["status"] in ("ENGAGED", "ISSUED")
        ]
        if not engaged:
            raise ApiError("ERR_TRANSITION_AUDIT_MISSING")
        case["financial_status"] = "AUDIT_IN_PROGRESS"
        calc.derive_posture(case)
        touch(case)
        association["subsidy_end_date"] = subsidy_end_date
        cascades.mark_forecast_stale(association)
        return response.object_response(serialize(case))

    if case["financial_status"] != "AUDIT_IN_PROGRESS":
        raise ApiError("ERR_TURNOVER_STAGE_INVALID")
    if case["governance_status"] != "OWNER_CONTROL":
        raise ApiError("ERR_TURNOVER_STAGE_INVALID")

    open_claims = [
        c for c in calc.claims_of(association["id"])
        if c["status"] in ("INVESTIGATING", "NOTICED", "REJECTED_BY_DEVELOPER")
    ]
    if open_claims:
        raise ApiError("ERR_CLAIM_STATE_INVALID")

    if cascades.has_cancellable_affiliated_contract(association["id"]):
        raise ApiError("ERR_ASSIGNMENT_CONSENT_REQUIRED")
    if cascades.has_overdue_unbuilt_amenity(association["id"]):
        raise ApiError("ERR_UNBUILT_AMENITY_OUTSTANDING")
    if cascades.records_pct(case) != constants.SETTLEMENT_RECORDS_THRESHOLD_PCT:
        raise ApiError("ERR_RECORDS_INCOMPLETE")

    if case["settlement_blocked"]:
        raise ApiError("ERR_SETTLEMENT_BLOCKED")
    clean = [
        e for e in calc.engagements_of(association["id"])
        if e["status"] == "ISSUED" and e["finding_status"] == "CLEAN"
    ]
    if not clean:
        raise ApiError("ERR_SETTLEMENT_BLOCKED")

    case["financial_status"] = "SETTLED"
    calc.derive_posture(case)
    touch(case)
    return response.object_response(serialize(case))
