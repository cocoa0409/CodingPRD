"""JobOrder routes (PRD 3.2)."""

from flask import Blueprint, request

import db
import errors
from errors import ApiError
from middleware import (
    get_user_context, require_role, get_json_body, parse_pagination, paginate,
)
from response import object_response, array_response
from services import common, serialize, recompute

bp = Blueprint("job_orders", __name__)

EMPLOYMENT_TYPES = {"TEMP", "TEMP_TO_PERM", "DIRECT"}
JOB_ORDER_TARGETS = {"OPEN", "ON_HOLD", "CLOSED", "CANCELLED"}


@bp.route("/staffing/job-orders", methods=["POST"])
def create_job_order():
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    body = get_json_body()

    client_id = common.require_str(body, "client_id")
    title = common.require_str(body, "title")
    employment_type = common.require_enum(body, "employment_type", EMPLOYMENT_TYPES)
    required_skill_code = common.require_str(body, "required_skill_code")
    openings = common.require_int(body, "openings")
    bill_rate_cents = common.require_int(body, "bill_rate_cents")
    target_pay_rate_cents = common.require_int(body, "target_pay_rate_cents")
    annual_salary_cents = common.optional_int(body, "annual_salary_cents", 0)

    # Existence (priority 3, before the priority-4 openings range check):
    # client FK, then required_skill_code FK, validated left-to-right.
    common.get_or_404(db.clients, client_id, errors.ERR_CLIENT_NOT_FOUND)
    catalog = {s["code"] for s in db.skills.values()}
    if required_skill_code not in catalog:
        raise ApiError(errors.ERR_SKILL_NOT_FOUND, 404, "required_skill_code not in catalog.")

    # Priority 4 structural range check.
    if openings < 1:
        raise ApiError(errors.ERR_VALIDATION, 422, "openings must be >= 1.")

    rec = common.init_mutable({
        "client_id": client_id,
        "title": title,
        "employment_type": employment_type,
        "required_skill_code": required_skill_code,
        "openings": openings,
        "bill_rate_cents": bill_rate_cents,
        "target_pay_rate_cents": target_pay_rate_cents,
        "annual_salary_cents": annual_salary_cents,
        "filled_count": 0,
        "status": "DRAFT",
    })
    db.job_orders[rec["id"]] = rec
    return object_response(serialize.job_order(rec), 201)


@bp.route("/staffing/job-orders", methods=["GET"])
def list_job_orders():
    _, role = get_user_context()
    require_role(role, {"AccountManager", "Recruiter", "Client"})
    user_id = request.headers.get("X-User-ID")
    limit, offset = parse_pagination()

    client_filter = request.args.get("client_id")
    status_filter = request.args.get("status")

    rows = list(db.job_orders.values())
    if client_filter is not None:
        rows = [r for r in rows if r["client_id"] == client_filter]
    if status_filter is not None:
        rows = [r for r in rows if r["status"] == status_filter]
    if role == "Client":
        rows = [r for r in rows if r["client_id"] == user_id]

    page, total = paginate(rows, limit, offset)
    return array_response([serialize.job_order(r) for r in page], limit, offset, total)


@bp.route("/staffing/job-orders/<jid>", methods=["GET"])
def get_job_order(jid):
    user_id, role = get_user_context()
    require_role(role, {"AccountManager", "Recruiter", "Client"})
    rec = common.get_or_404(db.job_orders, jid, errors.ERR_JOB_ORDER_NOT_FOUND)
    if role == "Client" and rec["client_id"] != user_id:
        raise ApiError(errors.ERR_UNAUTHORIZED, 403, "Client does not own this job order.")
    return object_response(serialize.job_order(rec), 200)


@bp.route("/staffing/job-orders/<jid>", methods=["PATCH"])
def patch_job_order(jid):
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    rec = common.get_or_404(db.job_orders, jid, errors.ERR_JOB_ORDER_NOT_FOUND)
    body = get_json_body()
    target = common.require_enum(body, "target_status", JOB_ORDER_TARGETS)

    status = rec["status"]

    if target == "OPEN":
        # DRAFT -> OPEN (requires client ACTIVE) OR ON_HOLD -> OPEN (resume).
        if status == "DRAFT":
            client = db.clients.get(rec["client_id"])
            if client is not None and client["status"] != "ACTIVE":
                raise ApiError(errors.ERR_CLIENT_SUSPENDED, 409, "Client is SUSPENDED.")
            rec["status"] = "OPEN"
            common.touch(rec)
        elif status == "ON_HOLD":
            rec["status"] = "OPEN"
            common.touch(rec)
        elif status == "OPEN":
            # Already OPEN: resume requires ON_HOLD; opening requires DRAFT.
            # From OPEN, neither precondition holds -> treat as not-on-hold
            # (resume) since the request asks to reach OPEN from a non-hold,
            # non-draft state.
            raise ApiError(errors.ERR_JOB_ORDER_NOT_ON_HOLD, 409, "Job order is not ON_HOLD.")
        else:
            raise ApiError(errors.ERR_JOB_ORDER_NOT_DRAFT, 409, "Job order is not DRAFT.")

    elif target == "ON_HOLD":
        if status != "OPEN":
            raise ApiError(errors.ERR_JOB_ORDER_NOT_OPEN, 409, "Job order is not OPEN.")
        rec["status"] = "ON_HOLD"
        common.touch(rec)

    elif target == "CLOSED":
        if status not in ("OPEN", "ON_HOLD"):
            raise ApiError(errors.ERR_JOB_ORDER_NOT_CLOSEABLE, 409, "Job order is not closeable.")
        rec["status"] = "CLOSED"
        common.touch(rec)
        recompute.cascade_reject_open_submissions(rec["id"], "ORDER_CLOSED")

    elif target == "CANCELLED":
        if status != "DRAFT":
            raise ApiError(errors.ERR_JOB_ORDER_NOT_DRAFT, 409, "Job order is not DRAFT.")
        rec["status"] = "CANCELLED"
        common.touch(rec)

    return object_response(serialize.job_order(rec), 200)
