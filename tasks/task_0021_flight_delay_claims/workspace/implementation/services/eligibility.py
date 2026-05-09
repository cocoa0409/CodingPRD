"""Per-segment eligibility and gross-payout computation."""

from __future__ import annotations

from db import db
from services.calculations import (
    INFINITY_SENTINEL,
    compute_delay_minutes,
    gross_segment_payout,
    select_tier,
)


def compute_segment_eligibility(segment: dict, claim: dict, policy: dict, ticket: dict, flight: dict) -> None:
    """Mutate the segment in-place: set delay_minutes_used, eligibility, tier_selected, gross_segment_payout_cents.

    Decision order (per PRD §3.5):
      1. Excluded cause → EXCLUDED_CAUSE
      2. Waiting period → WAITING_PERIOD
      3. Ticket REFUNDED/UNMATCHED → TICKET_NOT_BOUND
      4. delay below threshold → DELAY_BELOW_THRESHOLD
      5. else → ELIGIBLE
    """
    delay_basis = policy["delay_basis"]
    delay_minutes = compute_delay_minutes(flight, delay_basis)
    segment["delay_minutes_used"] = delay_minutes

    excluded_causes = policy.get("excluded_delay_causes") or []
    classified_cause = flight.get("classified_cause")

    # Tier selection (used for gross payout regardless of eligibility resolution)
    tier_selected, tier_amount_cents = select_tier(delay_minutes)
    segment["tier_selected"] = tier_selected

    # Compute gross payout per the (selected tier, payout_mode)
    gross = gross_segment_payout(
        payout_mode=policy["payout_mode"],
        tier_amount_cents=tier_amount_cents,
        claimed_actual_loss_cents=segment.get("claimed_actual_loss_cents", 0) or 0,
        reimbursement_rate_bps=policy.get("reimbursement_rate_bps", 0) or 0,
    )
    segment["gross_segment_payout_cents"] = gross

    # Eligibility classification (priority order per PRD §3.5)
    if classified_cause is not None and classified_cause in excluded_causes:
        segment["eligibility"] = "EXCLUDED_CAUSE"
        return
    if ticket["scheduled_departure_epoch_ms"] < (
        policy["effective_from_epoch_ms"] + (policy.get("waiting_period_ms", 0) or 0)
    ):
        segment["eligibility"] = "WAITING_PERIOD"
        return
    if ticket["status"] in ("REFUNDED", "UNMATCHED"):
        segment["eligibility"] = "TICKET_NOT_BOUND"
        return
    if delay_minutes < 60:
        segment["eligibility"] = "DELAY_BELOW_THRESHOLD"
        return
    segment["eligibility"] = "ELIGIBLE"


def recompute_claim_segments(claim: dict) -> None:
    """Recompute every segment's eligibility/gross/tier/delay for a claim."""
    policy = db.policies[claim["policy_id"]]
    for seg_id in claim.get("segment_ids", []):
        seg = db.claim_segments[seg_id]
        ticket = db.tickets[seg["ticket_id"]]
        flight = db.flights[seg["flight_id"]]
        compute_segment_eligibility(seg, claim, policy, ticket, flight)
