"""Pure calculation functions: delay, tier, multi-segment payout, reinsurance."""

from __future__ import annotations

from typing import Iterable

# Constants from scaffold §1.3
INFINITY_SENTINEL = 99_999_999

TIER_A_MIN_MINUTES = 60
TIER_B_MIN_MINUTES = 180
TIER_C_MIN_MINUTES = 360

TIER_A_AMOUNT_CENTS = 10_000   # €100
TIER_B_AMOUNT_CENTS = 25_000   # €250
TIER_C_AMOUNT_CENTS = 60_000   # €600

BPS_DENOMINATOR = 10_000

QUORUM_WINDOW_MS = 30 * 60 * 1000  # 30 minutes
MIN_SOURCES_FOR_QUORUM = 2

PRIMARY_RETENTION_CENTS = 50_000   # €500
REINSURER_LAYER_CENTS = 30_000     # €300

NINETY_DAYS_MS = 90 * 24 * 60 * 60 * 1000


# ---------- delay_duration ----------

def compute_delay_minutes(flight: dict, delay_basis: str) -> int:
    """Compute ClaimSegment.delay_minutes_used per scaffold calc 1."""
    status = flight.get("status")
    if delay_basis == "DEPARTURE":
        if status == "CANCELLED":
            return INFINITY_SENTINEL
        actual = flight.get("actual_departure_epoch_ms")
        scheduled = flight.get("scheduled_departure_epoch_ms")
        if actual is None or scheduled is None:
            # Falling back to sentinel when we lack data; this should not occur
            # for finalised flights other than CANCELLED.
            return INFINITY_SENTINEL
        diff_ms = actual - scheduled
        return diff_ms // 60000  # floor (Python // floors toward -inf; but we expect non-negative)
    # ARRIVAL
    if status == "CANCELLED":
        return INFINITY_SENTINEL
    if status == "RETURNED":
        return INFINITY_SENTINEL
    actual = flight.get("actual_arrival_epoch_ms")
    scheduled = flight.get("scheduled_arrival_epoch_ms")
    if actual is None or scheduled is None:
        return INFINITY_SENTINEL
    diff_ms = actual - scheduled
    return diff_ms // 60000


# ---------- tier selection ----------

def select_tier(delay_minutes: int) -> tuple[str, int]:
    """Return (tier_selected, tier_amount_cents). 'NONE' indicates below-threshold."""
    if delay_minutes >= TIER_C_MIN_MINUTES or delay_minutes == INFINITY_SENTINEL:
        return "TIER_C", TIER_C_AMOUNT_CENTS
    if delay_minutes >= TIER_B_MIN_MINUTES:
        return "TIER_B", TIER_B_AMOUNT_CENTS
    if delay_minutes >= TIER_A_MIN_MINUTES:
        return "TIER_A", TIER_A_AMOUNT_CENTS
    return "NONE", 0


# ---------- gross segment payout ----------

def gross_segment_payout(payout_mode: str, tier_amount_cents: int,
                         claimed_actual_loss_cents: int,
                         reimbursement_rate_bps: int) -> int:
    """Per-segment gross payout per scaffold calc 2."""
    if payout_mode == "FIXED":
        return tier_amount_cents
    # ACTUAL_LOSS
    raw = (claimed_actual_loss_cents * reimbursement_rate_bps) // BPS_DENOMINATOR
    return min(raw, tier_amount_cents)


# ---------- multi-segment combined ----------

def combined_payout(eligible_gross: list[int], deductible_cents: int,
                    policy_limit_cents: int) -> tuple[int, int]:
    """Return (sum_gross_cents, capped_cents) per scaffold calc 3 steps 1-3."""
    sum_gross = sum(eligible_gross)
    net = max(0, sum_gross - deductible_cents)
    capped = min(net, policy_limit_cents)
    return sum_gross, capped


def prorate_segments(eligible_segments: list[dict], capped_cents: int,
                     sum_gross_cents: int) -> dict[str, int]:
    """Return {segment_id: final_segment_payout_cents} per scaffold calc 3 step 4.

    `eligible_segments` is a list of segment dicts (with 'id' and 'gross_segment_payout_cents').
    Residue allocation: largest gross_segment_payout_cents wins;
    tie-break on smallest segment id lexicographically.
    """
    out: dict[str, int] = {}
    if sum_gross_cents == 0:
        for seg in eligible_segments:
            out[seg["id"]] = 0
        return out

    for seg in eligible_segments:
        gross = seg["gross_segment_payout_cents"]
        out[seg["id"]] = (gross * capped_cents) // sum_gross_cents

    allocated = sum(out.values())
    residue = capped_cents - allocated
    if residue and eligible_segments:
        # pick the segment with largest gross; tie-break lexicographically smallest id
        best = sorted(
            eligible_segments,
            key=lambda s: (-s["gross_segment_payout_cents"], s["id"]),
        )[0]
        out[best["id"]] += residue
    return out


# ---------- reinsurance waterfall ----------

def reinsurance_waterfall(final_payout_cents: int) -> tuple[int, int]:
    """Return (primary_share_cents, reinsurer_share_cents). Sum == final_payout exactly."""
    primary_first = min(final_payout_cents, PRIMARY_RETENTION_CENTS)
    reinsurer = min(max(0, final_payout_cents - primary_first), REINSURER_LAYER_CENTS)
    primary_excess = max(0, final_payout_cents - primary_first - reinsurer)
    primary_share = primary_first + primary_excess
    return primary_share, reinsurer
