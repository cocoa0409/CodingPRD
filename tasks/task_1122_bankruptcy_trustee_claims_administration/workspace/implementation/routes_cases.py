"""Case endpoints: intake, posture transitions, no-asset exit, conversion."""
from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_DUPLICATE, ERR_INVALID_STATE, ERR_NO_ASSETS_SCHEDULED,
    ERR_INVALID_BAR_DATE, ERR_BAR_DATE_NOT_PASSED, ERR_CLAIMS_UNREVIEWED,
    ERR_ASSETS_PENDING_SALE, ERR_OBJECTIONS_PENDING, ERR_NO_FUNDS_TO_DISTRIBUTE,
    ERR_PLAN_EXECUTING,
)
from middleware import auth_context, require_roles, json_body, ALL_ROLES
from response import ok_object, paginate
from services_common import (
    new_entity, touch, bump_case, get_case, ensure_case_open,
    ensure_trustee_binding, ser_case, sorted_rows,
)
from util import parse_datetime, require_str, optional_int, to_seconds

bp = Blueprint("cases", __name__)


@bp.route("/trustee/cases", methods=["POST"])
def create_case():
    _, role = auth_context()
    require_roles(role, ("Clerk",))
    body = json_body()

    # Tier 9 (uniqueness) precedes tier 13 (body shape) per PRD §2.11.
    raw_number = body.get("case_number")
    if isinstance(raw_number, str):
        for existing in db.cases.values():
            if existing["case_number"] == raw_number:
                raise ApiError(ERR_DUPLICATE, 409, "case_number already exists.")

    case_number = require_str(body, "case_number")
    debtor_name = require_str(body, "debtor_name")
    filed_on = parse_datetime(body.get("filed_on"), "filed_on")
    district = require_str(body, "district")
    trustee_user_id = require_str(body, "trustee_user_id")
    scheduled_unsecured = optional_int(body, "scheduled_unsecured_total_cents", minimum=0)
    objection_window = optional_int(body, "objection_window_days", minimum=0)

    case = new_entity({
        "case_number": case_number,
        "debtor_name": debtor_name,
        "filed_on": filed_on,
        "district": district,
        "status": "OPEN",
        "claim_bar_date": None,
        "bar_date_noticed": False,
        "estate_cash_on_hand_cents": 0,
        "allowed_claims_total_cents": 0,
        "scheduled_unsecured_total_cents": scheduled_unsecured if scheduled_unsecured is not None else 0,
        "no_asset_report_filed": False,
        "objection_window_days": objection_window if objection_window is not None else 30,
        "trustee_user_id": trustee_user_id,
    })
    db.cases[case["id"]] = case
    return ok_object(ser_case(case), status=201)


@bp.route("/trustee/cases", methods=["GET"])
def list_cases():
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    status = request.args.get("status")
    trustee_user_id = request.args.get("trustee_user_id")
    rows = list(db.cases.values())
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    if trustee_user_id is not None:
        rows = [c for c in rows if c["trustee_user_id"] == trustee_user_id]
    return paginate([ser_case(c) for c in sorted_rows(rows)])


@bp.route("/trustee/cases/<id>", methods=["GET"])
def get_case_endpoint(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    return ok_object(ser_case(get_case(id)))


@bp.route("/trustee/cases/<id>/begin_investigation", methods=["POST"])
def begin_investigation(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    case = get_case(id)
    ensure_case_open(case)
    if case["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Case must be OPEN to begin investigation.")
    ensure_trustee_binding(case, uid)
    if not any(a["case_id"] == id for a in db.assets.values()):
        raise ApiError(ERR_NO_ASSETS_SCHEDULED, 409, "No assets are scheduled for the case.")
    case["status"] = "ASSET_INVESTIGATION"
    bump_case(case)
    return ok_object(ser_case(case))


@bp.route("/trustee/cases/<id>/set_bar_date", methods=["POST"])
def set_bar_date(id):
    _, role = auth_context()
    require_roles(role, ("Clerk",))
    case = get_case(id)
    ensure_case_open(case)
    if case["status"] != "ASSET_INVESTIGATION":
        raise ApiError(ERR_INVALID_STATE, 409, "Case must be in ASSET_INVESTIGATION to set the bar date.")
    body = json_body()
    bar_date = parse_datetime(body.get("bar_date"), "bar_date")
    if bar_date <= case["filed_on"]:
        raise ApiError(ERR_INVALID_BAR_DATE, 422, "bar_date must be strictly after the petition filing date.")
    case["claim_bar_date"] = bar_date
    case["bar_date_noticed"] = True
    case["status"] = "CLAIMS_ADMINISTRATION"
    for asset in db.assets.values():
        if asset["case_id"] == id and asset["status"] == "SCHEDULED":
            asset["status"] = "UNDER_INVESTIGATION"
            touch(asset)
    bump_case(case)
    return ok_object(ser_case(case))


@bp.route("/trustee/cases/<id>/begin_liquidation", methods=["POST"])
def begin_liquidation(id):
    from logical_clock import CLOCK
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    case = get_case(id)
    ensure_case_open(case)
    if case["status"] != "CLAIMS_ADMINISTRATION":
        raise ApiError(ERR_INVALID_STATE, 409, "Case must be in CLAIMS_ADMINISTRATION to begin liquidation.")
    ensure_trustee_binding(case, uid)
    bar = case["claim_bar_date"]
    if bar is None or to_seconds(CLOCK.now()) <= to_seconds(bar):
        raise ApiError(ERR_BAR_DATE_NOT_PASSED, 409, "The claims bar date has not passed.")
    if any(c["case_id"] == id and c["status"] == "FILED" for c in db.claims.values()):
        raise ApiError(ERR_CLAIMS_UNREVIEWED, 409, "Claims remain in FILED status.")
    case["status"] = "LIQUIDATION"
    bump_case(case)
    return ok_object(ser_case(case))


@bp.route("/trustee/cases/<id>/begin_distribution", methods=["POST"])
def begin_distribution(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    case = get_case(id)
    ensure_case_open(case)
    if case["status"] != "LIQUIDATION":
        raise ApiError(ERR_INVALID_STATE, 409, "Case must be in LIQUIDATION to begin distribution.")
    ensure_trustee_binding(case, uid)
    if any(a["case_id"] == id and a["status"] in ("MARKED_FOR_SALE", "IN_AUCTION")
           for a in db.assets.values()):
        raise ApiError(ERR_ASSETS_PENDING_SALE, 409, "Assets remain pending sale.")
    if any(c["case_id"] == id and c["status"] == "OBJECTED" for c in db.claims.values()):
        raise ApiError(ERR_OBJECTIONS_PENDING, 409, "Claims remain OBJECTED.")
    if case["estate_cash_on_hand_cents"] <= 0:
        raise ApiError(ERR_NO_FUNDS_TO_DISTRIBUTE, 409, "Estate cash on hand is not positive.")
    case["status"] = "DISTRIBUTION"
    bump_case(case)
    return ok_object(ser_case(case))


@bp.route("/trustee/cases/<id>/file_no_asset_report", methods=["POST"])
def file_no_asset_report(id):
    uid, role = auth_context()
    require_roles(role, ("Trustee",))
    case = get_case(id)
    ensure_case_open(case)
    if case["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Case must be OPEN to file a no-asset report.")
    ensure_trustee_binding(case, uid)
    if any(a["case_id"] == id for a in db.assets.values()):
        raise ApiError(ERR_INVALID_STATE, 409, "Asset rows exist; the no-asset path is unavailable.")
    if any(c["case_id"] == id and c["status"] in ("FILED", "UNDER_REVIEW", "OBJECTED", "ALLOWED")
           for c in db.claims.values()):
        raise ApiError(ERR_INVALID_STATE, 409, "Open claims exist; the no-asset path is unavailable.")
    if case["estate_cash_on_hand_cents"] != 0:
        raise ApiError(ERR_INVALID_STATE, 409, "Estate cash is non-zero; the no-asset path is unavailable.")
    case["no_asset_report_filed"] = True
    case["status"] = "CLOSED"
    bump_case(case)
    return ok_object(ser_case(case))


@bp.route("/trustee/cases/<id>/convert_or_dismiss", methods=["POST"])
def convert_or_dismiss(id):
    _, role = auth_context()
    require_roles(role, ("Court",))
    case = get_case(id)
    ensure_case_open(case)
    if any(p["case_id"] == id and p["status"] == "EXECUTING" for p in db.plans.values()):
        raise ApiError(ERR_PLAN_EXECUTING, 409, "A distribution plan is EXECUTING.")
    for claim in db.claims.values():
        if claim["case_id"] == id and claim["status"] in ("FILED", "UNDER_REVIEW", "OBJECTED"):
            claim["status"] = "WITHDRAWN"
            claim["objection_id"] = None
            touch(claim)
    for asset in db.assets.values():
        if asset["case_id"] == id and asset["status"] in (
                "SCHEDULED", "UNDER_INVESTIGATION", "MARKED_FOR_SALE", "IN_AUCTION"):
            asset["status"] = "ABANDONED"
            touch(asset)
    for action in db.actions.values():
        if action["case_id"] == id and action["status"] not in (
                "RESCINDED", "ABANDONED", "SETTLED", "JUDGMENT"):
            action["status"] = "ABANDONED"
            touch(action)
    case["status"] = "CONVERTED_DISMISSED"
    bump_case(case)
    return ok_object(ser_case(case))
