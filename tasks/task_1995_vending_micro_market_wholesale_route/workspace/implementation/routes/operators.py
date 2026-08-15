"""Operator endpoints (scaffold §1.5)."""
from flask import Blueprint, request
import db
from middleware import get_auth, require_role
from response import success_object, success_list, parse_pagination
from util import get_json_body, req_string, req_enum, stamp_new, touch
from errors import ApiError, ERR_OPERATOR_NOT_FOUND, ERR_OPERATOR_NOT_ACTIVE

bp = Blueprint("operators", __name__)

ALL_ROLES = ["WholesaleAdmin", "OperatorManager", "RoutePlanner", "WarehouseOps", "CreditAdjuster", "TelemetryGateway"]
TENDERS = ["CASH", "CASHLESS"]


def op_view(o):
    return {k: v for k, v in o.items()}


@bp.post("/wholesale/operators")
def create_operator():
    user_id, role = get_auth()
    body = get_json_body()
    require_role(role, ["WholesaleAdmin"])
    name = req_string(body, "name")
    default_tender = body.get("default_tender", "CASH")
    if default_tender is None:
        default_tender = "CASH"
    if not isinstance(default_tender, str) or default_tender not in TENDERS:
        from errors import ERR_INVALID_REQUEST
        raise ApiError(ERR_INVALID_REQUEST, 400, "default_tender must be CASH or CASHLESS")
    op = stamp_new({
        "name": name,
        "default_tender": default_tender,
        "credit_balance_cents": 0,
        "status": "ACTIVE",
    })
    db.operators[op["id"]] = op
    return success_object(op_view(op), 201)


@bp.get("/wholesale/operators")
def list_operators():
    get_auth()
    limit, offset = parse_pagination(request.args)
    status_f = request.args.get("status")
    items = [o for o in db.operators.values()]
    if status_f is not None:
        items = [o for o in items if o["status"] == status_f]
    items.sort(key=lambda o: o["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([op_view(o) for o in page], limit, offset, total)


@bp.get("/wholesale/operators/<operatorId>")
def get_operator(operatorId):
    get_auth()
    op = db.operators.get(operatorId)
    if op is None:
        raise ApiError(ERR_OPERATOR_NOT_FOUND, 404, "Operator id does not exist")
    return success_object(op_view(op))


@bp.post("/wholesale/operators/<operatorId>/suspend")
def suspend_operator(operatorId):
    user_id, role = get_auth()
    require_role(role, ["WholesaleAdmin"])
    op = db.operators.get(operatorId)
    if op is None:
        raise ApiError(ERR_OPERATOR_NOT_FOUND, 404, "Operator id does not exist")
    if op["status"] != "ACTIVE":
        raise ApiError(ERR_OPERATOR_NOT_ACTIVE, 409, "Operator must be ACTIVE to suspend")
    op["status"] = "SUSPENDED"
    touch(op)
    return success_object(op_view(op))


@bp.post("/wholesale/operators/<operatorId>/reinstate")
def reinstate_operator(operatorId):
    user_id, role = get_auth()
    require_role(role, ["WholesaleAdmin"])
    op = db.operators.get(operatorId)
    if op is None:
        raise ApiError(ERR_OPERATOR_NOT_FOUND, 404, "Operator id does not exist")
    if op["status"] != "SUSPENDED":
        raise ApiError(ERR_OPERATOR_NOT_ACTIVE, 409, "Operator must be SUSPENDED to reinstate")
    op["status"] = "ACTIVE"
    touch(op)
    return success_object(op_view(op))
