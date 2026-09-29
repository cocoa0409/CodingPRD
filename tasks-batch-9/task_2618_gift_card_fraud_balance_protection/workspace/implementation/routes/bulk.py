"""Bulk purchase orders: tiered pricing, identity capture and decisions
(PRD 3.3)."""
from flask import Blueprint

import db as dbm
import response
import validate
from db import db
from errors import fail
from middleware import scope_body_store
from routes.common import (READ_ROLES, authenticate, filter_by, listing_response,
                           require_bulk_order, require_store, scope_record)
from services import bulk as bulk_svc
from services.bulk import BULK_STATES, DECISIONS, ID_TYPES, PAYMENT_METHODS

bp = Blueprint("bulk", __name__)


@bp.post("/bulk-purchase-orders")
def create_order():
    caller = authenticate(["PosAssociate", "StoreManager"])
    scope_body_store(caller)
    body = validate.body()
    store_id = validate.string(body, "store_id", min_len=1)
    quantity = validate.integer(body, "card_quantity", minimum=1)
    each = validate.integer(body, "face_value_cents_each", minimum=1)
    if each < 100 or each > 500000:
        fail("ERR_INVALID_REQUEST",
             "face_value_cents_each must be between 100 and 500000.")
    purchaser_name = validate.string(body, "purchaser_name", min_len=1, max_len=120)
    payment_method = validate.enum(body, "payment_method", PAYMENT_METHODS)
    require_store(store_id)
    policy = dbm.policy()
    if quantity > policy["bulk_quantity_limit"]:
        fail("ERR_BULK_QUANTITY_LIMIT_EXCEEDED")

    subtotal, bps, fee, total = bulk_svc.price(quantity, each)
    state = "PENDING_IDENTITY" if total >= policy["bulk_identity_threshold_cents"] \
        else "IDENTITY_VERIFIED"
    rec = dbm.record({
        "store_id": store_id,
        "card_quantity": quantity,
        "face_value_cents_each": each,
        "purchaser_name": purchaser_name,
        "payment_method": payment_method,
        "face_value_subtotal_cents": subtotal,
        "fee_rate_bps": bps,
        "activation_fee_cents": fee,
        "total_cents": total,
        "state": state,
        "identity_id_type": None,
        "identity_id_number_hash": None,
        "identity_id_expiry_date": None,
        "info_request_count": 0,
        "decided_by_user_id": None,
        "decision_note": None,
    })
    db.bulk_orders[rec["id"]] = rec
    return response.created(rec)


@bp.get("/bulk-purchase-orders")
def list_orders():
    authenticate(READ_ROLES)
    store_id = validate.query_str("store_id")
    state = validate.query_enum("state", BULK_STATES)
    rows = list(db.bulk_orders.values())
    rows = filter_by(rows, "store_id", store_id)
    rows = filter_by(rows, "state", state)
    return listing_response(rows)


@bp.get("/bulk-purchase-orders/<order_id>")
def get_order(order_id):
    caller = authenticate(READ_ROLES)
    scope_record(caller, db.bulk_orders.get(order_id))
    return response.ok(require_bulk_order(order_id))


@bp.post("/bulk-purchase-orders/<order_id>/identity-verification")
def verify_identity(order_id):
    caller = authenticate(["PosAssociate", "StoreManager"])
    scope_record(caller, db.bulk_orders.get(order_id))
    body = validate.body()
    id_type = validate.enum(body, "id_type", ID_TYPES)
    id_number_hash = validate.string(body, "id_number_hash", min_len=1)
    # PRD 3.3 requires `id_expiry_date` ("the document's expiry") and persists it
    # verbatim as `identity_id_expiry_date`.  It is not one of the logical-clock
    # instants enumerated in PRD 2.4, and the PRD declares no format for it, so it
    # is validated only as a required non-null string.
    id_expiry_date = validate.string(body, "id_expiry_date", min_len=1)
    order = require_bulk_order(order_id)
    if order["state"] != "PENDING_IDENTITY":
        fail("ERR_INVALID_BULK_ORDER_STATE")
    order["identity_id_type"] = id_type
    order["identity_id_number_hash"] = id_number_hash
    order["identity_id_expiry_date"] = id_expiry_date
    order["state"] = "IDENTITY_VERIFIED"
    dbm.touch(order)
    return response.ok(order)


@bp.post("/bulk-purchase-orders/<order_id>/decide")
def decide_order(order_id):
    caller = authenticate(["StoreManager", "RiskManager"])
    scope_record(caller, db.bulk_orders.get(order_id))
    body = validate.body()
    decision = validate.enum(body, "decision", DECISIONS)
    note = validate.string(body, "decision_note", required=False, min_len=None)
    order = require_bulk_order(order_id)
    policy = dbm.policy()

    if decision == "REQUEST_INFO":
        if order["state"] != "IDENTITY_VERIFIED":
            fail("ERR_INVALID_BULK_ORDER_STATE")
    elif order["state"] not in ("PENDING_IDENTITY", "IDENTITY_VERIFIED"):
        fail("ERR_INVALID_BULK_ORDER_STATE")

    if decision == "APPROVE":
        store = db.stores.get(order["store_id"])
        if store is not None and store["floor_posture"] == "SUSPENDED":
            fail("ERR_STORE_FLOOR_SUSPENDED")
        if order["total_cents"] >= policy["bulk_identity_threshold_cents"] \
                and not order.get("identity_id_number_hash"):
            fail("ERR_IDENTITY_VERIFICATION_REQUIRED")
        order["state"] = "APPROVED"
        order["decided_by_user_id"] = caller.user_id
    elif decision == "DECLINE":
        order["state"] = "DECLINED"
        order["decided_by_user_id"] = caller.user_id
    else:
        order["state"] = "PENDING_IDENTITY"
        order["identity_id_type"] = None
        order["identity_id_number_hash"] = None
        order["identity_id_expiry_date"] = None
        order["info_request_count"] = order.get("info_request_count", 0) + 1

    order["decision_note"] = note
    dbm.touch(order)
    return response.ok(order)
