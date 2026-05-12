"""Domain thresholds and helpers from the PRD.

Numeric constants drive boundary-precision tests in §3.4 (cancellation
refund tiers), §3.5 (peak multiplier, basis-points splits), and §2.3
(pagination).
"""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP


# ---------------------------------------------------------------------------
# Cancellation refund tiers (PRD §3.4)
# ---------------------------------------------------------------------------
# "When that lead is at least 24 hours (the full-refund minimum),
#  cancellation_refund_bps is set to 10000 ... at least 2 hours
#  (the partial-refund minimum), cancellation_refund_bps is set to 5000
#  ... less than 2 hours, cancellation_refund_bps is set to 0."
FULL_REFUND_MIN_MINUTES = 24 * 60   # 1440
PARTIAL_REFUND_MIN_MINUTES = 2 * 60  # 120
FULL_REFUND_BPS = 10000
PARTIAL_REFUND_BPS = 5000
NO_REFUND_BPS = 0


# ---------------------------------------------------------------------------
# Basis-points ceiling (PRD §2.6)
# ---------------------------------------------------------------------------
# "Basis points are integers in the inclusive range 0 through 10000,
#  where 10000 represents 100 percent."
BPS_MAX = 10000


# ---------------------------------------------------------------------------
# Authorization eligibility weights (PRD §3.2)
# ---------------------------------------------------------------------------
# "training_match weighted by 30, the sample_match weighted by 30, the
#  affiliation_match weighted by 20, and the identity_match weighted by 20,
#  giving a maximum of 100."
TRAINING_WEIGHT = 30
SAMPLE_WEIGHT = 30
AFFILIATION_WEIGHT = 20
IDENTITY_WEIGHT = 20
QUALIFICATION_THRESHOLD = 100


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Check-in window (PRD §3.6)
# ---------------------------------------------------------------------------
# "a User opens a session by checking in on their own reservation no
#  earlier than 15 minutes before start_at"
CHECK_IN_EARLY_MINUTES = 15


# ---------------------------------------------------------------------------
# Maintenance-rejection follow-up window (PRD §3.7)
# ---------------------------------------------------------------------------
# "spawns a follow-up AD_HOC MaintenanceWindow with start_at equal to the
#  server clock and end_at equal to the server clock plus 24 hours"
MAINTENANCE_FOLLOWUP_HOURS = 24


# ---------------------------------------------------------------------------
# Abnormal-checkout follow-up window (PRD §3.6)
# ---------------------------------------------------------------------------
ABNORMAL_CHECKOUT_FOLLOWUP_HOURS = 24


# ---------------------------------------------------------------------------
# Round-half-up helper for cents (PRD §2.6)
# ---------------------------------------------------------------------------
def round_half_up_cents(value: Decimal) -> int:
    """PRD §2.6: 'round half up' (half-cent always rounds away from zero,
    toward positive infinity for positive amounts)."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Estimated fee helper (PRD §3.5)
# ---------------------------------------------------------------------------
def compute_estimated_fee(
    *,
    mode: str,
    affiliation: str,
    rule: dict,
    revenue_share_bps: int,
    billed_hours_rational: Decimal,
    requested_sample_count: int,
    peak_overlap_minutes: int,
) -> dict:
    """Compute the four fee outputs per PRD §3.5 (forward-looking).

    Returns dict with keys:
      equipment_fee_cents, platform_fee_cents, consumables_cents,
      estimated_fee_cents, estimated_owner_share_cents,
      estimated_platform_fee_cents.
    """
    if affiliation == "WITHIN_SCHOOL":
        time_rate = rule["internal_rate_per_hour_cents"]
        sample_rate = rule["internal_rate_per_sample_cents"]
    elif affiliation == "INTER_SCHOOL":
        time_rate = rule["inter_school_rate_per_hour_cents"]
        sample_rate = rule["inter_school_rate_per_sample_cents"]
    else:  # EXTERNAL
        time_rate = rule["external_rate_per_hour_cents"]
        sample_rate = rule["external_rate_per_sample_cents"]

    if mode == "BY_SAMPLE":
        time_raw = Decimal(0)
    else:
        time_raw = billed_hours_rational * Decimal(time_rate)

    if mode == "BY_TIME":
        sample_raw = Decimal(0)
    else:
        sample_raw = Decimal(requested_sample_count) * Decimal(sample_rate)

    if peak_overlap_minutes > 0:
        time_raw = time_raw * Decimal(rule["peak_multiplier_bps"]) / Decimal(10000)

    equipment_fee_cents = round_half_up_cents(time_raw + sample_raw)
    platform_fee_cents = round_half_up_cents(
        Decimal(equipment_fee_cents)
        * Decimal(rule["platform_fee_bps"]) / Decimal(10000)
    )
    consumables_cents = rule["consumables_flat_cents"]
    estimated_fee_cents = (
        equipment_fee_cents + platform_fee_cents + consumables_cents
    )
    owner_share_cents = round_half_up_cents(
        Decimal(equipment_fee_cents)
        * Decimal(revenue_share_bps) / Decimal(10000)
    )
    return {
        "equipment_fee_cents": equipment_fee_cents,
        "platform_fee_cents": platform_fee_cents,
        "consumables_cents": consumables_cents,
        "estimated_fee_cents": estimated_fee_cents,
        "estimated_owner_share_cents": owner_share_cents,
        "estimated_platform_fee_cents": platform_fee_cents,
    }


def compute_final_fee(
    *,
    mode: str,
    affiliation: str,
    rule: dict,
    revenue_share_bps: int,
    actual_billed_hours: int,
    actual_sample_count: int,
    peak_overlap_minutes: int,
) -> dict:
    """Compute final fee per PRD §3.5 chronological branch.

    actual_billed_hours = ceil(actual_minutes / 60.0).
    """
    if affiliation == "WITHIN_SCHOOL":
        time_rate = rule["internal_rate_per_hour_cents"]
        sample_rate = rule["internal_rate_per_sample_cents"]
    elif affiliation == "INTER_SCHOOL":
        time_rate = rule["inter_school_rate_per_hour_cents"]
        sample_rate = rule["inter_school_rate_per_sample_cents"]
    else:
        time_rate = rule["external_rate_per_hour_cents"]
        sample_rate = rule["external_rate_per_sample_cents"]

    if mode == "BY_SAMPLE":
        time_raw = Decimal(0)
    else:
        time_raw = Decimal(actual_billed_hours) * Decimal(time_rate)

    if mode == "BY_TIME":
        sample_raw = Decimal(0)
    else:
        sample_raw = Decimal(actual_sample_count) * Decimal(sample_rate)

    if peak_overlap_minutes > 0:
        time_raw = time_raw * Decimal(rule["peak_multiplier_bps"]) / Decimal(10000)

    equipment_fee_cents = round_half_up_cents(time_raw + sample_raw)
    platform_fee_cents = round_half_up_cents(
        Decimal(equipment_fee_cents)
        * Decimal(rule["platform_fee_bps"]) / Decimal(10000)
    )
    consumables_cents = rule["consumables_flat_cents"]
    final_fee_cents = (
        equipment_fee_cents + platform_fee_cents + consumables_cents
    )
    owner_share_cents = round_half_up_cents(
        Decimal(equipment_fee_cents)
        * Decimal(revenue_share_bps) / Decimal(10000)
    )
    return {
        "equipment_fee_cents": equipment_fee_cents,
        "platform_fee_cents": platform_fee_cents,
        "consumables_cents": consumables_cents,
        "final_fee_cents": final_fee_cents,
        "final_owner_share_cents": owner_share_cents,
        "final_platform_fee_cents": platform_fee_cents,
    }


__all__ = [
    "FULL_REFUND_MIN_MINUTES",
    "PARTIAL_REFUND_MIN_MINUTES",
    "FULL_REFUND_BPS",
    "PARTIAL_REFUND_BPS",
    "NO_REFUND_BPS",
    "BPS_MAX",
    "TRAINING_WEIGHT",
    "SAMPLE_WEIGHT",
    "AFFILIATION_WEIGHT",
    "IDENTITY_WEIGHT",
    "QUALIFICATION_THRESHOLD",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "CHECK_IN_EARLY_MINUTES",
    "MAINTENANCE_FOLLOWUP_HOURS",
    "ABNORMAL_CHECKOUT_FOLLOWUP_HOURS",
    "round_half_up_cents",
    "compute_estimated_fee",
    "compute_final_fee",
]
