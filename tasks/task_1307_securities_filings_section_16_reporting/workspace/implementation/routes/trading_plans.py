"""TradingPlan10b5_1 CRUD + lifecycle transitions."""
from flask import Blueprint, request

from db import db
from errors import (
    ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_PLAN_INVALID_STATE,
    ERR_PLAN_WINDOW_OVERLAP, ERR_COOLING_OFF_NOT_SATISFIED,
    ERR_FORBIDDEN_ROLE, ApiError,
)
from middleware import require_role, get_auth
from response import success_object, success_list
from utils import (
    PLAN_FIELDS, serialize, stamp_created, bump_version,
    parse_pagination, paginate, today_stamp, parse_date, logical_clock_date,
)
from services.calculations import compute_cooling_off_end_date

plans_bp = Blueprint("trading_plans", __name__)


def _get_plan_or_404(pid):
    p = db.trading_plans.get(pid)
    if not p:
        raise ApiError(ERR_NOT_FOUND, f"TradingPlan10b5_1 {pid} not found.", 404)
    return p


@plans_bp.route("/trading-plans", methods=["POST"])
def create_plan():
    user_id, role = require_role("ReportingInsider")
    body = request.get_json(force=True) or {}

    for f in ["reporting_person_id", "plan_name", "first_trade_date", "expiration_date"]:
        if f not in body or body[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, f"{f} is required.", 400)

    if body["reporting_person_id"] != user_id:
        raise ApiError(ERR_FORBIDDEN_ROLE, "reporting_person_id must equal X-User-ID.", 403)

    if body["reporting_person_id"] not in db.reporting_persons:
        raise ApiError(ERR_INVALID_REQUEST, f"reporting_person_id {body['reporting_person_id']} not found.", 400)

    person = db.reporting_persons[body["reporting_person_id"]]

    try:
        ftd = parse_date(body["first_trade_date"])
        ed = parse_date(body["expiration_date"])
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, "first_trade_date and expiration_date must be YYYY-MM-DD.", 400)

    if ed <= ftd:
        raise ApiError(ERR_INVALID_REQUEST, "expiration_date must be after first_trade_date.", 400)

    plan = {
        "reporting_person_id": body["reporting_person_id"],
        "issuer_id": person["issuer_id"],
        "plan_name": body["plan_name"],
        "first_trade_date": body["first_trade_date"],
        "expiration_date": body["expiration_date"],
        "status": "DRAFT",
        "adoption_date": None,
        "cooling_off_end_date": None,
        "termination_date": None,
    }
    stamp_created(plan)
    db.trading_plans[plan["id"]] = plan
    return success_object(serialize(plan, PLAN_FIELDS), 201)


@plans_bp.route("/trading-plans", methods=["GET"])
def list_plans():
    get_auth()
    limit, offset = parse_pagination(request.args)
    items = sorted(db.trading_plans.values(), key=lambda x: x["created_at"])
    for param in ["reporting_person_id", "issuer_id", "status"]:
        val = request.args.get(param)
        if val:
            items = [p for p in items if str(p.get(param)) == val]
    page, total = paginate(items, limit, offset)
    return success_list([serialize(p, PLAN_FIELDS) for p in page], limit, offset, total)


@plans_bp.route("/trading-plans/<planId>", methods=["GET"])
def get_plan(planId):
    get_auth()
    p = _get_plan_or_404(planId)
    return success_object(serialize(p, PLAN_FIELDS))


@plans_bp.route("/trading-plans/<planId>/transitions", methods=["POST"])
def plan_transition(planId):
    user_id, role = get_auth()
    plan = _get_plan_or_404(planId)
    body = request.get_json(force=True) or {}
    action = body.get("action")
    if not action:
        raise ApiError(ERR_INVALID_REQUEST, "action is required.", 400)

    if action == "SUBMIT_ADOPTION":
        if role != "ReportingInsider":
            raise ApiError(ERR_FORBIDDEN_ROLE, "SUBMIT_ADOPTION requires ReportingInsider.", 403)
        if user_id != plan["reporting_person_id"]:
            raise ApiError(ERR_FORBIDDEN_ROLE, "Only the owning insider may submit adoption.", 403)
        if plan["status"] != "DRAFT":
            raise ApiError(ERR_PLAN_INVALID_STATE, "SUBMIT_ADOPTION requires DRAFT.", 409)
        plan["status"] = "PENDING_APPROVAL"

    elif action == "APPROVE":
        if role != "ComplianceOfficer":
            raise ApiError(ERR_FORBIDDEN_ROLE, "APPROVE requires ComplianceOfficer.", 403)
        if plan["status"] != "PENDING_APPROVAL":
            raise ApiError(ERR_PLAN_INVALID_STATE, "APPROVE requires PENDING_APPROVAL.", 409)
        # Window overlap check
        for other in db.trading_plans.values():
            if other["id"] == plan["id"]:
                continue
            if other["reporting_person_id"] != plan["reporting_person_id"]:
                continue
            if other["status"] not in ("ADOPTED", "ACTIVE", "SUSPENDED"):
                continue
            a_start = parse_date(plan["first_trade_date"])
            a_end = parse_date(plan["expiration_date"])
            b_start = parse_date(other["first_trade_date"])
            b_end = parse_date(other["expiration_date"])
            if a_start < b_end and b_start < a_end:
                raise ApiError(ERR_PLAN_WINDOW_OVERLAP, "Plan window overlaps another active plan.", 409)
        person = db.reporting_persons[plan["reporting_person_id"]]
        issuer = db.issuers[plan["issuer_id"]]
        plan["adoption_date"] = today_stamp()
        plan["cooling_off_end_date"] = compute_cooling_off_end_date(plan, person, issuer)
        plan["status"] = "ADOPTED"

    elif action == "REJECT":
        if role != "ComplianceOfficer":
            raise ApiError(ERR_FORBIDDEN_ROLE, "REJECT requires ComplianceOfficer.", 403)
        if plan["status"] != "PENDING_APPROVAL":
            raise ApiError(ERR_PLAN_INVALID_STATE, "REJECT requires PENDING_APPROVAL.", 409)
        plan["status"] = "REJECTED"

    elif action == "ACTIVATE":
        if role != "ComplianceOfficer":
            raise ApiError(ERR_FORBIDDEN_ROLE, "ACTIVATE requires ComplianceOfficer.", 403)
        if plan["status"] != "ADOPTED":
            raise ApiError(ERR_PLAN_INVALID_STATE, "ACTIVATE requires ADOPTED.", 409)
        if logical_clock_date() < parse_date(plan["cooling_off_end_date"]):
            raise ApiError(ERR_COOLING_OFF_NOT_SATISFIED, "Cooling-off period not yet satisfied.", 422)
        plan["status"] = "ACTIVE"

    elif action == "SUSPEND":
        if role != "ComplianceOfficer":
            raise ApiError(ERR_FORBIDDEN_ROLE, "SUSPEND requires ComplianceOfficer.", 403)
        if plan["status"] != "ACTIVE":
            raise ApiError(ERR_PLAN_INVALID_STATE, "SUSPEND requires ACTIVE.", 409)
        plan["status"] = "SUSPENDED"

    elif action == "REINSTATE":
        if role != "ComplianceOfficer":
            raise ApiError(ERR_FORBIDDEN_ROLE, "REINSTATE requires ComplianceOfficer.", 403)
        if plan["status"] != "SUSPENDED":
            raise ApiError(ERR_PLAN_INVALID_STATE, "REINSTATE requires SUSPENDED.", 409)
        plan["status"] = "ACTIVE"

    elif action == "TERMINATE":
        if role not in ("ComplianceOfficer", "ReportingInsider"):
            raise ApiError(ERR_FORBIDDEN_ROLE, "TERMINATE requires ComplianceOfficer or ReportingInsider.", 403)
        if role == "ReportingInsider" and user_id != plan["reporting_person_id"]:
            raise ApiError(ERR_FORBIDDEN_ROLE, "Only the owning insider may terminate.", 403)
        if plan["status"] not in ("ADOPTED", "ACTIVE", "SUSPENDED"):
            raise ApiError(ERR_PLAN_INVALID_STATE, "TERMINATE requires ADOPTED, ACTIVE, or SUSPENDED.", 409)
        plan["termination_date"] = today_stamp()
        plan["status"] = "TERMINATED"

    else:
        raise ApiError(ERR_INVALID_REQUEST, f"Unknown action: {action}", 400)

    bump_version(plan)
    return success_object(serialize(plan, PLAN_FIELDS))
