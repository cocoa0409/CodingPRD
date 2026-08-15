"""MonetaryInstrumentSale endpoints."""
from flask import Blueprint, request

from db import (
    MONEY_ORDER_MAX_CENTS,
    RECORD_BAND_HIGH_CENTS,
    RECORD_BAND_LOW_CENTS,
    add_years,
    fmt_dt,
    now,
    now_iso,
    stamp_new,
    store,
    today,
    touch,
)
from errors import (
    ERR_AMOUNT_NOT_POSITIVE,
    ERR_BRANCH_INACTIVE,
    ERR_BRANCH_NOT_FOUND,
    ERR_CUSTOMER_NOT_ACTIVE,
    ERR_CUSTOMER_NOT_FOUND,
    ERR_INSTRUMENT_LIMIT_EXCEEDED,
    ERR_INSTRUMENT_RECORD_INCOMPLETE,
    ERR_INSTRUMENT_SALE_NOT_FOUND,
    ERR_INVALID_STATE_TRANSITION,
    ERR_OCCURRED_AT_IN_FUTURE,
    ERR_VOID_WINDOW_EXPIRED,
    ApiError,
)
from middleware import authenticate, body, f_datetime, f_enum, f_int, f_str, f_str_opt, sorted_page
from response import ok, ok_list
from serializers import serialize_instrument_sale
from services.audit import add_fx, main_event
from services.domain import compute_fee_cents, evaluate_structuring, recompute_aggregation

bp = Blueprint("instrument_sales", __name__)

ALL_ROLES = ["SystemAdmin", "BranchManager", "Teller", "ComplianceAnalyst", "BSAOfficer", "Examiner"]
INSTRUMENT_TYPES = ("CASHIERS_CHECK", "MONEY_ORDER", "TRAVELERS_CHECK")


def get_sale_or_404(sale_id):
    s = store.instrument_sales.get(sale_id)
    if s is None:
        raise ApiError(ERR_INSTRUMENT_SALE_NOT_FOUND, "Monetary instrument sale not found", 404)
    return s


@bp.post("/monetary-instrument-sales")
def create_instrument_sale():
    authenticate(["Teller"])
    b = body()
    customer_id = f_str(b, "customer_id")
    branch_id = f_str(b, "branch_id")
    instrument_type = f_enum(b, "instrument_type", INSTRUMENT_TYPES)
    amount_cents = f_int(b, "amount_cents")
    occurred_raw, occurred_dt = f_datetime(b, "occurred_at")
    purchaser_name = f_str_opt(b, "purchaser_name")
    purchaser_tin = f_str_opt(b, "purchaser_tin")
    purchaser_address = f_str_opt(b, "purchaser_address")
    purchaser_id_number = f_str_opt(b, "purchaser_id_number")
    # Body FK references resolve customer first, then branch.
    customer = store.customers.get(customer_id)
    if customer is None:
        raise ApiError(ERR_CUSTOMER_NOT_FOUND, "Customer not found", 404)
    branch = store.branches.get(branch_id)
    if branch is None:
        raise ApiError(ERR_BRANCH_NOT_FOUND, "Branch not found", 404)
    # Customer status is checked before the branch's.
    if customer["status"] != "ACTIVE":
        raise ApiError(ERR_CUSTOMER_NOT_ACTIVE, "Customer is not ACTIVE", 409)
    if branch["status"] != "ACTIVE":
        raise ApiError(ERR_BRANCH_INACTIVE, "Branch is not ACTIVE", 409)
    if amount_cents <= 0:
        raise ApiError(ERR_AMOUNT_NOT_POSITIVE, "amount_cents must be > 0", 422)
    if instrument_type == "MONEY_ORDER" and amount_cents > MONEY_ORDER_MAX_CENTS:
        raise ApiError(
            ERR_INSTRUMENT_LIMIT_EXCEEDED,
            "MONEY_ORDER amount exceeds 100000 cents",
            422,
        )
    record_required = RECORD_BAND_LOW_CENTS <= amount_cents <= RECORD_BAND_HIGH_CENTS
    if record_required and (
        purchaser_name is None
        or purchaser_tin is None
        or purchaser_address is None
        or purchaser_id_number is None
    ):
        raise ApiError(
            ERR_INSTRUMENT_RECORD_INCOMPLETE,
            "All four purchaser_* fields are mandatory for sales in the recordkeeping band",
            422,
        )
    if occurred_dt > now():
        raise ApiError(
            ERR_OCCURRED_AT_IN_FUTURE,
            "occurred_at is later than the current logical clock",
            422,
        )
    sale = {
        "customer_id": customer_id,
        "branch_id": branch_id,
        "instrument_type": instrument_type,
        "amount_cents": amount_cents,
        "occurred_at": occurred_raw,
        "business_date": occurred_dt.date().isoformat(),
        "purchaser_name": purchaser_name,
        "purchaser_tin": purchaser_tin,
        "purchaser_address": purchaser_address,
        "purchaser_id_number": purchaser_id_number,
        "record_required": record_required,
        "fee_cents": compute_fee_cents(amount_cents),
        "retention_until": fmt_dt(add_years(occurred_dt, 5)),
        "status": "RECORDED",
        "voided_at": None,
    }
    stamp_new(sale)
    store.instrument_sales[sale["id"]] = sale
    # Atomic cascade: aggregation, CTR reportability, structuring detection.
    recompute_aggregation(customer_id, sale["business_date"])
    evaluate_structuring(customer_id, sale["business_date"])
    main_event(
        "POST /monetary-instrument-sales", "MonetaryInstrumentSale", sale["id"],
        None, serialize_instrument_sale(sale),
    )
    return ok(serialize_instrument_sale(sale), status=201)


@bp.get("/monetary-instrument-sales")
def list_instrument_sales():
    authenticate(ALL_ROLES)
    items = list(store.instrument_sales.values())
    for param in ("customer_id", "branch_id", "business_date", "instrument_type", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [s for s in items if s[param] == value]
    page, limit, offset, total = sorted_page(items)
    return ok_list([serialize_instrument_sale(s) for s in page], limit, offset, total)


@bp.get("/monetary-instrument-sales/<sale_id>")
def get_instrument_sale(sale_id):
    authenticate(ALL_ROLES)
    return ok(serialize_instrument_sale(get_sale_or_404(sale_id)))


@bp.post("/monetary-instrument-sales/<sale_id>/void")
def void_instrument_sale(sale_id):
    authenticate(["Teller", "BranchManager"])
    b = body()
    void_reason = f_str_opt(b, "void_reason")
    sale = get_sale_or_404(sale_id)
    if sale["status"] != "RECORDED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION, "Sale is not in RECORDED status", 409
        )
    if sale["business_date"] != today().isoformat():
        raise ApiError(
            ERR_VOID_WINDOW_EXPIRED,
            "Void is permitted only on the sale's business date",
            409,
        )
    before = serialize_instrument_sale(sale)
    sale["status"] = "VOIDED"
    sale["voided_at"] = now_iso()
    touch(sale)
    if void_reason is not None:
        add_fx({"type": "void_reason", "value": void_reason})
    recompute_aggregation(sale["customer_id"], sale["business_date"])
    main_event(
        "POST /monetary-instrument-sales/{id}/void", "MonetaryInstrumentSale",
        sale["id"], before, serialize_instrument_sale(sale),
    )
    return ok(serialize_instrument_sale(sale))
