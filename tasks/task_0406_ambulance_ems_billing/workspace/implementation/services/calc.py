"""Calculation rules (SCAFFOLD §1.3 / PRD §3).

All monetary amounts are integer cents. Where a calculation produces a
fractional cent the result is rounded HALF UP. Several totals floor at zero.
"""

from decimal import Decimal, ROUND_HALF_UP

# ---- Billing fee schedule (PRD §3.3 / SCAFFOLD compute_charge_billed_amount) ----
BASE_RATE_CENTS = {
    "A0428": 45000,  # BLS non-emergency
    "A0429": 60000,  # BLS emergency
    "A0426": 65000,  # ALS1 non-emergency
    "A0427": 80000,  # ALS1 emergency
    "A0433": 110000,  # ALS2
    "A0434": 130000,  # SCT
}
MILEAGE_CENTS_PER_MILE = 1750
RURAL_BONUS_FACTOR = Decimal("1.5")
RURAL_BONUS_MILE_CAP = Decimal("17")

# ---- Medicare allowed baseline (PRD §3.7 / SCAFFOLD adjudicated_allowed) ----
MEDICARE_ALLOWED_BASE = {
    "A0428": 23000,
    "A0429": 31000,
    "A0426": 33000,
    "A0427": 41000,
    "A0433": 56000,
    "A0434": 66000,
}
MEDICARE_ALLOWED_MILEAGE_CENTS_PER_MILE = 800
MEDICARE_RURAL_BONUS_FACTOR = Decimal("1.5")
MEDICAID_FACTOR = Decimal("0.80")

# ---- Charity FPL (PRD §3.10 / SCAFFOLD charity_writeoff) ----
FPL_FIRST_PERSON_CENTS = 1508000
FPL_PER_ADDL_CENTS = 532000


def round_half_up(value):
    """Round a numeric value half-up to a whole integer (cents/percent)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# =============================================================================
# resolve_hcpcs_lines
# =============================================================================
def resolve_base_code(level_of_service, emergency_indicator):
    """Resolve the BASE_RATE HCPCS code from LOS + emergency flag."""
    los = level_of_service
    em = bool(emergency_indicator)
    if los == "BLS":
        return "A0429" if em else "A0428"
    if los == "ALS1":
        return "A0427" if em else "A0426"
    if los == "ALS2":
        return "A0433"  # ALS2 always emergency-grade
    if los == "SCT":
        return "A0434"
    return None


MILEAGE_CODE = "A0425"  # ground mileage, always per-loaded-mile


# =============================================================================
# compute_charge_billed_amount
# =============================================================================
def compute_base_billed(base_code):
    return BASE_RATE_CENTS[base_code]


def compute_mileage_billed(loaded_miles, is_rural_pickup):
    """Per-tier round half-up BEFORE summing (round-per-tier-then-sum)."""
    miles = Decimal(str(loaded_miles))
    if is_rural_pickup:
        rural_miles = min(miles, RURAL_BONUS_MILE_CAP)
        normal_miles = max(miles - RURAL_BONUS_MILE_CAP, Decimal("0"))
        tier1 = round_half_up(rural_miles * MILEAGE_CENTS_PER_MILE * RURAL_BONUS_FACTOR)
        tier2 = round_half_up(normal_miles * MILEAGE_CENTS_PER_MILE)
        return tier1 + tier2
    return round_half_up(miles * MILEAGE_CENTS_PER_MILE)


# =============================================================================
# Medicare baseline for a transport (used by adjudicated_allowed)
# =============================================================================
def medicare_baseline(base_code, loaded_miles, is_rural_pickup):
    """Medicare fee-schedule baseline = base component + mileage component.

    Mileage at 800 c/mile with the same first-17-mile rural bonus factor 1.5.
    Per-tier round half-up before summing (mirrors the billing mileage rule).
    """
    base_component = MEDICARE_ALLOWED_BASE[base_code]
    miles = Decimal(str(loaded_miles))
    if is_rural_pickup:
        rural_miles = min(miles, RURAL_BONUS_MILE_CAP)
        normal_miles = max(miles - RURAL_BONUS_MILE_CAP, Decimal("0"))
        tier1 = round_half_up(
            rural_miles * MEDICARE_ALLOWED_MILEAGE_CENTS_PER_MILE * MEDICARE_RURAL_BONUS_FACTOR
        )
        tier2 = round_half_up(normal_miles * MEDICARE_ALLOWED_MILEAGE_CENTS_PER_MILE)
        mileage_component = tier1 + tier2
    else:
        mileage_component = round_half_up(miles * MEDICARE_ALLOWED_MILEAGE_CENTS_PER_MILE)
    return base_component + mileage_component


# =============================================================================
# adjudicated_allowed (dual-variant calc #1)
# =============================================================================
def adjudicated_allowed(reported_allowed_cents, payer_type, qpa_multiplier,
                        base_code, loaded_miles, is_rural_pickup,
                        total_billed_cents, claim_billed_cents, claim_prior_paid_cents):
    """Compute the claim's adjudicated allowed amount.

    Variant A (payer_reported): reported_allowed_cents provided -> verbatim.
    Variant B (fee_schedule_derived): derive from Medicare baseline scaled by
        payer_type factor / QPA multiplier.
    Then COB-cap at the remaining gap: min(allowed, billed - prior_paid).
    """
    if reported_allowed_cents is not None:
        allowed = int(reported_allowed_cents)
    else:
        base = medicare_baseline(base_code, loaded_miles, is_rural_pickup)
        if payer_type == "MEDICARE":
            allowed = base
        elif payer_type == "MEDICAID":
            allowed = round_half_up(Decimal(base) * MEDICAID_FACTOR)
        elif payer_type in ("COMMERCIAL", "AUTO"):
            allowed = round_half_up(Decimal(base) * Decimal(str(qpa_multiplier)))
        elif payer_type == "SELF_PAY":
            allowed = int(total_billed_cents)
        else:
            allowed = base
    # COB cap: never allow more than the remaining gap available to this payer.
    cap = int(claim_billed_cents) - int(claim_prior_paid_cents)
    allowed = min(allowed, cap)
    return allowed


# =============================================================================
# contractual_adjustment
# =============================================================================
def contractual_adjustment(payer_type, sequence_rank, billed_cents,
                           allowed_cents, prior_paid_cents):
    """Contractual write-off recorded when a PAID/PARTIAL line posts.

    PRIMARY (rank 1):
      MEDICARE/MEDICAID -> full gap = max(billed - allowed, 0)
      COMMERCIAL/AUTO/SELF_PAY -> 0 at remit time (gap stays on patient balance)
    SECONDARY/TERTIARY (rank > 1):
      residual gap = max((billed - prior_paid) - allowed, 0)
    """
    if sequence_rank == 1:
        if payer_type in ("MEDICARE", "MEDICAID"):
            return max(int(billed_cents) - int(allowed_cents), 0)
        return 0
    return max((int(billed_cents) - int(prior_paid_cents)) - int(allowed_cents), 0)


# =============================================================================
# charity_writeoff helper: income percent of FPL
# =============================================================================
def charity_income_pct_of_fpl(income_cents, household_size):
    fpl_base = FPL_FIRST_PERSON_CENTS + (int(household_size) - 1) * FPL_PER_ADDL_CENTS
    # round half up to a whole percent BEFORE the comparison.
    return round_half_up(Decimal(int(income_cents)) * 100 / Decimal(fpl_base))
