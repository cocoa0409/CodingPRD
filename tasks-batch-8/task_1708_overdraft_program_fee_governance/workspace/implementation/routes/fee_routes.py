from flask import Blueprint, request

import db
from errors import ApiError, ERR_NOT_FOUND
from helpers import auth, require_role, ok, ok_list, ALL_ROLES, sort_created
from serializers import fee_to_dict

bp = Blueprint("fees", __name__)


@bp.get("/v1/fees")
def list_fees():
    _, role = auth()
    require_role(role, ALL_ROLES)
    items = list(db.store["fees"].values())
    account_id = request.args.get("account_id")
    batch_id = request.args.get("batch_id")
    transaction_id = request.args.get("transaction_id")
    status = request.args.get("status")
    fee_type = request.args.get("fee_type")
    if account_id is not None:
        items = [f for f in items if f["account_id"] == account_id]
    if batch_id is not None:
        items = [f for f in items if f["batch_id"] == batch_id]
    if transaction_id is not None:
        items = [f for f in items if f["transaction_id"] == transaction_id]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    if fee_type is not None:
        items = [f for f in items if f["fee_type"] == fee_type]
    return ok_list([fee_to_dict(f) for f in sort_created(items)])


@bp.get("/v1/fees/<fid>")
def get_fee(fid):
    _, role = auth()
    require_role(role, ALL_ROLES)
    f = db.store["fees"].get(fid)
    if f is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Fee %s not found" % fid)
    return ok(fee_to_dict(f))
