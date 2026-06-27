"""Arrangement calculations: settlement floor and payoff quote."""
import math

from clock import clock, parse_iso8601
from db import db
from money import round_half_up

ADMIN_FEE_PER_DAY_CENTS = 50
FRESH_AGE_DAYS = 180
AGED_AGE_DAYS = 730
HIGH_BALANCE_CENTS = 1000000


def settlement_floor_bps(account):
    """Settlement floor (calculations.settlement_floor): MAX of age and balance
    floors, then +1000 (capped 10000) if the account has any RESOLVED dispute
    with resolution=VERIFIED."""
    charge_off = parse_iso8601(account["charge_off_date"])
    elapsed = clock.now - charge_off
    age_days = math.floor(elapsed.total_seconds() / 86400)
    if age_days < FRESH_AGE_DAYS:
        age_floor = 7000
    elif age_days < AGED_AGE_DAYS:
        age_floor = 5000
    else:
        age_floor = 3000
    balance_floor = 4000 if account["balance_cents"] >= HIGH_BALANCE_CENTS else 6000
    floor = max(age_floor, balance_floor)
    has_verified = any(
        d["account_id"] == account["id"]
        and d["status"] == "RESOLVED"
        and d.get("resolution") == "VERIFIED"
        for d in db.disputes.values()
    )
    if has_verified:
        floor = min(floor + 1000, 10000)
    return floor


def payoff_quote(arrangement, account, as_of):
    """Payoff quote (calculations.payoff_quote)."""
    if arrangement["arrangement_type"] == "SETTLEMENT":
        base = round_half_up(account["balance_cents"] * arrangement["offer_pct_bps"], 10000)
    else:
        base = account["balance_cents"]
    if as_of == "QUOTE_DATE":
        return base
    # GOOD_THROUGH: add per-day admin fee for whole days clock -> good_through, min 0.
    gt = arrangement.get("good_through")
    if not gt:
        days = 0
    else:
        gt_dt = parse_iso8601(gt)
        delta = (gt_dt - clock.now).total_seconds()
        days = max(0, math.floor(delta / 86400))
    return base + days * ADMIN_FEE_PER_DAY_CENTS
