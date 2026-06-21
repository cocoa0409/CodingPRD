"""Fine endpoints: read, list, pay, waive."""
from flask import Blueprint, request

from db import db, touch
from errors import err, ERR_INVALID_STATE, ERR_NOT_ACCOUNT_OWNER
from middleware import authenticate, require_role
from response import success, list_response
from services import common
from services.derive import serialize_fine

bp = Blueprint("fines", __name__)


@bp.route("/fines/<fid>", methods=["GET"])
def get_fine(fid):
    caller = authenticate()
    require_role(caller, {"Administrator", "MonitoringOperator", "Subscriber"})
    fine = common.lookup(db.fines, fid)
    return success(serialize_fine(fine))


@bp.route("/fines", methods=["GET"])
def list_fines():
    caller = authenticate()
    require_role(caller, {"Administrator", "MonitoringOperator", "Subscriber"})
    limit, offset = common.parse_pagination()
    account_id = request.args.get("account_id")
    alarm_event_id = request.args.get("alarm_event_id")
    settlement_status = request.args.get("settlement_status")
    items = list(db.fines.values())
    if account_id is not None:
        items = [f for f in items if f["account_id"] == account_id]
    if alarm_event_id is not None:
        items = [f for f in items if f["alarm_event_id"] == alarm_event_id]
    if settlement_status is not None:
        items = [f for f in items if f["settlement_status"] == settlement_status]
    items = common.sort_by_created(items)
    window, total = common.paginate(items, limit, offset)
    return list_response([serialize_fine(f) for f in window], limit, offset, total)


@bp.route("/fines/<fid>/pay", methods=["POST"])
def pay_fine(fid):
    caller = authenticate()
    require_role(caller, {"Subscriber", "Administrator"})
    fine = common.lookup(db.fines, fid)
    if caller.role == "Subscriber" and caller.user_id != fine["account_id"]:
        raise err(ERR_NOT_ACCOUNT_OWNER, "Subscriber is not the owner of this fine's account")
    if fine["settlement_status"] != "ASSESSED":
        raise err(ERR_INVALID_STATE, "Fine is not ASSESSED")
    fine["settlement_status"] = "PAID"
    touch(fine)
    return success(serialize_fine(fine))


@bp.route("/fines/<fid>/waive", methods=["POST"])
def waive_fine(fid):
    caller = authenticate()
    require_role(caller, {"Administrator"})
    fine = common.lookup(db.fines, fid)
    if fine["settlement_status"] != "ASSESSED":
        raise err(ERR_INVALID_STATE, "Fine is not ASSESSED")
    fine["settlement_status"] = "WAIVED"
    touch(fine)
    return success(serialize_fine(fine))
