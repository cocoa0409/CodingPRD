"""Promotion, budget adjustment, and PromotionRedemption endpoints."""

from flask import Blueprint, request

import errors as E
import middleware as M
import response as R
import services as S
from db import store, new_id, stamp_created, touch

bp = Blueprint("promotions", __name__)

READ_ROLES = S.ALL_ROLES
REDEMPTION_READ_ROLES = {"DistributionAdmin", "ComplianceOfficer", "SalonBuyer"}
ADMIN_ONLY = {"DistributionAdmin"}
PROMO_TYPES = {"BUNDLE", "SAMPLE"}

BUNDLE_FIELDS = {"required_product_id", "required_qty", "free_product_id", "free_qty"}
SAMPLE_FIELDS = {"sample_product_id", "sample_units_per_redemption"}


@bp.post("/api/promotions")
def create_promotion():
    ctx = M.require_auth()
    data = M.body()
    M.no_unknown(data, {"code", "promo_type", "eligible_tiers", "starts_at", "ends_at",
                        "budget_units", "per_salon_cap",
                        "required_product_id", "required_qty", "free_product_id", "free_qty",
                        "sample_product_id", "sample_units_per_redemption"})
    code = M.req_string(data, "code")
    promo_type = M.req_enum(data, "promo_type", PROMO_TYPES)
    eligible_tiers = M.req_str_array(data, "eligible_tiers", non_empty=True)
    for t in eligible_tiers:
        if t not in S.TIERS:
            raise E.invalid_request("eligible_tiers must be a subset of {SILVER, GOLD, PLATINUM}")
    starts_at = M.req_datetime(data, "starts_at")
    ends_at = M.req_datetime(data, "ends_at")
    if not starts_at < ends_at:
        raise E.invalid_time_window("ends_at must be strictly after starts_at")
    budget_units = M.req_pos_int(data, "budget_units")
    per_salon_cap = M.req_pos_int(data, "per_salon_cap")
    required_product_id = required_qty = free_product_id = free_qty = None
    sample_product_id = sample_units = None
    if promo_type == "BUNDLE":
        required_product_id = M.req_string(data, "required_product_id")
        required_qty = M.req_pos_int(data, "required_qty")
        free_product_id = M.req_string(data, "free_product_id")
        free_qty = M.req_pos_int(data, "free_qty")
        if data.get("sample_product_id") is not None:
            sample_product_id = M.req_string(data, "sample_product_id")
        if data.get("sample_units_per_redemption") is not None:
            sample_units = M.req_pos_int(data, "sample_units_per_redemption")
    else:
        sample_product_id = M.req_string(data, "sample_product_id")
        sample_units = M.req_pos_int(data, "sample_units_per_redemption")
        if data.get("required_product_id") is not None:
            required_product_id = M.req_string(data, "required_product_id")
        if data.get("required_qty") is not None:
            required_qty = M.req_pos_int(data, "required_qty")
        if data.get("free_product_id") is not None:
            free_product_id = M.req_string(data, "free_product_id")
        if data.get("free_qty") is not None:
            free_qty = M.req_pos_int(data, "free_qty")
    M.require_role(ctx, ADMIN_ONLY)
    # existence of referenced products (pipeline step 5)
    for pid in (required_product_id, free_product_id, sample_product_id):
        if pid is not None:
            S.get_product(pid)
    for p in store.promotions.values():
        if p["code"] == code:
            raise E.duplicate_code("Promotion code already in use")
    promo = {
        "id": new_id(),
        "code": code,
        "promo_type": promo_type,
        "eligible_tiers": list(eligible_tiers),
        "starts_at": S.dt_to_iso(starts_at),
        "ends_at": S.dt_to_iso(ends_at),
        "budget_units": budget_units,
        "remaining_budget_units": None,
        "per_salon_cap": per_salon_cap,
        "status": "DRAFT",
        "required_product_id": required_product_id,
        "required_qty": required_qty,
        "free_product_id": free_product_id,
        "free_qty": free_qty,
        "sample_product_id": sample_product_id,
        "sample_units_per_redemption": sample_units,
    }
    stamp_created(promo)
    store.promotions[promo["id"]] = promo
    return R.success_object(S.pub(promo), 201)


@bp.get("/api/promotions")
def list_promotions():
    ctx = M.require_auth()
    M.require_role(ctx, READ_ROLES)
    items = list(store.promotions.values())
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    pt = request.args.get("promo_type")
    if pt is not None:
        items = [p for p in items if p["promo_type"] == pt]
    for param, field in (("required_product_id", "required_product_id"),
                         ("free_product_id", "free_product_id"),
                         ("sample_product_id", "sample_product_id")):
        v = request.args.get(param)
        if v is not None:
            items = [p for p in items if p.get(field) == v]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.pub_list(page), limit, offset, total)


@bp.get("/api/promotions/<pid>")
def get_promotion(pid):
    ctx = M.require_auth()
    M.require_role(ctx, READ_ROLES)
    return R.success_object(S.pub(S.get_promotion(pid)))


@bp.post("/api/promotions/<pid>/activate")
def activate_promotion(pid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, ADMIN_ONLY)
    promo = S.get_promotion(pid)
    if promo["status"] != "DRAFT":
        raise E.invalid_promotion_state("Only a DRAFT promotion can be activated")
    if S.parse_dt(promo["ends_at"]) <= store.clock:
        raise E.invalid_time_window("Promotion window has already ended")
    promo["status"] = "ACTIVE"
    promo["remaining_budget_units"] = promo["budget_units"]
    touch(promo)
    return R.success_object(S.pub(promo))


@bp.post("/api/promotions/<pid>/pause")
def pause_promotion(pid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, ADMIN_ONLY)
    promo = S.get_promotion(pid)
    if promo["status"] != "ACTIVE":
        raise E.invalid_promotion_state("Only an ACTIVE promotion can be paused")
    promo["status"] = "PAUSED"
    touch(promo)
    return R.success_object(S.pub(promo))


@bp.post("/api/promotions/<pid>/resume")
def resume_promotion(pid):
    ctx = M.require_auth()
    M.empty_body()
    M.require_role(ctx, ADMIN_ONLY)
    promo = S.get_promotion(pid)
    if promo["status"] != "PAUSED":
        raise E.invalid_promotion_state("Only a PAUSED promotion can be resumed")
    if S.parse_dt(promo["ends_at"]) <= store.clock:
        raise E.invalid_time_window("Promotion window has already ended")
    for pidref in (promo.get("required_product_id"), promo.get("free_product_id"),
                   promo.get("sample_product_id")):
        if pidref is None:
            continue
        product = store.products.get(pidref)
        if product is None or product["lifecycle_status"] not in ("ACTIVE", "LIQUIDATION"):
            raise E.invalid_product_state("Referenced products must be ACTIVE or LIQUIDATION")
    promo["status"] = "ACTIVE"
    touch(promo)
    return R.success_object(S.pub(promo))


@bp.post("/api/promotions/<pid>/budget-adjustments")
def budget_adjustment(pid):
    ctx = M.require_auth()
    data = M.body()
    M.no_unknown(data, {"delta_units", "expected_promotion_version"})
    delta = M.req_int(data, "delta_units")
    expected = M.req_int(data, "expected_promotion_version")
    M.require_role(ctx, ADMIN_ONLY)
    promo = S.get_promotion(pid)
    if expected != promo["version"]:
        raise E.stale_version()
    promo["budget_units"] += delta
    if promo["remaining_budget_units"] is not None:
        new_remaining = promo["remaining_budget_units"] + delta
        if new_remaining < 0:
            raise E.invalid_request("remaining_budget_units cannot go below 0")
        promo["remaining_budget_units"] = new_remaining
    touch(promo)
    return R.success_object(S.pub(promo))


# ---------------------------------------------------------------------------
# PromotionRedemption reads
# ---------------------------------------------------------------------------
@bp.get("/api/promotion-redemptions")
def list_redemptions():
    ctx = M.require_auth()
    M.require_role(ctx, REDEMPTION_READ_ROLES)
    items = list(store.redemptions.values())
    salon_id = request.args.get("salon_account_id")
    if ctx.role == "SalonBuyer":
        if salon_id is not None and salon_id != ctx.user_id:
            raise E.forbidden()
        items = [r for r in items if r["salon_account_id"] == ctx.user_id]
    elif salon_id is not None:
        items = [r for r in items if r["salon_account_id"] == salon_id]
    promotion_id = request.args.get("promotion_id")
    if promotion_id is not None:
        items = [r for r in items if r["promotion_id"] == promotion_id]
    order_id = request.args.get("order_id")
    if order_id is not None:
        items = [r for r in items if r["order_id"] == order_id]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, limit, offset, total = M.paginate(items)
    return R.success_list(S.pub_list(page), limit, offset, total)


@bp.get("/api/promotion-redemptions/<rid>")
def get_redemption(rid):
    ctx = M.require_auth()
    M.require_role(ctx, REDEMPTION_READ_ROLES)
    redemption = S.get_redemption(rid)
    S.buyer_scope(ctx, redemption["salon_account_id"])
    return R.success_object(S.pub(redemption))
