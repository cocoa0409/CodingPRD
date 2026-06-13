"""Redeemability / eligibility / cap checks shared by apply, lock, checkout
(PRD §3.8, §3.10, §3.11; scaffold §1.3 calcs 6-7, §1.4 priorities 11-17)."""
from db import db
from errors import err


def clock_in_window(promotion, clock):
    """Clock within [active_from, active_until) — inclusive start, exclusive end."""
    from db import parse_dt

    af = parse_dt(promotion["active_from"])
    au = parse_dt(promotion["active_until"])
    return af <= clock < au


def clock_in_any_blackout(promotion, clock):
    from db import parse_dt

    for bw in db.blackout_windows.values():
        if bw["promotion_id"] != promotion["id"]:
            continue
        starts = parse_dt(bw["starts_at"])
        ends = parse_dt(bw["ends_at"])
        if starts <= clock < ends:
            return True
    return False


def is_redeemable(promotion, clock):
    """Promotion-level redeemability: ACTIVE, within window, not in blackout."""
    if promotion["status"] != "ACTIVE":
        return False
    if not clock_in_window(promotion, clock):
        return False
    if clock_in_any_blackout(promotion, clock):
        return False
    return True


def eligibility_ok(promotion, customer):
    mode = promotion["eligibility_mode"]
    if mode == "ALL":
        return True
    if mode == "FIRST_ORDER":
        return customer["order_count"] == 0
    if mode == "SEGMENT":
        seg_id = promotion["eligible_segment_id"]
        for m in db.segment_memberships.values():
            if (
                m["customer_id"] == customer["id"]
                and m["segment_id"] == seg_id
                and m["status"] == "ACTIVE"
            ):
                return True
        return False
    return False


def coupon_committed_count(coupon_id):
    """CONFIRMED + RESERVED redemptions for a coupon."""
    return sum(
        1
        for r in db.coupon_redemptions.values()
        if r["coupon_id"] == coupon_id and r["status"] in ("CONFIRMED", "RESERVED")
    )


def coupon_cap(coupon):
    if coupon["use_mode"] == "SINGLE_USE":
        return 1
    return coupon["max_total_redemptions"]


def customer_uses(promotion_id, customer_id):
    """CONFIRMED + RESERVED redemptions of a promotion by a customer."""
    return sum(
        1
        for r in db.coupon_redemptions.values()
        if r["promotion_id"] == promotion_id
        and r["customer_id"] == customer_id
        and r["status"] in ("CONFIRMED", "RESERVED")
    )


def committed_budget(promotion_id):
    """Sum of discount_cents over CONFIRMED + RESERVED redemptions."""
    return sum(
        r["discount_cents"]
        for r in db.coupon_redemptions.values()
        if r["promotion_id"] == promotion_id and r["status"] in ("CONFIRMED", "RESERVED")
    )


def confirmed_budget(promotion_id):
    """Sum of discount_cents over CONFIRMED redemptions (the derived field)."""
    return sum(
        r["discount_cents"]
        for r in db.coupon_redemptions.values()
        if r["promotion_id"] == promotion_id and r["status"] == "CONFIRMED"
    )


def confirmed_coupon_count(coupon_id):
    return sum(
        1
        for r in db.coupon_redemptions.values()
        if r["coupon_id"] == coupon_id and r["status"] == "CONFIRMED"
    )


def check_caps(promotion, coupon, customer, new_discount, *, count_self=None):
    """Run coupon-cap, abuse-limit, and budget-headroom checks in priority order
    (PRD §2.9: coupon-cap -> abuse -> budget-would-exceed -> budget-exhausted).

    `count_self` (a redemption record being re-checked) is excluded from the
    committed tallies and counted explicitly as already-present where needed —
    used at checkout/lock re-verification so a redemption is not counted twice.
    """
    # Coupon usage cap (priority 14).
    if coupon is not None:
        uses = coupon_committed_count(coupon["id"])
        if count_self is not None and count_self["coupon_id"] == coupon["id"]:
            pass  # count_self already included in uses; re-check is "still within"
        cap = coupon_cap(coupon)
        if count_self is None:
            if uses >= cap:
                raise err("ERR_COUPON_EXHAUSTED", "Coupon usage cap reached")
        else:
            if uses > cap:
                raise err("ERR_COUPON_EXHAUSTED", "Coupon usage cap reached")

    # Per-customer abuse limit (priority 15).
    limit = promotion["max_redemptions_per_customer"]
    if limit is not None:
        uses = customer_uses(promotion["id"], customer["id"])
        if count_self is None:
            if uses >= limit:
                raise err("ERR_ABUSE_LIMIT_EXCEEDED", "Per-customer abuse limit reached")
        else:
            if uses > limit:
                raise err("ERR_ABUSE_LIMIT_EXCEEDED", "Per-customer abuse limit reached")

    # Budget headroom (priority 16). The already-EXHAUSTED case (priority 17) is
    # surfaced separately: an EXHAUSTED promotion has status != ACTIVE and is
    # rejected earlier by the redeemability check (ERR_PROMO_NOT_REDEEMABLE);
    # the budget-exhausted error is only reached when the caller explicitly maps
    # an EXHAUSTED status to it (auto-apply candidate filtering).
    cap_cents = promotion["budget_cap_cents"]
    if cap_cents is not None:
        committed = committed_budget(promotion["id"])
        if count_self is None:
            if committed + new_discount > cap_cents:
                raise err(
                    "ERR_PROMO_BUDGET_WOULD_EXCEED",
                    "Promotion budget would be exceeded",
                )
        else:
            # Re-check at lock/checkout: the redemption is already in `committed`.
            if committed > cap_cents:
                raise err(
                    "ERR_PROMO_BUDGET_WOULD_EXCEED",
                    "Promotion budget would be exceeded",
                )
