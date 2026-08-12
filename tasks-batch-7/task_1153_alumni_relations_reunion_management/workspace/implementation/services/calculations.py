"""Calculation rules from SCAFFOLD §1.3: engagement score, tier thresholds,
giving propensity, ticket pricing, campaign matching credit, posture,
suppression recompute. All rounded half-up via Decimal."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from services.common import touch


def _d2(value):
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _f2(value):
    """Decimal quantized to 2dp, returned as float for JSON output."""
    return float(_d2(value))


# ---------------------------------------------------------------------------
# engagement_score_calc
# ---------------------------------------------------------------------------

def compute_engagement_score(alumni_id, provisional=False):
    """FINAL variant by default; PROVISIONAL counts PLEDGED pledges at 50%."""
    # event_points: registrations with payment_status CONFIRMED or CHECKED_IN
    event_count = 0
    for reg in db.registrations.values():
        if reg["alumni_id"] != alumni_id:
            continue
        if reg["payment_status"] in ("CONFIRMED", "CHECKED_IN"):
            event_count += 1
    event_points = min(100, 25 * event_count)

    # giving_points: lifetime_giving_cents -> 1 point per $10 ($1000 => 100)
    record = db.records.get(alumni_id)
    lifetime_cents = record["lifetime_giving_cents"] if record else 0
    giving_cents_effective = lifetime_cents
    if provisional:
        pledged_cents = sum(
            p["amount_cents"] for p in db.pledges.values()
            if p["alumni_id"] == alumni_id and p["status"] == "PLEDGED"
        )
        giving_cents_effective = lifetime_cents + pledged_cents * Decimal("0.5")
    giving_points = min(
        Decimal("100"),
        (Decimal(str(giving_cents_effective)) / Decimal("100000")) * Decimal("100"),
    )

    # service_points: memberships ACTIVE or ENDED, excluding ALUMNUS_DECEASED
    service_count = 0
    for m in db.memberships.values():
        if m["alumni_id"] != alumni_id:
            continue
        if m["status"] == "ACTIVE":
            service_count += 1
        elif m["status"] == "ENDED" and m.get("ended_reason") != "ALUMNUS_DECEASED":
            service_count += 1
    service_points = min(100, 20 * service_count)

    score = (Decimal("0.50") * Decimal(str(event_points))
             + Decimal("0.30") * giving_points
             + Decimal("0.20") * Decimal(str(service_points)))
    score = min(Decimal("100.00"), score)
    return _f2(score)


def engagement_tier_for(score):
    """Inclusive thresholds: >= 70.00 HIGH, >= 30.00 MEDIUM, else LOW."""
    s = _d2(score)
    if s >= Decimal("70.00"):
        return "HIGH"
    if s >= Decimal("30.00"):
        return "MEDIUM"
    return "LOW"


def compute_giving_propensity(alumni_id):
    """Reads the just-persisted engagement_score (pinned evaluation order)."""
    record = db.records.get(alumni_id)
    if record is None:
        return 0.0
    score = _d2(record["engagement_score"])
    base = score / Decimal("100.0")

    now = db.logical_now()
    window_start = now - timedelta(days=365)
    recency = Decimal("0.0")
    for p in db.pledges.values():
        if p["alumni_id"] == alumni_id and p["status"] == "FULFILLED":
            fulfilled_at = p.get("fulfilled_at_dt")
            if fulfilled_at is not None and window_start <= fulfilled_at <= now:
                recency = Decimal("0.15")
                break

    capacity = min(
        Decimal("0.25"),
        (Decimal(record["lifetime_giving_cents"]) / Decimal("1000000")) * Decimal("0.25"),
    )

    propensity = base * Decimal("0.7") + recency + capacity
    propensity = min(Decimal("1.00"), propensity)
    return _f2(propensity)


def recompute_engagement(alumni_id, also_propensity=True):
    """Persist FINAL engagement_score, re-derive tier, then propensity."""
    record = db.records.get(alumni_id)
    if record is None:
        return
    record["engagement_score"] = compute_engagement_score(alumni_id, provisional=False)
    record["engagement_tier"] = engagement_tier_for(record["engagement_score"])
    if also_propensity:
        record["giving_propensity"] = compute_giving_propensity(alumni_id)
    touch(record)


def recompute_propensity(alumni_id):
    record = db.records.get(alumni_id)
    if record is None:
        return
    record["giving_propensity"] = compute_giving_propensity(alumni_id)
    touch(record)


# ---------------------------------------------------------------------------
# ticket_price_calc
# ---------------------------------------------------------------------------

EARLY_BIRD_CUTOFF_DAYS = 60
LATE_FEE_CENTS = 1500
LATE_FEE_WINDOW_DAYS = 7
COMMITTEE_DISCOUNT_FACTOR = Decimal("0.75")


def _has_active_committee_membership(event_id, alumni_id):
    committee = next((c for c in db.committees.values() if c["event_id"] == event_id), None)
    if committee is None:
        return False
    for m in db.memberships.values():
        if (m["committee_id"] == committee["id"]
                and m["alumni_id"] == alumni_id
                and m["status"] == "ACTIVE"):
            return True
    return False


def ticket_price(tier, event, alumni_id, variant):
    """variant: 'ESTIMATE' or 'FINAL'. Returns integer cents, round-half-up at
    the final step only; intermediate steps unrounded."""
    now = db.logical_now()
    event_date = event["event_date_dt"]
    cutoff = event_date - timedelta(days=EARLY_BIRD_CUTOFF_DAYS)

    price = Decimal(tier["base_price_cents"])

    # (1) early-bird discount
    if now < cutoff:
        pct = Decimal(tier.get("early_bird_discount_pct", 0))
        price = price * (Decimal("100") - pct) / Decimal("100")

    # (2) committee discount
    if _has_active_committee_membership(event["id"], alumni_id):
        price = price * COMMITTEE_DISCOUNT_FACTOR

    # (3) late fee — FINAL variant only (ESTIMATE ignores it entirely)
    if variant == "FINAL":
        if now > event_date - timedelta(days=LATE_FEE_WINDOW_DAYS):
            price = price + Decimal(LATE_FEE_CENTS)

    # (4) round half-up to integer cents
    return int(price.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# campaign_matching_credit
# ---------------------------------------------------------------------------

def matching_credit(amount_cents, multiplier_bps):
    """Per-pledge: round_half_up(amount * bps / 10000)."""
    if not multiplier_bps:
        return 0
    value = (Decimal(amount_cents) * Decimal(multiplier_bps)) / Decimal("10000")
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# reunion_posture_calc
# ---------------------------------------------------------------------------

def derive_posture(event):
    if event["status"] != "OPEN_FOR_REGISTRATION":
        if event["status"] in ("HELD", "RECONCILED", "CANCELLED"):
            return "CLOSED"
        return "GATED"
    if event["committee_count"] < event["committee_quorum_required"]:
        return "GATED"
    tiers = [t for t in db.ticket_tiers.values() if t["event_id"] == event["id"]]
    bookable = [t for t in tiers if t["capacity"] == 0 or t["sold_count"] < t["capacity"]]
    if len(bookable) == 0:
        return "SOLD_OUT"
    return "OPEN"


def rederive_posture(event):
    new_posture = derive_posture(event)
    if event.get("posture") != new_posture:
        event["posture"] = new_posture
    touch(event)


# ---------------------------------------------------------------------------
# suppression_recompute
# ---------------------------------------------------------------------------

def recompute_preference_suppression(pref):
    """Recompute a single CommunicationPreference row's suppressed flag and reason."""
    record = db.records.get(pref["alumni_id"])
    suppressed = False
    reason = "NONE"
    if record is not None and record["status"] in ("DO_NOT_CONTACT", "DECEASED"):
        suppressed = True
        reason = "DO_NOT_CONTACT_RECORD"
    elif (pref["alumni_id"], pref["channel"]) in db.suppression_list:
        suppressed = True
        reason = "GLOBAL_LIST"
    elif (pref["channel"] == "EMAIL" and record is not None
          and record.get("hard_bounce_flag")):
        suppressed = True
        reason = "HARD_BOUNCE"
    if pref.get("suppressed") != suppressed or pref.get("suppression_reason") != reason:
        pref["suppressed"] = suppressed
        pref["suppression_reason"] = reason
        touch(pref)


def recompute_all_preferences_for(alumni_id):
    for pref in db.preferences.values():
        if pref["alumni_id"] == alumni_id:
            recompute_preference_suppression(pref)
