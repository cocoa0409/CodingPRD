"""Calculation rules (SCAFFOLD 1.3 / PRD 2.8, 2.10, 3.4, 3.6, 3.11)."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from store import days_between

# --- constants -------------------------------------------------------------
CONFIRMATION_TOKEN_TTL_HOURS = 48
SOFT_BOUNCE_ESCALATION_COUNT = 3
BOUNCE_SUSPENSION_MIN_SENDS = 4
BOUNCE_SUSPENSION_HARD_RATE = Decimal("0.25")
AUDIENCE_FATIGUE_BUFFER_HOURS = 6
BILLING_PERIOD_DAYS = 30
ROLLING_WINDOW_DAYS = 90
AB_MIN_SAMPLE_PER_VARIANT = 2
AB_MIN_TOTAL_OPENS = 1
IMPORT_MIN_ROWS = 1
IMPORT_MAX_ROWS = 100

OVERAGE_BLOCK_SIZE = 5
PLAN_INCLUDED_CONTACTS = {"FREE": 2, "ESSENTIALS": 5, "STANDARD": 10, "PREMIUM": 25}
PLAN_BASE_FEE_CENTS = {"FREE": 0, "ESSENTIALS": 1300, "STANDARD": 2000, "PREMIUM": 29900}
PLAN_OVERAGE_DISCOUNT_PCT = {
    "FREE": Decimal("0.00"),
    "ESSENTIALS": Decimal("0.10"),
    "STANDARD": Decimal("0.20"),
    "PREMIUM": Decimal("0.30"),
}

SCORED_DELIVERY = ("DELIVERED", "SOFT_BOUNCED", "HARD_BOUNCED", "COMPLAINED")
TERMINAL_DELIVERY = ("DELIVERED", "HARD_BOUNCED", "SUPPRESSED", "COMPLAINED", "CANCELLED")
BILLABLE_CONSENT = ("PENDING", "CONFIRMED", "UNSUBSCRIBED")


def round_half_up(value):
    """Round a Decimal half-up to a whole unit, returning an int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def clamp_score(raw):
    return max(0, min(100, round_half_up(raw)))


# --- sender_reputation_score ----------------------------------------------
def sender_reputation(sends):
    """sends: every Send of the account. Returns (score, n_scored, n_hard)."""
    scored = [s for s in sends if s["delivery_status"] in SCORED_DELIVERY]
    n = len(scored)
    hard = sum(1 for s in scored if s["delivery_status"] == "HARD_BOUNCED")
    if n == 0:
        return 100, 0, 0
    comp = sum(1 for s in scored if s["delivery_status"] == "COMPLAINED")
    soft = sum(1 for s in scored if s["delivery_status"] == "SOFT_BOUNCED")
    dn = Decimal(n)
    hard_pct = Decimal(100) * Decimal(hard) / dn
    comp_pct = Decimal(100) * Decimal(comp) / dn
    soft_pct = Decimal(100) * Decimal(soft) / dn
    raw = (Decimal(100) - Decimal("2.0") * hard_pct - Decimal("3.0") * comp_pct
           - Decimal("0.5") * soft_pct)
    return clamp_score(raw), n, hard


def suspension_triggered(n_scored, n_hard):
    if n_scored < BOUNCE_SUSPENSION_MIN_SENDS:
        return False
    # rate >= 0.25, exact rational comparison
    return Decimal(n_hard) / Decimal(n_scored) >= BOUNCE_SUSPENSION_HARD_RATE


# --- subscriber_engagement_score ------------------------------------------
def engagement_score(sends, current_time, variant):
    """sends: every Send of the subscriber. variant: LIFETIME | ROLLING_90D."""
    pool = [s for s in sends if s["delivery_status"] == "DELIVERED"]
    if variant == "ROLLING_90D":
        # Only sends whose delivered_at falls on or after (now - 90 days).
        cutoff = current_time - timedelta(days=ROLLING_WINDOW_DAYS)
        pool = [s for s in pool
                if s.get("delivered_at") is not None and s["delivered_at"] >= cutoff]
    n = len(pool)
    if n == 0:
        return 50
    opens = sum(1 for s in pool if s["engagement_status"] in ("OPENED", "CLICKED"))
    clicks = sum(1 for s in pool if s["engagement_status"] == "CLICKED")
    dn = Decimal(n)
    open_rate = Decimal(opens) / dn
    click_rate = Decimal(clicks) / dn
    base = Decimal(100) * (Decimal("0.4") * open_rate + Decimal("0.6") * click_rate)

    firsts = [s["first_opened_at"] for s in pool if s.get("first_opened_at") is not None]
    if firsts:
        last_open = max(firsts)
        d = days_between(current_time, last_open)
        if d <= 30:
            recency = Decimal("1.0")
        elif d <= 90:
            recency = Decimal("0.8")
        else:
            recency = Decimal("0.5")
    else:
        recency = Decimal("0.5")

    volume_bonus = min(10, max(0, n - 2) * 2)
    return clamp_score(base * recency + Decimal(volume_bonus))


def engagement_state(delivered_send_count, score):
    if delivered_send_count == 0:
        return "NEW"
    if score >= 70:
        return "ENGAGED"
    if score >= 40:
        return "DORMANT"
    return "LAPSED"


# --- campaign_send_charge_cents -------------------------------------------
def send_charge_cents(recipient_count, reputation_score):
    r = recipient_count
    if r <= 10:
        rate = Decimal("2.8")
    elif r <= 50:
        rate = Decimal("2.2")
    else:
        rate = Decimal("1.6")
    subtotal_raw = Decimal(r) * rate

    if subtotal_raw < Decimal(20):
        discount_pct = Decimal("0.00")
    elif subtotal_raw < Decimal(40):
        discount_pct = Decimal("0.05")
    else:
        discount_pct = Decimal("0.10")
    discount_cents = round_half_up(subtotal_raw * discount_pct)

    if reputation_score >= 90:
        surcharge_pct = Decimal("0.00")
    elif reputation_score >= 70:
        surcharge_pct = Decimal("0.05")
    else:
        surcharge_pct = Decimal("0.20")
    surcharge_cents = round_half_up((subtotal_raw - Decimal(discount_cents)) * surcharge_pct)

    return round_half_up(subtotal_raw) - discount_cents + surcharge_cents


# --- tiered_contact_billing -----------------------------------------------
def tiered_overage_cents(peak_contact_count, tier):
    included = PLAN_INCLUDED_CONTACTS[tier]
    discount = PLAN_OVERAGE_DISCOUNT_PCT[tier]
    overage_contacts = max(0, peak_contact_count - included)
    if overage_contacts == 0:
        return 0
    n_blocks = -(-overage_contacts // OVERAGE_BLOCK_SIZE)  # ceil
    total = 0
    for i in range(1, n_blocks + 1):
        block_contacts = min(OVERAGE_BLOCK_SIZE,
                             overage_contacts - OVERAGE_BLOCK_SIZE * (i - 1))
        if i <= 2:
            rate = Decimal("27.0")
        elif i <= 5:
            rate = Decimal("19.0")
        else:
            rate = Decimal("13.0")
        # Rounding order is pinned: round EACH BLOCK, THEN sum.
        total += round_half_up(Decimal(block_contacts) * rate * (Decimal(1) - discount))
    return total


# --- segment_member_set ----------------------------------------------------
def segment_matches(segment, subscriber, current_time):
    if subscriber["audience_id"] != segment["audience_id"]:
        return False
    if subscriber["consent_state"] not in segment["consent_states"]:
        return False
    if subscriber["engagement_score"] < segment["min_engagement_score"]:
        return False
    max_days = segment.get("max_days_since_open")
    if max_days is not None:
        last = subscriber.get("last_opened_at")
        if last is None:
            return False
        if days_between(current_time, last) > max_days:
            return False
    return True
