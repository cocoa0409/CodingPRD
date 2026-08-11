"""Court orders endpoints."""

from flask import Blueprint, request

from db import store
from errors import (
    ERR_ALREADY_TERMINAL,
    ERR_CLIENT_NOT_FOUND,
    ERR_COURT_ORDER_NOT_FOUND,
    ERR_INVALID_STATE,
    err,
)
from middleware import require_roles
from response import success_object, success_list
from serializers import serialize_court_order
from services.cascade import clock_now_iso, clock_date
from util import (
    new_id,
    parse_date,
    parse_pagination,
    require_body,
    get_string,
    get_int,
    get_enum,
    reject_unexpected,
)

bp = Blueprint("court_orders", __name__)

READ_ROLES = ("FiduciaryAdmin", "CaseManager", "FinancialOfficer", "ConservatorOfficer", "ComplianceAuditor")
ORDER_TYPES = ("RESTRICTED_WITHDRAWAL", "REPORT_EXTENSION", "BOND_RELIEF")


@bp.route("/court-orders", methods=["POST"])
def create_order():
    require_roles("FiduciaryAdmin")
    body = require_body()
    reject_unexpected(body, {
        "client_id", "order_type", "amount_limit_cents", "petitioned_date", "expiry_date",
    })
    client_id = get_string(body, "client_id")
    order_type = get_enum(body, "order_type", ORDER_TYPES)
    amount_limit = get_int(body, "amount_limit_cents", required=False, min_value=1, allow_null=True)
    petitioned = parse_date(get_string(body, "petitioned_date"), "petitioned_date")
    expiry = parse_date(get_string(body, "expiry_date"), "expiry_date")

    if client_id not in store.clients:
        raise err(ERR_CLIENT_NOT_FOUND, 404, "client not found")

    now = clock_now_iso()
    oid = new_id()
    o = {
        "id": oid,
        "client_id": client_id,
        "order_type": order_type,
        "amount_limit_cents": amount_limit,
        "petitioned_date": petitioned,
        "granted_date": None,
        "expiry_date": expiry,
        "executed_disbursement_id": None,
        "status": "PETITIONED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.court_orders[oid] = o
    return success_object(serialize_court_order(o), status=201)


@bp.route("/court-orders", methods=["GET"])
def list_orders():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination()
    client_id = request.args.get("client_id")
    order_type = request.args.get("order_type")
    status = request.args.get("status")
    executed = request.args.get("executed_disbursement_id")
    items = list(store.court_orders.values())
    if client_id is not None:
        items = [o for o in items if o["client_id"] == client_id]
    if order_type is not None:
        items = [o for o in items if o["order_type"] == order_type]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    if executed is not None:
        items = [o for o in items if o.get("executed_disbursement_id") == executed]
    items.sort(key=lambda o: o["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_court_order(o) for o in page], limit, offset, total)


@bp.route("/court-orders/<oid>", methods=["GET"])
def get_order(oid):
    require_roles(*READ_ROLES)
    o = store.court_orders.get(oid)
    if not o:
        raise err(ERR_COURT_ORDER_NOT_FOUND, 404, "court order not found")
    return success_object(serialize_court_order(o))


@bp.route("/court-orders/<oid>/grant", methods=["POST"])
def grant_order(oid):
    require_roles("FiduciaryAdmin")
    o = store.court_orders.get(oid)
    if not o:
        raise err(ERR_COURT_ORDER_NOT_FOUND, 404, "court order not found")
    if o["status"] in ("EXECUTED", "EXPIRED"):
        raise err(ERR_ALREADY_TERMINAL, 409, "Court order is terminal")
    if o["status"] != "PETITIONED":
        raise err(ERR_INVALID_STATE, 409, "Only PETITIONED -> GRANTED")
    now_date = clock_date()
    now_iso = clock_now_iso()
    o["status"] = "GRANTED"
    o["granted_date"] = now_date
    o["updated_at"] = now_iso
    o["version"] += 1
    return success_object(serialize_court_order(o))
