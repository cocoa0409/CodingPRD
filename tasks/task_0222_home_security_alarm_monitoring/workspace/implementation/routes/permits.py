"""Permit endpoints: issue, read, list, revoke, expire."""
from flask import Blueprint, request

import clock
from db import db, new_id, new_common, touch
from errors import (
    err,
    ERR_REFERENCE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_PERMIT_ALREADY_ACTIVE,
    ERR_DUPLICATE_PERMIT_NUMBER,
)
from middleware import authenticate, require_role
from response import success, list_response
from services import validate, common, calc
from services.derive import serialize_permit

bp = Blueprint("permits", __name__)


@bp.route("/permits", methods=["POST"])
def create_permit():
    caller = authenticate()
    require_role(caller, {"Administrator"})
    body = validate.get_body()

    # FK presence + resolution
    account_id = validate.require_str(body, "account_id")
    if account_id not in db.accounts:
        raise err(ERR_REFERENCE_NOT_FOUND, "account_id does not resolve: %s" % account_id)

    permit_number = validate.require_str(body, "permit_number")
    filed_days_late = validate.require_int(body, "filed_days_late", minimum=0)

    # At most one ACTIVE permit per account (priority 12) before duplicate
    # permit_number (priority 18).
    for p in db.permits.values():
        if p["account_id"] == account_id and p["status"] == "ACTIVE":
            raise err(ERR_PERMIT_ALREADY_ACTIVE, "Account already holds an ACTIVE permit")

    for p in db.permits.values():
        if p["permit_number"] == permit_number:
            raise err(ERR_DUPLICATE_PERMIT_NUMBER, "permit_number already issued")

    account = db.accounts[account_id]
    fee_total = calc.permit_fee(account["premises_type"], filed_days_late)

    pid = new_id()
    permit = {"id": pid}
    permit.update(new_common())
    permit.update({
        "account_id": account_id,
        "permit_number": permit_number,
        "status": "ACTIVE",
        "filed_days_late": filed_days_late,
        "cycle_anchor_utc": clock.now(),
        "fee_total_cents": fee_total,
    })
    db.permits[pid] = permit
    return success(serialize_permit(permit), http_status=201)


@bp.route("/permits/<pid>", methods=["GET"])
def get_permit(pid):
    caller = authenticate()
    require_role(caller, {"Administrator", "MonitoringOperator", "Subscriber"})
    permit = common.lookup(db.permits, pid)
    return success(serialize_permit(permit))


@bp.route("/permits", methods=["GET"])
def list_permits():
    caller = authenticate()
    require_role(caller, {"Administrator", "MonitoringOperator", "Subscriber"})
    limit, offset = common.parse_pagination()
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    items = list(db.permits.values())
    if account_id is not None:
        items = [p for p in items if p["account_id"] == account_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = common.sort_by_created(items)
    window, total = common.paginate(items, limit, offset)
    return list_response([serialize_permit(p) for p in window], limit, offset, total)


@bp.route("/permits/<pid>/revoke", methods=["POST"])
def revoke_permit(pid):
    caller = authenticate()
    require_role(caller, {"Administrator"})
    permit = common.lookup(db.permits, pid)
    if permit["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Permit is not ACTIVE")
    permit["status"] = "REVOKED"
    touch(permit)
    return success(serialize_permit(permit))


@bp.route("/permits/<pid>/expire", methods=["POST"])
def expire_permit(pid):
    caller = authenticate()
    require_role(caller, {"Administrator"})
    permit = common.lookup(db.permits, pid)
    if permit["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Permit is not ACTIVE")
    permit["status"] = "EXPIRED"
    touch(permit)
    return success(serialize_permit(permit))
