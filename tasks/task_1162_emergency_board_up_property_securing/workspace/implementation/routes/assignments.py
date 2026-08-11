"""Assignment endpoints: list/get/respond/withdraw."""
from flask import Blueprint, request
import db
from db import clock, format_ts, iso_now, parse_ts
from errors import err
from middleware import require_role, get_body, require_fields, check_enum, paginate_args
from response import success_obj, success_list
from services.common import (
    touch, get_or_404, serialize_assignment,
    recompute_active_assignment_count,
)
from services import dispatch as dispatch_svc

bp = Blueprint("assignments", __name__)


@bp.route("/assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    require_role("PlatformAdmin", "Dispatcher", "Customer", "Subcontractor")
    rec = get_or_404(db.assignments, aid, "Assignment")
    return success_obj(serialize_assignment(rec))


@bp.route("/assignments", methods=["GET"])
def list_assignments():
    require_role("PlatformAdmin", "Dispatcher", "Customer", "Subcontractor")
    limit, offset = paginate_args()
    items = list(db.assignments.values())
    jid = request.args.get("job_id")
    sid = request.args.get("subcontractor_id")
    status = request.args.get("status")
    if jid:
        items = [a for a in items if a["job_id"] == jid]
    if sid:
        items = [a for a in items if a["subcontractor_id"] == sid]
    if status:
        items = [a for a in items if a["status"] == status]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_assignment(a) for a in page], total, limit, offset)


@bp.route("/assignments/<aid>/respond", methods=["POST"])
def respond_assignment(aid):
    user_id, _ = require_role("Subcontractor")
    a = get_or_404(db.assignments, aid, "Assignment")
    body = get_body()
    require_fields(body, ["outcome"])
    outcome = check_enum(body["outcome"], {"ACCEPT", "DECLINE"}, "outcome")
    # Assignee check
    if a["subcontractor_id"] != user_id:
        raise err("ERR_NOT_ASSIGNEE", "Caller is not the offeree")
    # Terminal states first
    if a["status"] in ("COMPLETED", "DECLINED", "EXPIRED", "CANCELLED"):
        raise err("ERR_ALREADY_TERMINAL", "Assignment already terminal")
    if a["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "Assignment must be OFFERED")
    # Expiry check
    now_dt = clock.now()
    expiry = parse_ts(a["offer_expires_at"])
    if now_dt > expiry:
        # transition to EXPIRED and fail
        dispatch_svc.expire_offer_and_cascade(a)
        raise err("ERR_OFFER_EXPIRED", "Offer has expired")
    a["responded_at"] = iso_now()
    if outcome == "ACCEPT":
        a["status"] = "ACCEPTED"
        touch(a)
        recompute_active_assignment_count(a["subcontractor_id"])
    else:  # DECLINE
        a["status"] = "DECLINED"
        touch(a)
        job = db.jobs.get(a["job_id"])
        if job is not None:
            dispatch_svc.run_reoffer_cascade(job)
    return success_obj(serialize_assignment(a))


@bp.route("/assignments/<aid>/withdraw", methods=["POST"])
def withdraw_assignment(aid):
    require_role("Dispatcher")
    a = get_or_404(db.assignments, aid, "Assignment")
    if a["status"] in ("COMPLETED", "DECLINED", "EXPIRED", "CANCELLED"):
        raise err("ERR_ALREADY_TERMINAL", "Assignment already terminal")
    if a["status"] not in ("OFFERED", "ACCEPTED"):
        raise err("ERR_INVALID_STATE", "Assignment must be OFFERED or ACCEPTED")
    now_dt = clock.now()
    if a["status"] == "OFFERED":
        expiry = parse_ts(a["offer_expires_at"])
        if now_dt > expiry:
            # withdraw arriving past expiry takes EXPIRED path
            dispatch_svc.expire_offer_and_cascade(a)
            raise err("ERR_OFFER_EXPIRED", "Offer has expired")
    was_accepted = a["status"] == "ACCEPTED"
    a["status"] = "CANCELLED"
    touch(a)
    if was_accepted:
        recompute_active_assignment_count(a["subcontractor_id"])
    job = db.jobs.get(a["job_id"])
    if job is not None:
        dispatch_svc.run_reoffer_cascade(job)
    return success_obj(serialize_assignment(a))
