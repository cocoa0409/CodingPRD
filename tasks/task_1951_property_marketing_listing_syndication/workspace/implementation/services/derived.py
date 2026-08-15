"""Derived read-time state (PRD 2.6) and calculation rules (scaffold table 3):
posture, feedback scores, breach counters, portal display price, relist fee."""
from decimal import Decimal, ROUND_HALF_UP

from db import store

LIVE_JOB_STATUSES = ("QUEUED", "RETRY_QUEUED", "DISPATCHED")
OVERRIDE_LIFECYCLES = ("COMPLIANCE_HOLD", "WITHDRAWN", "EXPIRED", "SOLD")

FEEDBACK_HALF_LIFE_DAYS = 14
BASE_RELIST_FEE_CENTS = 20000
VOLUME_THRESHOLD = 10
DISCOUNT_THRESHOLD_PCT = Decimal("5.0")
RELIST_COOLDOWN_DAYS = 30
DEFAULT_SLA_SECONDS = 3600
ALLOWED_INCREMENTS_CENTS = (10000, 50000, 100000, 1000000)


def jobs_of_listing(listing_id):
    return [j for j in store.jobs.values() if j["listing_id"] == listing_id]


def subs_of_listing(listing_id):
    return [s for s in store.subscriptions.values() if s["listing_id"] == listing_id]


def portal_of_job(job):
    sub = store.subscriptions.get(job["feed_subscription_id"])
    if not sub:
        return None
    return store.portals.get(sub["portal_account_id"])


def compute_breach_counts(listing_id, now):
    """(audited, provisional). Strictly-greater comparison against the SLA."""
    audited = 0
    in_flight = 0
    for j in jobs_of_listing(listing_id):
        portal = portal_of_job(j)
        sla = portal["sla_seconds"] if portal else DEFAULT_SLA_SECONDS
        st = j["status"]
        if st == "DEAD_LETTER":
            audited += 1
        elif st == "ACKED" and j["propagation_delay_seconds"] is not None \
                and j["propagation_delay_seconds"] > sla:
            audited += 1
        elif st == "DISPATCHED" and j["dispatched_at"] is not None \
                and (now - j["dispatched_at"]).total_seconds() > sla:
            in_flight += 1
    return audited, audited + in_flight


def compute_posture(listing, now):
    """First matching rule wins (PRD 2.6)."""
    if listing["lifecycle_status"] in OVERRIDE_LIFECYCLES:
        return "SUSPENDED"
    jobs = jobs_of_listing(listing["id"])
    audited, _ = compute_breach_counts(listing["id"], now)
    if audited > 0 or any(j["status"] == "DEAD_LETTER" for j in jobs):
        return "DEGRADED"
    if any(j["status"] in LIVE_JOB_STATUSES for j in jobs):
        return "SYNDICATING"
    if any(s["status"] == "SUBSCRIBED" for s in subs_of_listing(listing["id"])):
        return "SYNDICATED"
    return "NOT_SYNDICATED"


def compute_scores(listing_id, now):
    """(raw, weighted); both null when no INCLUDED feedback. 3dp round-half-up."""
    inc = [f for f in store.feedbacks.values()
           if f["listing_id"] == listing_id and f["status"] == "INCLUDED"]
    if not inc:
        return None, None
    raw = (Decimal(sum(f["rating"] for f in inc)) / Decimal(len(inc))).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP)
    num = 0.0
    den = 0.0
    for f in inc:
        age_days = (now - f["created_at"]).total_seconds() / 86400.0
        w = 2.0 ** (-age_days / FEEDBACK_HALF_LIFE_DAYS)
        num += f["rating"] * w
        den += w
    weighted = Decimal(repr(num / den)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return float(raw), float(weighted)


def display_price_cents(list_price_cents, portal):
    """Discount applied to the exact unrounded price; one round-half-up at the
    increment division; multiply back (PRD 3.5)."""
    discounted = Decimal(int(list_price_cents)) * (
        Decimal(1) - Decimal(str(portal["discount_pct"])))
    inc = int(portal["rounding_increment_cents"])
    units = (discounted / Decimal(inc)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(units) * inc


def headline_display_price_cents(listing):
    prices = []
    for s in subs_of_listing(listing["id"]):
        if s["status"] != "SUBSCRIBED":
            continue
        portal = store.portals.get(s["portal_account_id"])
        if portal:
            prices.append(display_price_cents(listing["list_price_cents"], portal))
    return min(prices) if prices else None


def relist_fee_and_pct(listing, effective_price_cents):
    """Evaluation order pinned: tier -> volume -> discount, single final rounding
    (PRD 3.9). Returns (fee_cents:int, price_reduction_pct:float)."""
    base = listing["terminal_price_cents"]
    if base is None:
        base = listing["list_price_cents"]
    effective = effective_price_cents if effective_price_cents is not None \
        else listing["list_price_cents"]
    if base:
        pct = (Decimal(100) * (Decimal(int(base)) - Decimal(int(effective)))
               / Decimal(int(base))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    else:
        pct = Decimal("0.00")
    count = listing["relist_count"]
    if count == 0:
        tier = Decimal("1.0")
    elif count == 1:
        tier = Decimal("1.5")
    else:
        tier = Decimal("2.0")
    active_count = sum(
        1 for l in store.listings.values()
        if l["agent_id"] == listing["agent_id"] and l["lifecycle_status"] == "ACTIVE")
    volume = Decimal("2.0") if active_count > VOLUME_THRESHOLD else Decimal("1.0")
    discount = Decimal("0.25") if pct >= DISCOUNT_THRESHOLD_PCT else Decimal("0")
    fee = (Decimal(BASE_RELIST_FEE_CENTS) * tier * volume * (Decimal(1) - discount)
           ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(fee), float(pct)
