"""Calculation rules (PRD 2.9 - 2.11, 3.4, 3.6, 3.8, 3.9).

Every monetary figure is an integer count of cents; percentages are applied with
Decimal round-half-up, per component, before anything is combined (PRD 2.8).
"""

import math
from decimal import Decimal

from util import dec, rhu_cents, round_half_up, whole_seconds

# ---- rotating_barcode_token ----
BARCODE_ROTATION_SECONDS = 30
SKEW_TOLERANCE_EPOCHS = 1

# ---- zone_posture ----
RESTRICTED_RATIO_NUM, RESTRICTED_RATIO_DEN = 9, 10   # 0.90

# ---- resale_price_cap ----
STATUTORY_CAP_PCT = Decimal("0.10")
VENUE_POLICY_CAP_PCT = Decimal("0.30")
MAX_ABS_MARKUP_CENTS = 2500

# ---- resale_settlement_split ----
PLATFORM_FEE_PCT = Decimal("0.0725")
VENUE_ROYALTY_PCT = Decimal("0.0350")
PROCESSING_FEE_PCT = Decimal("0.0290")
PROCESSING_FIXED_CENTS = 30

# ---- denied_entry_remediation_credit ----
GOODWILL_TIER1_CENTS = 5000
GOODWILL_TIER2_CENTS = 15000
GOODWILL_LOW_PCT = Decimal("0.10")
GOODWILL_MID_PCT = Decimal("0.15")
GOODWILL_HIGH_PCT = Decimal("0.20")
STRIKE_PENALTY_CENTS = 500
STRIKE_PENALTY_CAP_CENTS = 2000

# ---- patron_fraud_risk_score ----
CATEGORY_WEIGHT = {
    "COUNTERFEIT": 50,
    "DEVICE_MISMATCH": 45,
    "UNAUTHORIZED_RESALE": 30,
    "DUPLICATE": 20,
    "ZONE_VIOLATION": 15,
}
DEVICE_CHURN_WEIGHT = 4
REMEDIATED_DISCOUNT = Decimal("0.5")
SCORE_CAP = 100
FRAUD_BLOCK_THRESHOLD = 40

# ---- reentry_lockout_window ----
RE_ENTRY_LOCKOUT_SECONDS = 120

# ---- credential_window_overlap_capacity ----
MAX_CREDENTIAL_REVISIONS = 2

# ---- reconciliation_variance ----
MAX_VARIANCE_PCT = Decimal("2.00")


# =====================================================================
# rotating_barcode_token
# =====================================================================

def epoch_index(anchor_dt, instant_dt):
    """floor((t - anchor) / 30), floored toward -infinity."""
    delta = whole_seconds(instant_dt) - whole_seconds(anchor_dt)
    return delta // BARCODE_ROTATION_SECONDS


def current_barcode(seed, index):
    return "%s-%d" % (seed, index)


def split_barcode(presented):
    """Split at the LAST hyphen into (seed_part, epoch_part_or_None)."""
    if not isinstance(presented, str):
        return "", None
    if "-" not in presented:
        return presented, None
    seed_part, epoch_part = presented.rsplit("-", 1)
    if seed_part.endswith("-") and epoch_part.isdigit():
        # A negative epoch index puts a second hyphen right before the digits.
        seed_part, epoch_part = seed_part[:-1], "-" + epoch_part
    return seed_part, epoch_part


def parse_epoch_part(epoch_part):
    if epoch_part is None:
        return None
    text = epoch_part.strip()
    if not text:
        return None
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        return None
    return int(text)


def epoch_accepted(presented_epoch, now_epoch):
    return (now_epoch - SKEW_TOLERANCE_EPOCHS) <= presented_epoch <= now_epoch


# =====================================================================
# zone_posture
# =====================================================================

def zone_posture(issued_entitlement_count, fire_code_capacity):
    """Exact rational comparison, inclusive boundaries."""
    if fire_code_capacity <= 0:
        return "FROZEN"
    if issued_entitlement_count >= fire_code_capacity:
        return "FROZEN"
    if issued_entitlement_count * RESTRICTED_RATIO_DEN >= fire_code_capacity * RESTRICTED_RATIO_NUM:
        return "RESTRICTED"
    return "OPEN"


# =====================================================================
# resale_price_cap
# =====================================================================

def resale_price_cap(ticket, event, seller):
    """Returns the cap in cents, or None when the regime is uncapped."""
    if ticket["ticket_type"] in ("COMP", "CREDENTIAL"):
        return 0
    regime = event["price_cap_regime"]
    if regime == "NONE":
        return None
    pct = STATUTORY_CAP_PCT if regime == "STATUTORY" else VENUE_POLICY_CAP_PCT
    face = ticket["face_value_cents"]
    markup = min(rhu_cents(dec(face) * pct), MAX_ABS_MARKUP_CENTS)
    cap = face + markup
    if regime == "STATUTORY" and not seller["identity_verified"]:
        cap = face
    return cap


# =====================================================================
# resale_settlement_split -- round per component, then sum.
# =====================================================================

def resale_settlement_split(sale_price_cents):
    platform_fee = rhu_cents(dec(sale_price_cents) * PLATFORM_FEE_PCT)
    venue_royalty = rhu_cents(dec(sale_price_cents) * VENUE_ROYALTY_PCT)
    processing_fee = rhu_cents(dec(sale_price_cents) * PROCESSING_FEE_PCT) + PROCESSING_FIXED_CENTS
    total_deductions = platform_fee + venue_royalty + processing_fee
    return {
        "platform_fee_cents": platform_fee,
        "venue_royalty_cents": venue_royalty,
        "processing_fee_cents": processing_fee,
        "seller_payout_cents": sale_price_cents - total_deductions,
    }


# =====================================================================
# credential_forgone_revenue -- round per ticket, then multiply.
# =====================================================================

def credential_forgone_revenue(zone, quantity):
    per_ticket = rhu_cents(dec(zone["face_value_reference_cents"]) * (Decimal(1) - dec(zone["comp_discount_pct"])))
    return per_ticket, per_ticket * quantity


# =====================================================================
# denied_entry_remediation_credit -- pinned five-step order.
# =====================================================================

def denied_entry_remediation_credit(ticket, patron):
    base = ticket["face_value_cents"] if ticket["ticket_type"] == "PAID" else 0
    if base <= GOODWILL_TIER1_CENTS:
        goodwill_pct = GOODWILL_LOW_PCT
    elif base <= GOODWILL_TIER2_CENTS:
        goodwill_pct = GOODWILL_MID_PCT
    else:
        goodwill_pct = GOODWILL_HIGH_PCT
    goodwill = rhu_cents(dec(base) * goodwill_pct)
    strike_count = patron["strike_count"] if patron else 0
    penalty = min(strike_count * STRIKE_PENALTY_CENTS, STRIKE_PENALTY_CAP_CENTS)
    return max(base + goodwill - penalty, 0)


# =====================================================================
# patron_fraud_risk_score -- dual variant.
# =====================================================================

def patron_fraud_risk_score(patron, incidents, variant):
    churn = DEVICE_CHURN_WEIGHT * max(patron["device_rebind_count"] - 1, 0)
    raw = churn
    for incident in incidents:
        weight = CATEGORY_WEIGHT.get(incident["category"], 0)
        status = incident["status"]
        if variant == "PROVISIONAL":
            if status in ("OPEN", "UNDER_REVIEW", "REMEDIATED"):
                raw += weight
        else:  # ADJUDICATED
            if status in ("OPEN", "UNDER_REVIEW"):
                raw += weight
            elif status == "REMEDIATED":
                raw += int(round_half_up(Decimal(weight) * REMEDIATED_DISCOUNT, 0))
            # DISMISSED contributes nothing at all.
    return min(raw, SCORE_CAP)


# =====================================================================
# live_occupancy (RECONCILED variant) & gate_clearance_projection
# =====================================================================

OUTSTANDING_LIFECYCLES = ("ISSUED", "LISTED", "TRANSFERRED", "RESOLD")


def reconciled_attendance(scan_events):
    """Distinct admitted ticket ids, any source, exits do not reduce it."""
    ordered = sorted(
        scan_events,
        key=lambda se: (se["_scanned_dt"], se["recorded_at"], se["_seq"]),
    )
    seen = []
    for se in ordered:
        if se["result"] == "ADMITTED" and se["ticket_id"] and se["ticket_id"] not in seen:
            seen.append(se["ticket_id"])
    return len(seen)


def gate_clearance_projection(gates, tickets):
    capacity_per_minute = sum(
        g["throughput_per_minute"] * g["lanes_open"] for g in gates if g["status"] == "SCANNING"
    )
    waiting = sum(
        1
        for t in tickets
        if t["lifecycle_status"] in OUTSTANDING_LIFECYCLES and t["admission_status"] == "NOT_ADMITTED"
    )
    if capacity_per_minute == 0:
        return None
    return int(math.ceil(waiting / capacity_per_minute))


# =====================================================================
# reconciliation_variance
# =====================================================================

def reconciliation_variance(reported_attendance, scan_derived_attendance, fire_code_capacity):
    variance_count = reported_attendance - scan_derived_attendance
    if scan_derived_attendance == 0:
        variance_pct = Decimal("0.00")
    else:
        variance_pct = round_half_up(
            dec(variance_count) / dec(scan_derived_attendance) * Decimal(100), 2
        )
    return {
        "scan_derived_attendance": scan_derived_attendance,
        "variance_count": variance_count,
        "variance_pct": float(variance_pct),
        "fire_code_breach": scan_derived_attendance > fire_code_capacity,
    }


def variance_within_tolerance(variance_pct):
    return abs(dec(variance_pct)) <= MAX_VARIANCE_PCT


# =====================================================================
# reentry_lockout_window / credential_window_overlap_capacity
# =====================================================================

def reentry_locked_out(last_exited_dt, clock):
    """Closed interval, both ends inclusive: allowed iff clock > exit + 120s."""
    if last_exited_dt is None:
        return False
    return whole_seconds(clock) <= whole_seconds(last_exited_dt) + RE_ENTRY_LOCKOUT_SECONDS


def windows_overlap(a_from, a_until, b_from, b_until):
    """Half-open windows: touching windows do NOT overlap."""
    return a_from < b_until and b_from < a_until
