"""The pro tier ladder and account tier determination (PRD 2.9, 3.2)."""
from datetime import timedelta
from decimal import Decimal

import clock
import db

TRAILING_WINDOW_DAYS = 365

TIER_TABLE = [
    {"tier_code": "MEMBER", "min_trailing_volume_cents": 0,
     "discount_pct": Decimal("0.00"), "rebate_rate_pct": Decimal("0.000"), "max_quote_term_days": 15},
    {"tier_code": "GOLD", "min_trailing_volume_cents": 5000000,
     "discount_pct": Decimal("0.05"), "rebate_rate_pct": Decimal("0.010"), "max_quote_term_days": 30},
    {"tier_code": "PLATINUM", "min_trailing_volume_cents": 20000000,
     "discount_pct": Decimal("0.08"), "rebate_rate_pct": Decimal("0.020"), "max_quote_term_days": 60},
    {"tier_code": "DIAMOND", "min_trailing_volume_cents": 50000000,
     "discount_pct": Decimal("0.12"), "rebate_rate_pct": Decimal("0.030"), "max_quote_term_days": 90},
]


def tier_by_code(tier_code):
    for tier in TIER_TABLE:
        if tier["tier_code"] == tier_code:
            return tier
    return TIER_TABLE[0]


def select_tier(volume_cents):
    """Highest rung whose inclusive opening volume is at or below volume_cents."""
    best = None
    for tier in TIER_TABLE:
        if tier["min_trailing_volume_cents"] <= volume_cents:
            if best is None:
                best = tier
            elif tier["min_trailing_volume_cents"] > best["min_trailing_volume_cents"]:
                best = tier
            elif (tier["min_trailing_volume_cents"] == best["min_trailing_volume_cents"]
                  and tier["discount_pct"] > best["discount_pct"]):
                best = tier
    return best or TIER_TABLE[0]


def order_net_volume(order):
    subtotal = order.get("subtotal_cents")
    if subtotal is None:
        return 0
    return subtotal - (order.get("credited_gross_refund_cents") or 0)


def compute_trailing_volume(account):
    """Step 1: baseline plus in-window invoiced net volume. Both window ends inclusive."""
    now = clock.get_now()
    window_start = now - timedelta(days=TRAILING_WINDOW_DAYS)
    total = account.get("baseline_volume_cents") or 0
    for order in db.where("pro_orders", pro_account_id=account["id"]):
        if order["credit_status"] not in ("INVOICED", "PAID"):
            continue
        invoiced_at = order.get("_invoiced_at")
        if invoiced_at is None:
            continue
        if invoiced_at < window_start or invoiced_at > now:
            continue
        total += order_net_volume(order)
    return total


def tier_review(account):
    """A tier review event: recompute the three tier figures and stamp tier_reviewed_at."""
    volume = compute_trailing_volume(account)
    tier = select_tier(volume)
    account["trailing_volume_cents"] = volume
    account["tier_code"] = tier["tier_code"]
    account["tier_discount_pct"] = float(tier["discount_pct"])
    account["tier_reviewed_at"] = clock.now_iso()
    db.touch(account)
    return account


def persisted_discount(account):
    return tier_by_code(account.get("tier_code"))["discount_pct"]


def pricing_tier(account, order_list_subtotal_cents):
    """Which rung prices an order, per the account's tier_review_mode variant."""
    if account.get("tier_review_mode") == "ROLLING_365_INCLUSIVE":
        # The window rolls with the clock, so step 1 is re-run at the pricing
        # instant instead of reusing the figure pinned by the last review.
        volume_used = compute_trailing_volume(account) + order_list_subtotal_cents
        return select_tier(volume_used)
    return tier_by_code(account.get("tier_code"))


def account_view(account):
    """tax_exempt_state_codes is a continuously derived read (strict expiry)."""
    out = db.public(account)
    out["tax_exempt_state_codes"] = tax_exempt_state_codes(account)
    return out


def tax_exempt_state_codes(account):
    """States with a VERIFIED certificate whose expires_on is strictly after today."""
    today = clock.today()
    states = []
    for cert in db.where("tax_exempt_certificates", pro_account_id=account["id"]):
        if cert["status"] != "VERIFIED":
            continue
        expires_on = cert.get("_expires_on")
        if expires_on is None or not expires_on > today:
            continue
        if cert["state_code"] not in states:
            states.append(cert["state_code"])
    return states
