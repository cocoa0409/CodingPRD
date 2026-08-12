from flask import Blueprint, request
from middleware import get_caller, require_role, get_json_body
from services.common import require_string, require_enum, parse_pagination
from response import success_object, success_list
from errors import ApiError
from db import db, new_common, touch, CLOCK, add_days, add_year
from services.serialize import serialize

bp = Blueprint("notices", __name__)
READ_ROLES = {"FarmManager", "Landlord", "Tenant"}
SERVED_BY = {"LANDLORD", "TENANT"}


@bp.route("/notices", methods=["POST"])
def create_notice():
    user_id, role = get_caller()
    require_role(role, {"Landlord", "Tenant"})
    body = get_json_body()
    lease_id = require_string(body, "lease_id")
    served_by = require_enum(body, "served_by", SERVED_BY)

    # served_by must match caller role
    if role == "Landlord" and served_by != "LANDLORD":
        raise ApiError("ERR_VALIDATION", 400, "served_by must be LANDLORD for a Landlord caller")
    if role == "Tenant" and served_by != "TENANT":
        raise ApiError("ERR_VALIDATION", 400, "served_by must be TENANT for a Tenant caller")

    lease = db.leases.get(lease_id)
    if lease is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Lease {lease_id} not found")

    # Ownership: caller must be the serving party to this lease
    if role == "Landlord" and lease["landlord_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Caller is not the lease landlord")
    if role == "Tenant" and lease["tenant_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "Caller is not the lease tenant")

    # State: lease must be ACTIVE
    if lease["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Notice requires an ACTIVE lease (state is {lease['status']})")

    clock = CLOCK.get()
    statutory_deadline = add_days(lease["term_end_date"], -lease["notice_lead_days"])
    if clock <= statutory_deadline:
        effective_date = lease["term_end_date"]
    else:
        # Late service: effective at end of following term (renewed term_end_date)
        effective_date = add_year(lease["term_end_date"])

    rec = new_common()
    rec.update({
        "lease_id": lease_id,
        "served_by": served_by,
        "served_date": clock,
        "statutory_deadline": statutory_deadline,
        "effective_date": effective_date,
        "status": "SERVED",
    })
    db.notices[rec["id"]] = rec

    lease["status"] = "TERMINATION_PENDING"
    touch(lease)
    return success_object(serialize("notice", rec), status=201)


@bp.route("/notices/<noticeId>", methods=["GET"])
def get_notice(noticeId):
    _, role = get_caller()
    require_role(role, READ_ROLES)
    rec = db.notices.get(noticeId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Notice {noticeId} not found")
    return success_object(serialize("notice", rec))


@bp.route("/notices", methods=["GET"])
def list_notices():
    _, role = get_caller()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    items = sorted(db.notices.values(), key=lambda r: r["created_at"])
    lease_q = request.args.get("lease_id")
    if lease_q is not None:
        items = [r for r in items if r["lease_id"] == lease_q]
    status_q = request.args.get("status")
    if status_q is not None:
        items = [r for r in items if r["status"] == status_q]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize("notice", r) for r in page], limit, offset, total)


@bp.route("/notices/<noticeId>/withdraw", methods=["POST"])
def withdraw_notice(noticeId):
    user_id, role = get_caller()
    require_role(role, {"Landlord", "Tenant"})
    rec = db.notices.get(noticeId)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, f"Notice {noticeId} not found")
    lease = db.leases.get(rec["lease_id"])
    if lease is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Notice lease missing")

    # Caller must be the serving party and a party to the lease
    if rec["served_by"] == "LANDLORD":
        if role != "Landlord" or lease["landlord_id"] != user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                           "Caller is not the serving party")
    else:  # TENANT
        if role != "Tenant" or lease["tenant_id"] != user_id:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                           "Caller is not the serving party")

    if rec["status"] != "SERVED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       f"Notice in state {rec['status']} cannot be withdrawn")

    rec["status"] = "WITHDRAWN"
    touch(rec)
    if lease["status"] == "TERMINATION_PENDING":
        lease["status"] = "ACTIVE"
        touch(lease)
    return success_object(serialize("notice", rec))
