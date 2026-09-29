"""Logical clock, product eligibility matrix and the LLPA grid."""

from flask import Blueprint

import validate as v
from auth import endpoint, user_id
from envelope import created, ok, ok_list
from errors import ApiError
from helpers import need_product
from store import base_record, db, public, public_list, touch

catalog_bp = Blueprint("catalog", __name__)

COMMITMENT_TYPES = ("MANDATORY", "BEST_EFFORTS")
OCCUPANCIES = ("PRIMARY", "SECOND_HOME", "INVESTMENT")
ROW_STATUSES = ("ACTIVE", "RETIRED")


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------

@catalog_bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint("PlatformAdmin")
def set_clock():
    body = v.body()
    instant = v.req_instant(body, "current_utc", required=True)
    db.clock = instant
    return ok({})


# --------------------------------------------------------------------------
# products
# --------------------------------------------------------------------------

@catalog_bp.route("/products", methods=["POST"])
@endpoint("PlatformAdmin")
def create_product():
    body = v.body()
    product_code = v.req_str(body, "product_code", min_len=3, max_len=32)
    if product_code != product_code.upper():
        v.bad("Field 'product_code' must be uppercase.")
    base_price_pct = v.req_num(body, "base_price_pct", minimum="90.000",
                               maximum="110.000")
    min_fico = v.req_int(body, "min_fico", minimum=300, maximum=850)
    max_ltv_pct = v.req_num(body, "max_ltv_pct", minimum="1.0", maximum="100.0")
    max_loan_amount_cents = v.req_int(body, "max_loan_amount_cents", minimum=1)
    allowed_commitment_types = v.req_enum_array(body, "allowed_commitment_types",
                                                COMMITMENT_TYPES)
    allowed_occupancies = v.req_enum_array(body, "allowed_occupancies", OCCUPANCIES)
    srp_pct = v.req_num(body, "srp_pct", minimum="0.000", maximum="5.000")
    description = v.req_str(body, "description", max_len=500, required=False)
    status = v.req_enum(body, "status", ROW_STATUSES, required=False,
                        default="ACTIVE")

    for existing in db.products.values():
        if existing["product_code"] == product_code:
            raise ApiError("ERR_DUPLICATE_PRODUCT_CODE")

    record = base_record()
    record.update({
        "product_code": product_code,
        "description": description,
        "base_price_pct": base_price_pct,
        "min_fico": min_fico,
        "max_ltv_pct": max_ltv_pct,
        "max_loan_amount_cents": max_loan_amount_cents,
        "allowed_commitment_types": allowed_commitment_types,
        "allowed_occupancies": allowed_occupancies,
        "srp_pct": srp_pct,
        "status": status,
    })
    db.products[record["id"]] = record
    return created(public(record))


@catalog_bp.route("/products/<pid>", methods=["GET"])
@endpoint("PlatformAdmin", "CounterpartyAnalyst", "LockDeskTrader",
          "PurchaseReviewer", "SellerUser")
def read_product(pid):
    product = need_product(pid)
    return ok(public(product))


# --------------------------------------------------------------------------
# pricing adjustments
# --------------------------------------------------------------------------

@catalog_bp.route("/products/<pid>/pricing-adjustments", methods=["POST"])
@endpoint("PlatformAdmin")
def create_adjustment(pid):
    product = need_product(pid)
    body = v.body()
    adjustment_code = v.req_str(body, "adjustment_code", min_len=3, max_len=48)
    fico_min = v.req_int(body, "fico_min", minimum=300, maximum=850)
    fico_max = v.req_int(body, "fico_max", minimum=300, maximum=850)
    if fico_max < fico_min:
        v.bad("Field 'fico_max' must not be below 'fico_min'.")
    ltv_min_pct = v.req_num(body, "ltv_min_pct", minimum="0.0", maximum="100.0")
    ltv_max_pct = v.req_num(body, "ltv_max_pct", minimum="0.0", maximum="100.0")
    if ltv_max_pct <= ltv_min_pct:
        v.bad("Field 'ltv_max_pct' must exceed 'ltv_min_pct'.")
    price_adjustment_bps = v.req_int(body, "price_adjustment_bps", minimum=-300,
                                     maximum=100)
    status = v.req_enum(body, "status", ROW_STATUSES, required=False,
                        default="ACTIVE")

    for existing in db.adjustments.values():
        if (existing["product_id"] == product["id"]
                and existing["adjustment_code"] == adjustment_code):
            raise ApiError("ERR_DUPLICATE_ADJUSTMENT_CODE")

    record = base_record()
    record.update({
        "product_id": product["id"],
        "adjustment_code": adjustment_code,
        "fico_min": fico_min,
        "fico_max": fico_max,
        "ltv_min_pct": ltv_min_pct,
        "ltv_max_pct": ltv_max_pct,
        "price_adjustment_bps": price_adjustment_bps,
        "status": status,
    })
    db.adjustments[record["id"]] = record
    return created(public(record))


@catalog_bp.route("/products/<pid>/pricing-adjustments", methods=["GET"])
@endpoint("PlatformAdmin", "LockDeskTrader", "CounterpartyAnalyst")
def list_adjustments(pid):
    product = need_product(pid)
    limit, offset = v.pagination()
    status = v.arg("status")
    rows = [r for r in db.adjustments.values() if r["product_id"] == product["id"]]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: r["_seq"])
    page, total = v.paginate(rows, limit, offset)
    return ok_list(public_list(page), limit, offset, total)
