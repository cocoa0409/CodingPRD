"""Promotions, manufacturer rebate claims, and equipment trade-ins
(PRD sections 3.4 and 3.6)."""

from flask import Blueprint, request

import envelope
from auth import auth_and_roles, pm_owns_or_403
from calc import (
    appraise_trade_in,
    compute_rebate_amount,
    lazy_expire_promotion,
)
from db import STORES, now
from errors import ApiError
from util import (
    base_record,
    body,
    fk_exists,
    fmt_ts,
    get_or_404,
    paginate,
    pub,
    sorted_default,
    touch,
    v_bool,
    v_dt,
    v_enum,
    v_int,
    v_list,
    v_num,
    v_str,
)

bp = Blueprint("commercial", __name__)

PROMO_KINDS = {"BUNDLE_DISCOUNT", "MANUFACTURER_REBATE"}
PROMO_READ_ROLES = [
    "DistributionAdmin",
    "SalesRep",
    "PracticeManager",
    "ServiceDispatcher",
    "ManufacturerAgent",
]
CLAIM_READ_ROLES = ["DistributionAdmin", "PracticeManager", "ManufacturerAgent"]
TRADE_IN_ROLES = ["DistributionAdmin", "SalesRep", "PracticeManager"]
TRADE_IN_WRITE_ROLES = ["PracticeManager", "SalesRep"]
CONDITIONS = {"WORKING", "NEEDS_REPAIR", "SCRAP"}
VALUATION_METHODS = {"MARKET_VALUE", "SCRAP_VALUE"}
DISPOSAL_METHODS = {"RECYCLE", "RESALE_PARTS", "HAZMAT"}


# ---------------------------------------------------------------------------
# Promotions
# ---------------------------------------------------------------------------


def _id_list(data, field):
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"{field} must be an array of strings")
    return list(value)


@bp.post("/promotions")
def create_promotion():
    auth_and_roles(["DistributionAdmin"])
    data = body()
    name = v_str(data, "name")
    promo_kind = v_enum(data, "promo_kind", PROMO_KINDS)
    required_product_ids = _id_list(data, "required_product_ids")
    eligible_product_ids = _id_list(data, "eligible_product_ids")
    discount_pct = v_num(data, "discount_pct", required=False, default=None)
    max_discount = v_int(data, "max_discount_cents", required=False, default=None, min_val=0)
    rebate_per_unit = v_int(
        data, "rebate_per_unit_cents", required=False, default=None, min_val=0
    )
    stacking = v_bool(data, "stacking_allowed", required=False, default=False)
    fund_total = v_int(data, "fund_total_cents", required=False, default=None, min_val=0)
    start_raw, start_dt = v_dt(data, "start_date")
    end_raw, end_dt = v_dt(data, "end_date")

    if promo_kind == "MANUFACTURER_REBATE" and fund_total is None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "fund_total_cents is required for MANUFACTURER_REBATE promotions",
        )

    record = base_record()
    record.update(
        {
            "name": name,
            "promo_kind": promo_kind,
            "required_product_ids": required_product_ids,
            "eligible_product_ids": eligible_product_ids,
            "discount_pct": discount_pct,
            "max_discount_cents": max_discount,
            "rebate_per_unit_cents": rebate_per_unit,
            "stacking_allowed": stacking,
            "fund_total_cents": fund_total,
            "fund_remaining_cents": fund_total if promo_kind == "MANUFACTURER_REBATE" else None,
            "start_date": start_raw,
            "end_date": end_raw,
            "status": "ACTIVE",
            "_start_dt": start_dt,
            "_end_dt": end_dt,
        }
    )
    STORES["promotions"][record["id"]] = record
    return envelope.success(pub(record), "object", 201)


@bp.get("/promotions/<rid>")
def get_promotion(rid):
    auth_and_roles(PROMO_READ_ROLES)
    promo = get_or_404("promotions", rid)
    lazy_expire_promotion(promo)
    return envelope.success(pub(promo))


# ---------------------------------------------------------------------------
# Rebate claims
# ---------------------------------------------------------------------------


@bp.post("/rebate-claims")
def create_rebate_claim():
    uid, role = auth_and_roles(["PracticeManager"])
    data = body()
    pid = data.get("practice_id")
    if pid is not None:
        pm_owns_or_403(role, uid, pid)

    fk_exists(data, "practice_id", "practices")
    fk_exists(data, "order_id", "orders")
    fk_exists(data, "promotion_id", "promotions")

    practice_id = v_str(data, "practice_id")
    order_id = v_str(data, "order_id")
    promotion_id = v_str(data, "promotion_id")

    practice = STORES["practices"][practice_id]
    order = STORES["orders"][order_id]
    promo = STORES["promotions"][promotion_id]

    # Creation checks in order: kind applicability, practice match, duplicates.
    if promo["promo_kind"] != "MANUFACTURER_REBATE":
        raise ApiError(
            "ERR_PROMOTION_NOT_APPLICABLE",
            422,
            "Claims accept only MANUFACTURER_REBATE promotions",
        )
    if order["practice_id"] != practice_id:
        raise ApiError(
            "ERR_PRACTICE_MISMATCH",
            422,
            "Referenced order belongs to a different practice",
        )
    for other in STORES["rebate_claims"].values():
        if (
            other["order_id"] == order_id
            and other["promotion_id"] == promotion_id
            and other["status"] != "DENIED"
        ):
            raise ApiError(
                "ERR_DUPLICATE_CLAIM",
                409,
                "A non-DENIED claim already exists for this order and promotion",
            )

    amount = compute_rebate_amount(practice, order, promo)
    record = base_record()
    record.update(
        {
            "practice_id": practice_id,
            "order_id": order_id,
            "promotion_id": promotion_id,
            "claim_amount_cents": amount,
            "status": "DRAFT",
            "submitted_at": None,
            "paid_at": None,
            "denial_reason": None,
            "_submitted_dt": None,
            "_paid_dt": None,
        }
    )
    STORES["rebate_claims"][record["id"]] = record
    return envelope.success(pub(record), "object", 201)


@bp.get("/rebate-claims/<rid>")
def get_rebate_claim(rid):
    uid, role = auth_and_roles(CLAIM_READ_ROLES)
    claim = get_or_404("rebate_claims", rid)
    pm_owns_or_403(role, uid, claim["practice_id"])
    return envelope.success(pub(claim))


@bp.get("/rebate-claims")
def list_rebate_claims():
    uid, role = auth_and_roles(CLAIM_READ_ROLES)
    records = list(STORES["rebate_claims"].values())
    if role == "PracticeManager":
        records = [r for r in records if r["practice_id"] == uid]
    for field in ("practice_id", "order_id", "promotion_id"):
        value = request.args.get(field)
        if value is not None:
            records = [r for r in records if r.get(field) == value]
    records = sorted_default(records)
    page, pagination = paginate(records)
    return envelope.success([pub(r) for r in page], "array", 200, pagination)


@bp.post("/rebate-claims/<rid>/submit")
def submit_rebate_claim(rid):
    uid, role = auth_and_roles(["PracticeManager"])
    claim = get_or_404("rebate_claims", rid)
    pm_owns_or_403(role, uid, claim["practice_id"])
    if claim["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a DRAFT claim can be submitted")

    # Domain checks in the fixed order of PRD section 3.4.
    promo = STORES["promotions"][claim["promotion_id"]]
    lazy_expire_promotion(promo)
    t = now()
    if promo["status"] != "ACTIVE" or not (promo["_start_dt"] <= t <= promo["_end_dt"]):
        raise ApiError(
            "ERR_PROMOTION_INACTIVE",
            422,
            "Promotion is not ACTIVE within its program window",
        )
    order = STORES["orders"][claim["order_id"]]
    if order["status"] != "DELIVERED":
        raise ApiError(
            "ERR_ORDER_NOT_DELIVERED",
            409,
            "The referenced order must be DELIVERED before claim submission",
        )
    if promo["fund_remaining_cents"] < claim["claim_amount_cents"]:
        raise ApiError(
            "ERR_REBATE_FUND_EXHAUSTED",
            422,
            "Promotion fund is below the claim amount",
        )

    claim["status"] = "SUBMITTED"
    claim["submitted_at"] = fmt_ts(t)
    claim["_submitted_dt"] = t
    touch(claim)

    # Fund reservation; exhaustion flip at zero or below.
    promo["fund_remaining_cents"] -= claim["claim_amount_cents"]
    if promo["fund_remaining_cents"] <= 0:
        promo["status"] = "EXHAUSTED"
    touch(promo)
    return envelope.success(pub(claim))


@bp.post("/rebate-claims/<rid>/revise")
def revise_rebate_claim(rid):
    uid, role = auth_and_roles(["PracticeManager"])
    claim = get_or_404("rebate_claims", rid)
    pm_owns_or_403(role, uid, claim["practice_id"])
    data = body()
    v_str(data, "revision_note")
    if claim["status"] != "DENIED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a DENIED claim can be revised")
    claim["status"] = "DRAFT"
    claim["denial_reason"] = None
    touch(claim)
    return envelope.success(pub(claim))


@bp.post("/rebate-claims/<rid>/deny")
def deny_rebate_claim(rid):
    auth_and_roles(["ManufacturerAgent"])
    claim = get_or_404("rebate_claims", rid)
    data = body()
    denial_reason = v_str(data, "denial_reason")
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a SUBMITTED claim can be denied")
    claim["status"] = "DENIED"
    claim["denial_reason"] = denial_reason
    touch(claim)

    # Compensation: release the reservation; revive an EXHAUSTED promotion.
    promo = STORES["promotions"][claim["promotion_id"]]
    promo["fund_remaining_cents"] += claim["claim_amount_cents"]
    if promo["status"] == "EXHAUSTED" and promo["fund_remaining_cents"] > 0:
        promo["status"] = "ACTIVE"
    touch(promo)
    return envelope.success(pub(claim))


@bp.post("/rebate-claims/<rid>/settle")
def settle_rebate_claim(rid):
    auth_and_roles(["ManufacturerAgent"])
    claim = get_or_404("rebate_claims", rid)
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Only a SUBMITTED claim can be settled")
    t = now()
    claim["status"] = "PAID"
    claim["paid_at"] = fmt_ts(t)
    claim["_paid_dt"] = t
    touch(claim)
    return envelope.success(pub(claim))


# ---------------------------------------------------------------------------
# Trade-ins
# ---------------------------------------------------------------------------


@bp.post("/trade-ins")
def create_trade_in():
    uid, role = auth_and_roles(TRADE_IN_WRITE_ROLES)
    data = body()
    if role == "PracticeManager":
        pid = data.get("practice_id")
        if pid is not None:
            pm_owns_or_403(role, uid, pid)

    fk_exists(data, "practice_id", "practices")

    practice_id = v_str(data, "practice_id")
    description = v_str(data, "description")
    age_months = v_int(data, "equipment_age_months", min_val=0)
    condition = v_enum(data, "condition", CONDITIONS)
    base_value = v_int(data, "category_base_value_cents", min_val=0)

    practice = STORES["practices"][practice_id]
    if practice["status"] != "ACTIVE":
        raise ApiError(
            "ERR_PRACTICE_SUSPENDED",
            409,
            "SUSPENDED practices may not request trade-ins",
        )

    record = base_record()
    record.update(
        {
            "practice_id": practice_id,
            "description": description,
            "equipment_age_months": age_months,
            "condition": condition,
            "category_base_value_cents": base_value,
            "valuation_method": None,
            "appraised_value_cents": None,
            "applied_to_equipment_sale_id": None,
            "disposal_method": None,
            "status": "REQUESTED",
        }
    )
    STORES["trade_ins"][record["id"]] = record
    return envelope.success(pub(record), "object", 201)


@bp.get("/trade-ins/<rid>")
def get_trade_in(rid):
    uid, role = auth_and_roles(TRADE_IN_ROLES)
    trade_in = get_or_404("trade_ins", rid)
    pm_owns_or_403(role, uid, trade_in["practice_id"])
    return envelope.success(pub(trade_in))


@bp.get("/trade-ins")
def list_trade_ins():
    uid, role = auth_and_roles(TRADE_IN_ROLES)
    records = list(STORES["trade_ins"].values())
    if role == "PracticeManager":
        records = [r for r in records if r["practice_id"] == uid]
    for field in ("practice_id", "applied_to_equipment_sale_id"):
        value = request.args.get(field)
        if value is not None:
            records = [r for r in records if r.get(field) == value]
    records = sorted_default(records)
    page, pagination = paginate(records)
    return envelope.success([pub(r) for r in page], "array", 200, pagination)


@bp.post("/trade-ins/<rid>/appraise")
def appraise(rid):
    auth_and_roles(["SalesRep"])
    trade_in = get_or_404("trade_ins", rid)
    data = body()
    method = v_enum(data, "valuation_method", VALUATION_METHODS)
    if trade_in["status"] != "REQUESTED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a REQUESTED trade-in can be appraised"
        )
    trade_in["valuation_method"] = method
    trade_in["appraised_value_cents"] = appraise_trade_in(trade_in, method)
    trade_in["status"] = "APPRAISED"
    touch(trade_in)
    return envelope.success(pub(trade_in))


@bp.post("/trade-ins/<rid>/accept")
def accept_trade_in(rid):
    uid, role = auth_and_roles(["PracticeManager"])
    trade_in = get_or_404("trade_ins", rid)
    pm_owns_or_403(role, uid, trade_in["practice_id"])
    if trade_in["status"] != "APPRAISED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only an APPRAISED trade-in can be accepted"
        )
    trade_in["status"] = "ACCEPTED"
    touch(trade_in)
    return envelope.success(pub(trade_in))


@bp.post("/trade-ins/<rid>/apply-to-sale")
def apply_trade_in(rid):
    auth_and_roles(["SalesRep"])
    trade_in = get_or_404("trade_ins", rid)
    data = body()
    fk_exists(data, "equipment_sale_id", "equipment_sales")
    equipment_sale_id = v_str(data, "equipment_sale_id")

    if trade_in["status"] != "ACCEPTED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Only an ACCEPTED trade-in can be applied to a sale",
        )
    sale = STORES["equipment_sales"][equipment_sale_id]
    if sale["status"] not in ("QUOTE", "CONFIRMED"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Trade-in credit applies only to a QUOTE or CONFIRMED sale",
        )
    # The already-applied check precedes the price check.
    if sale["trade_in_id"] is not None:
        raise ApiError(
            "ERR_TRADE_IN_ALREADY_APPLIED",
            409,
            "Equipment sale already carries a trade-in credit",
        )
    if trade_in["appraised_value_cents"] > sale["sale_price_cents"]:
        raise ApiError(
            "ERR_TRADE_IN_CREDIT_EXCEEDS_PRICE",
            422,
            "Trade-in appraised value exceeds the equipment sale price",
        )

    sale["trade_in_id"] = trade_in["id"]
    sale["trade_in_credit_cents"] = trade_in["appraised_value_cents"]
    touch(sale)
    trade_in["applied_to_equipment_sale_id"] = sale["id"]
    trade_in["status"] = "CREDITED"
    touch(trade_in)
    return envelope.success(pub(trade_in))


@bp.post("/trade-ins/<rid>/dispose")
def dispose_trade_in(rid):
    auth_and_roles(["DistributionAdmin"])
    trade_in = get_or_404("trade_ins", rid)
    data = body()
    method = v_enum(data, "disposal_method", DISPOSAL_METHODS)
    if trade_in["status"] != "CREDITED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a CREDITED trade-in can be disposed"
        )
    trade_in["disposal_method"] = method
    trade_in["status"] = "DISPOSED"
    touch(trade_in)
    return envelope.success(pub(trade_in))
