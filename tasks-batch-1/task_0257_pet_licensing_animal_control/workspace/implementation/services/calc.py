"""Calculation rules (PRD §3.6, SCAFFOLD §1.3).

All monetary amounts are integer cents. Rounding is round-half-up via Decimal
(ROUND_HALF_UP) — never float, never banker's rounding (PRD §2.7).
"""
from decimal import Decimal, ROUND_HALF_UP

# ---- license_fee constants (SCAFFOLD §1.3) ----
BASE_RATE = {"INDIVIDUAL": 4000, "KENNEL": 12000}
ALTERED_FACTOR = Decimal("0.5")
UNALTERED_FACTOR = Decimal("1.0")
KENNEL_DISCOUNT_PCT = Decimal("0.05")
KENNEL_DISCOUNT_FLOOR_PCT = Decimal("0.6")  # discounted fee never below 60% of un-discounted

# ---- dangerous_surcharge constants ----
SURCHARGE_BASE_CENTS = 5000
SEVERITY_MULT = {"BITE": Decimal("2.0") / Decimal("2"),  # 1.0
                 "ATTACK": Decimal("2.0"),
                 "NUISANCE": Decimal("0.5")}
SURCHARGE_MIN_CENTS = 3000

# ---- late_penalty constants ----
GRACE_DAYS = 30
PENALTY_TIER_1 = 200
PENALTY_TIER_1_MAX_DAYS = 30
PENALTY_TIER_2 = 500

# ---- lost_found_match constants ----
W_SPECIES = 10
W_ZIP = 20
W_TAG_EXACT = 100
MATCH_MIN_SCORE = 20


def round_half_up(dec_value):
    """Round a Decimal to a whole integer using round-half-up (PRD §2.7)."""
    return int(Decimal(dec_value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def license_fee(license_kind, is_altered, occupied_slots, variant,
                pet_is_dangerous=False, dangerous_surcharge_cents=0):
    """Compute a license fee (PRD §3.6).

    Stages, with rounding pinned at two points:
      1. base * alter_factor, round_half_up           (first rounding)
      2. KENNEL only: apply multi-pet discount, round_half_up (second rounding)
      3. final variant only: add flat dangerous surcharge AFTER all rounding.
    """
    base = BASE_RATE[license_kind]
    alter_factor = ALTERED_FACTOR if is_altered else UNALTERED_FACTOR

    fee = round_half_up(Decimal(base) * alter_factor)  # round AFTER base*alter_factor

    if license_kind == "KENNEL":
        slots = max(int(occupied_slots), 0)
        discount_pct = KENNEL_DISCOUNT_PCT * slots
        cap = Decimal("1") - KENNEL_DISCOUNT_FLOOR_PCT  # 0.4
        if discount_pct > cap:
            discount_pct = cap
        fee = round_half_up(Decimal(fee) * (Decimal("1") - discount_pct))  # round AGAIN

    if variant == "final" and pet_is_dangerous:
        fee = fee + int(dangerous_surcharge_cents)  # flat cents, no further rounding

    return fee


def dangerous_surcharge(severity):
    """Surcharge at designation (PRD §3.6): base * severity mult, round, then
    floor at minimum."""
    raw = Decimal(SURCHARGE_BASE_CENTS) * SEVERITY_MULT[severity]
    surcharge = round_half_up(raw)
    return max(surcharge, SURCHARGE_MIN_CENTS)


def late_penalty(days_late, final_fee_cents):
    """Late penalty at GRACE->EXPIRED (PRD §3.6).

    Tier boundary inclusive of tier 1: days_late <= 30 uses TIER_1, > 30 uses
    TIER_2. Result rounded then capped at the license's own final_fee_cents.
    """
    days_late = max(int(days_late), 0)
    tier_rate = PENALTY_TIER_1 if days_late <= PENALTY_TIER_1_MAX_DAYS else PENALTY_TIER_2
    raw = Decimal(days_late * tier_rate)
    penalty = round_half_up(raw)
    return min(penalty, int(final_fee_cents))


def match_score(this_report, candidate):
    """Score a candidate counterpart against this report (PRD §3.8)."""
    score = 0
    if candidate["species"] == this_report["species"]:
        score += W_SPECIES
    if candidate["zip_seen"] == this_report["zip_seen"]:
        score += W_ZIP
    c_tag = candidate.get("tag_serial_seen")
    t_tag = this_report.get("tag_serial_seen")
    if c_tag is not None and t_tag is not None and c_tag == t_tag:
        score += W_TAG_EXACT
    return score
