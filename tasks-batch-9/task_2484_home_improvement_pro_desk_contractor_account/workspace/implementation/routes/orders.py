"""Pro orders, order lines, sourcing reservations, invoicing and settlement."""
from flask import Blueprint, request

import clock
import db
import response
import validate as v
from errors import ApiError
from middleware import auth, check_scope, scope_list
from services import credit as credit_svc
from services import pricing as pricing_svc
from services import rebate as rebate_svc
from services import sourcing as sourcing_svc
from services import stock as stock_svc
from services import tier as tier_svc

bp = Blueprint("orders", __name__)

PAYMENT_METHODS = ("CREDIT_LINE", "CARD")
DELIVERY_MODES = ("WILL_CALL", "DELIVERY")

ORDER_READ_ROLES = ("ContractorAdmin", "ProDeskAssociate", "CreditManager", "StoreOperations")
LINE_READ_ROLES = ("ContractorAdmin", "ProDeskAssociate", "StoreOperations")
ORDER_LINE_READ_ROLES = ("ContractorAdmin", "ProDeskAssociate", "StoreOperations", "CreditManager")
RESERVATION_READ_ROLES = ("StoreOperations", "ProDeskAssociate", "ContractorAdmin")


def _lines_of(order):
    return db.where("order_lines", pro_order_id=order["id"])


def _live_reservations(order):
    return [r for r in db.where("reservations", pro_order_id=order["id"])
            if r["status"] in ("HELD", "ALLOCATED")]


# ---------------------------------------------------------------- pro orders
@bp.post("/pro/pro-orders")
def create_order():
    user_id, role = auth("ContractorAdmin")
    data = v.body()
    account = v.resolve_fk(data, "pro_account_id", "pro_accounts", "ERR_PRO_ACCOUNT_NOT_FOUND")
    if account is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field 'pro_account_id' is required.")
    store = v.resolve_fk(data, "fulfillment_store_id", "stores", "ERR_STORE_NOT_FOUND")
    if store is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field 'fulfillment_store_id' is required.")
    quote = v.resolve_fk(data, "job_quote_id", "job_quotes", "ERR_JOB_QUOTE_NOT_FOUND")
    payment_method = v.req_enum(data, "payment_method", PAYMENT_METHODS)
    delivery_mode = v.req_enum(data, "delivery_mode", DELIVERY_MODES)
    po_number = v.opt_str(data, "po_number")
    job_name = v.opt_str(data, "job_name")
    lift_gate_required = v.opt_bool(data, "lift_gate_required", False)
    job_lot_required = v.opt_bool(data, "job_lot_required", False)
    resale_purchase = v.opt_bool(data, "resale_purchase", False)
    check_scope(role, user_id, account["id"])
    if quote is not None and quote["pro_account_id"] != account["id"]:
        raise ApiError("ERR_QUOTE_ACCOUNT_MISMATCH", 422)
    rec = db.new_record("pro_orders", {
        "pro_account_id": account["id"],
        "fulfillment_store_id": store["id"],
        "job_quote_id": quote["id"] if quote is not None else None,
        "po_number": po_number,
        "job_name": job_name,
        "payment_method": payment_method,
        "delivery_mode": delivery_mode,
        "lift_gate_required": lift_gate_required,
        "job_lot_required": job_lot_required,
        "resale_purchase": resale_purchase,
        "fulfillment_status": "DRAFT",
        "credit_status": "UNBILLED",
        "tier_code_applied": None,
        "list_subtotal_cents": None,
        "subtotal_cents": None,
        "discount_cents": None,
        "freight_surcharge_cents": None,
        "lift_gate_fee_cents": None,
        "tax_cents": None,
        "total_cents": None,
        "tax_exempt_applied": False,
        "priced_at": None,
        "invoiced_at": None,
        "fulfilled_at": None,
        "credited_refund_cents": 0,
        "credited_gross_refund_cents": 0,
        "net_volume_cents": None,
        "cancel_reason_code": None,
    })
    return response.obj(db.public(rec), 201)


@bp.get("/pro/pro-orders/<pro_order_id>")
def get_order(pro_order_id):
    user_id, role = auth(*ORDER_READ_ROLES)
    order = db.require("pro_orders", pro_order_id)
    check_scope(role, user_id, order["pro_account_id"])
    return response.obj(db.public(order))


@bp.get("/pro/pro-orders")
def list_orders():
    user_id, role = auth(*ORDER_READ_ROLES)
    records = db.all_of("pro_orders")
    for key in ("pro_account_id", "job_quote_id", "fulfillment_store_id",
                "fulfillment_status", "credit_status"):
        value = request.args.get(key)
        if value is not None:
            records = [r for r in records if r[key] == value]
    records = scope_list(role, user_id, records, lambda r: r["pro_account_id"])
    items, meta = v.paginate(records)
    return response.array(items, 200, meta)


# ---------------------------------------------------------------- order lines
@bp.post("/pro/pro-orders/<pro_order_id>/lines")
def create_order_line(pro_order_id):
    user_id, role = auth("ContractorAdmin")
    order = db.require("pro_orders", pro_order_id)
    data = v.body()
    sku = v.req_str(data, "sku")
    qty_units = v.req_int(data, "qty_units", minimum=1)
    check_scope(role, user_id, order["pro_account_id"])
    if order["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409)
    if stock_svc.find_stock(order["fulfillment_store_id"], sku) is None:
        raise ApiError("ERR_SKU_NOT_STOCKED", 422)
    for existing in _lines_of(order):
        if existing["sku"] == sku:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "An order may carry only one line per SKU.")
    rec = db.new_record("order_lines", {
        "pro_order_id": order["id"],
        "sku": sku,
        "qty_units": qty_units,
        "price_source": None,
        "list_unit_price_cents": None,
        "effective_unit_price_cents": None,
        "line_subtotal_cents": None,
        "fulfilled_units": 0,
        "returned_units": 0,
    })
    return response.obj(db.public(rec), 201)


@bp.get("/pro/pro-orders/<pro_order_id>/lines")
def list_lines_of_order(pro_order_id):
    user_id, role = auth(*LINE_READ_ROLES)
    order = db.require("pro_orders", pro_order_id)
    check_scope(role, user_id, order["pro_account_id"])
    items, meta = v.paginate(_lines_of(order))
    return response.array(items, 200, meta)


@bp.get("/pro/order-lines/<order_line_id>")
def get_order_line(order_line_id):
    user_id, role = auth(*ORDER_LINE_READ_ROLES)
    line = db.require("order_lines", order_line_id)
    order = db.get("pro_orders", line["pro_order_id"])
    check_scope(role, user_id, order["pro_account_id"] if order else None)
    return response.obj(db.public(line))


@bp.get("/pro/order-lines")
def list_order_lines():
    user_id, role = auth(*ORDER_LINE_READ_ROLES)
    records = db.all_of("order_lines")
    for key in ("pro_order_id", "sku"):
        value = request.args.get(key)
        if value is not None:
            records = [r for r in records if r[key] == value]
    if role == "ContractorAdmin":
        def owner(line):
            order = db.get("pro_orders", line["pro_order_id"])
            return order["pro_account_id"] if order else None
        records = scope_list(role, user_id, records, owner)
    items, meta = v.paginate(records)
    return response.array(items, 200, meta)


# ------------------------------------------------------------- pricing/submit
@bp.get("/pro/pro-orders/<pro_order_id>/pricing-preview")
def pricing_preview(pro_order_id):
    user_id, role = auth("ContractorAdmin", "ProDeskAssociate")
    order = db.require("pro_orders", pro_order_id)
    check_scope(role, user_id, order["pro_account_id"])
    if not _lines_of(order):
        raise ApiError("ERR_NO_ORDER_LINES", 422)
    result = pricing_svc.compute(order, persist=False)
    return response.obj(result)


@bp.post("/pro/pro-orders/<pro_order_id>/submit")
def submit_order(pro_order_id):
    user_id, role = auth("ContractorAdmin")
    order = db.require("pro_orders", pro_order_id)
    check_scope(role, user_id, order["pro_account_id"])
    if order["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409)
    account = db.require("pro_accounts", order["pro_account_id"])
    if account["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_ON_HOLD", 409)

    credit_line = None
    if order["payment_method"] == "CREDIT_LINE":
        credit_line = credit_svc.credit_line_of(account["id"])
        if credit_line is None:
            raise ApiError("ERR_CREDIT_LINE_NOT_FOUND", 404)
        if credit_line["status"] != "ACTIVE":
            raise ApiError("ERR_CREDIT_LINE_FROZEN", 409)

    if not _lines_of(order):
        raise ApiError("ERR_NO_ORDER_LINES", 422)

    quote = db.get("job_quotes", order["job_quote_id"]) if order.get("job_quote_id") else None
    if quote is not None and quote["status"] != "ACCEPTED":
        raise ApiError("ERR_QUOTE_NOT_ACCEPTED", 422)

    if account["po_required"] and not (order.get("po_number") or "").strip():
        raise ApiError("ERR_PO_NUMBER_REQUIRED", 422)
    if account["job_name_required"] and not (order.get("job_name") or "").strip():
        raise ApiError("ERR_JOB_NAME_REQUIRED", 422)

    store = db.require("stores", order["fulfillment_store_id"])
    if order.get("resale_purchase"):
        if store["state_code"] not in tier_svc.tax_exempt_state_codes(account):
            raise ApiError("ERR_NO_VALID_TAX_CERTIFICATE", 422)

    if quote is not None:
        now = clock.get_now()
        term_start = quote.get("_term_start")
        term_end = quote.get("_term_end")
        if term_start is None or term_end is None or not (term_start <= now <= term_end):
            raise ApiError("ERR_QUOTE_TERM_EXPIRED", 422)

    # Price without persisting so the credit gate can reject atomically.
    preview = pricing_svc.compute(order, persist=False)
    if credit_line is not None and preview["total_cents"] > credit_line["available_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 402)

    pricing_svc.compute(order, persist=True)
    order["priced_at"] = clock.now_iso()
    order["net_volume_cents"] = (order["subtotal_cents"] or 0) - \
        (order["credited_gross_refund_cents"] or 0)
    order["fulfillment_status"] = "SUBMITTED"
    order["credit_status"] = "AUTHORIZED"
    db.touch(order)
    if credit_line is not None:
        credit_svc.recompute_exposure(credit_line)
    return response.obj(db.public(order))


# ---------------------------------------------------------------- reservations
@bp.post("/pro/pro-orders/<pro_order_id>/reserve")
def reserve_order(pro_order_id):
    auth("ProDeskAssociate")
    order = db.require("pro_orders", pro_order_id)
    if order["fulfillment_status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409)
    lines = _lines_of(order)
    if not lines:
        raise ApiError("ERR_NO_ORDER_LINES", 422)
    planned = sourcing_svc.plan(order, lines)
    created = sourcing_svc.commit(order, planned)
    order["fulfillment_status"] = "RESERVED"
    db.touch(order)
    return response.array([db.public(r) for r in created], 201)


@bp.get("/pro/reservations/<reservation_id>")
def get_reservation(reservation_id):
    user_id, role = auth(*RESERVATION_READ_ROLES)
    res = db.require("reservations", reservation_id)
    order = db.get("pro_orders", res["pro_order_id"])
    check_scope(role, user_id, order["pro_account_id"] if order else None)
    return response.obj(db.public(res))


@bp.get("/pro/reservations")
def list_reservations():
    user_id, role = auth(*RESERVATION_READ_ROLES)
    records = db.all_of("reservations")
    for key in ("pro_order_id", "order_line_id", "store_id", "status"):
        value = request.args.get(key)
        if value is not None:
            records = [r for r in records if r[key] == value]
    if role == "ContractorAdmin":
        def owner(res):
            order = db.get("pro_orders", res["pro_order_id"])
            return order["pro_account_id"] if order else None
        records = scope_list(role, user_id, records, owner)
    items, meta = v.paginate(records)
    return response.array(items, 200, meta)


@bp.post("/pro/reservations/<reservation_id>/allocate")
def allocate_reservation(reservation_id):
    auth("StoreOperations")
    res = db.require("reservations", reservation_id)
    order = db.require("pro_orders", res["pro_order_id"])
    if res["status"] != "HELD":
        raise ApiError("ERR_INVALID_STATE", 409)
    if order["fulfillment_status"] != "RESERVED":
        raise ApiError("ERR_INVALID_STATE", 409)
    res["status"] = "ALLOCATED"
    db.touch(res)
    return response.obj(db.public(res))


@bp.post("/pro/reservations/<reservation_id>/release")
def release_reservation(reservation_id):
    auth("StoreOperations")
    res = db.require("reservations", reservation_id)
    order = db.require("pro_orders", res["pro_order_id"])
    data = v.body()
    reason_code = v.req_str(data, "reason_code")
    if res["status"] == "HELD":
        allowed = ("SUBMITTED", "RESERVED", "STAGED")
    elif res["status"] == "ALLOCATED":
        allowed = ("RESERVED", "STAGED")
    else:
        raise ApiError("ERR_INVALID_STATE", 409)
    if order["fulfillment_status"] not in allowed:
        raise ApiError("ERR_INVALID_STATE", 409)
    sourcing_svc.release(res, reason_code)
    sourcing_svc.revert_order_if_all_released(order)
    return response.obj(db.public(res))


# ------------------------------------------------------------ cancel / credit
@bp.post("/pro/pro-orders/<pro_order_id>/cancel")
def cancel_order(pro_order_id):
    user_id, role = auth("ContractorAdmin")
    order = db.require("pro_orders", pro_order_id)
    data = v.body()
    reason_code = v.req_str(data, "reason_code")
    check_scope(role, user_id, order["pro_account_id"])
    if order["fulfillment_status"] not in ("DRAFT", "SUBMITTED", "RESERVED", "STAGED"):
        raise ApiError("ERR_INVALID_STATE", 409)

    order["cancel_reason_code"] = reason_code
    order["fulfillment_status"] = "CANCELLED"
    voided = False
    if order["credit_status"] == "AUTHORIZED":
        order["credit_status"] = "VOIDED"
        voided = True
    db.touch(order)

    for res in _live_reservations(order):
        sourcing_svc.release(res, "ORDER_CANCELLED")

    for staging in db.where("will_call_stagings", pro_order_id=order["id"]):
        if staging["status"] in ("SCHEDULED", "STAGED"):
            staging["status"] = "EXPIRED"
            db.touch(staging)

    for appt in db.where("delivery_appointments", pro_order_id=order["id"]):
        if appt["status"] in ("SCHEDULED", "CONFIRMED"):
            appt["status"] = "CANCELLED"
            appt["cancel_reason_code"] = "ORDER_CANCELLED"
            db.touch(appt)

    if voided:
        credit_svc.recompute_exposure(credit_svc.credit_line_of(order["pro_account_id"]))
    return response.obj(db.public(order))


@bp.post("/pro/pro-orders/<pro_order_id>/invoice")
def invoice_order(pro_order_id):
    auth("CreditManager")
    order = db.require("pro_orders", pro_order_id)
    if order["credit_status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_STATE", 409)
    if order["fulfillment_status"] != "FULFILLED":
        raise ApiError("ERR_ORDER_NOT_FULFILLED", 409)
    if order["payment_method"] != "CREDIT_LINE":
        raise ApiError("ERR_INVALID_STATE", 409)

    account = db.require("pro_accounts", order["pro_account_id"])
    order["credit_status"] = "INVOICED"
    order["invoiced_at"] = clock.now_iso()
    order["_invoiced_at"] = clock.get_now()
    order["net_volume_cents"] = (order["subtotal_cents"] or 0) - \
        (order["credited_gross_refund_cents"] or 0)
    db.touch(order)

    credit_line = credit_svc.credit_line_of(account["id"])
    if credit_line is not None:
        credit_svc.recompute_exposure(credit_line)
        credit_svc.utilization_review(credit_line)

    tier_svc.tier_review(account)
    rebate_svc.book_accrual(account, order)
    return response.obj(db.public(order))


@bp.post("/pro/pro-orders/<pro_order_id>/pay")
def pay_order(pro_order_id):
    auth("CreditManager")
    order = db.require("pro_orders", pro_order_id)
    data = v.body()
    amount_cents = v.req_int(data, "amount_cents")
    if order["credit_status"] != "INVOICED":
        raise ApiError("ERR_INVALID_STATE", 409)
    owed = (order["total_cents"] or 0) - (order["credited_refund_cents"] or 0)
    if amount_cents != owed:
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH", 422)
    order["credit_status"] = "PAID"
    db.touch(order)
    credit_svc.recompute_exposure(credit_svc.credit_line_of(order["pro_account_id"]))
    return response.obj(db.public(order))
