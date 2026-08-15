"""Rejection tolerance cascade, conditional sibling cancellation, void
reversal, and the standard vs attested credit variants."""
import pytest

from test_helpers import (
    TEST_USERS,
    accept_shipment,
    book_dispatch_deliver,
    book_shipment,
    dispatch_and_deliver,
    dispatch_shipment,
    get_agreement,
    get_commitment,
    get_generator,
    get_shipment,
    setup_dispatch_ready_chain,
    validate_paginated,
    validate_success,
)

BROKER = TEST_USERS["broker_ops_headers"]


def _setup_reject_cascade_chain(api):
    """Agreement committed 500; commitment committed 100 (tolerance 20.0 t).
    S1 20.5 t DISPATCHED+DELIVERED wet; S2 10 t BOOKED; S3 5 t DISPATCHED."""
    chain = setup_dispatch_ready_chain(
        committed_agreement_tons=500, committed_commitment_tons=100,
    )
    s1 = book_shipment(chain, gross_tons=20.5, pickup_date="2026-08-05")
    s2 = book_shipment(chain, gross_tons=10, pickup_date="2026-08-06")
    s3 = book_shipment(chain, gross_tons=5, pickup_date="2026-08-07")
    dispatch_shipment(chain, s3["id"])
    dispatch_and_deliver(chain, s1["id"], destination_moisture_pct=13.0)
    return chain, s1, s2, s3


def test_rejection_auto_suspends_commitment_over_tolerance(api):
    """PRD §3.6: "The tolerance threshold itself is the commitment's
    `committed_monthly_tons` multiplied by 0.20, rounded half-up to three
    decimal places; if the commitment was `ACTIVE` and, after the current
    rejection has been added, `cumulative_rejected_tons` strictly exceeds that
    threshold, the commitment automatically transitions from `ACTIVE` to
    `SUSPENDED`."
    PRD §3.6: "The rejection then feeds the commitment's tolerance posture:
    `cumulative_rejected_tons` increases by the shipment's `gross_tons` and the
    commitment's `version` advances by one."

    Design: Difficulty/transitive_cascade/reject_cascade_to_commitment_suspension_to_booked_cancellations
    """
    chain, s1, _, _ = _setup_reject_cascade_chain(api)

    rejected = validate_success(
        api.reject_shipment(s1["id"], {"reason": "too wet"}, chain["offtaker_headers"]),
        200,
    )
    assert rejected["status"] == "REJECTED"

    commitment_after = get_commitment(chain["commitment"]["id"])
    assert commitment_after["cumulative_rejected_tons"] == pytest.approx(20.5)
    # Tolerance is 100 x 0.20 = 20.0; 20.5 strictly exceeds it.
    assert commitment_after["status"] == "SUSPENDED", (
        "cumulative_rejected_tons 20.5 > 20.0 tolerance must auto-suspend the commitment"
    )


def test_auto_suspension_cancels_only_booked_siblings(api):
    """PRD §3.6: "The auto-suspension is conditional and deliberately scoped. It
    cancels every shipment of that commitment still in `BOOKED` status, moving
    each to `CANCELLED`; shipments already `DISPATCHED` or further along are
    not affected. Each such auto-cancelled shipment releases its quota: its
    supply agreement's `booked_month_to_date_tons` decreases by that shipment's
    `gross_tons` (after rollover) and the agreement's `version` advances by
    one."

    Design: Difficulty/transitive_cascade/reject_cascade_to_commitment_suspension_to_booked_cancellations
    """
    chain, s1, s2, s3 = _setup_reject_cascade_chain(api)

    validate_success(
        api.reject_shipment(s1["id"], {"reason": "too wet"}, chain["offtaker_headers"]),
        200,
    )

    s2_after = get_shipment(s2["id"])
    assert s2_after["status"] == "CANCELLED", (
        "a BOOKED sibling shipment is auto-cancelled by the suspension cascade"
    )
    s3_after = get_shipment(s3["id"])
    assert s3_after["status"] == "DISPATCHED", (
        "a DISPATCHED sibling is deliberately not affected by the cascade"
    )

    agreement_after = get_agreement(chain["agreement"]["id"])
    # 35.5 t booked (20.5 + 10 + 5) minus S2's released 10 t.
    assert agreement_after["booked_month_to_date_tons"] == pytest.approx(25.5)


def test_reject_exactly_at_tolerance_keeps_commitment_active(api):
    """PRD §3.6: "The tolerance threshold itself is the commitment's
    `committed_monthly_tons` multiplied by 0.20, rounded half-up to three
    decimal places; if the commitment was `ACTIVE` and, after the current
    rejection has been added, `cumulative_rejected_tons` strictly exceeds that
    threshold, the commitment automatically transitions from `ACTIVE` to
    `SUSPENDED`. A cumulative total exactly equal to the threshold does not
    suspend."

    Design: Corner/state_machines/reject_exactly_at_tolerance_keeps_commitment_active
    """
    chain = setup_dispatch_ready_chain(
        committed_agreement_tons=500, committed_commitment_tons=100,
    )
    delivered = book_dispatch_deliver(chain, gross_tons=20,
                                      destination_moisture_pct=13.0)

    rejected = validate_success(
        api.reject_shipment(delivered["id"], {"reason": "too wet"}, chain["offtaker_headers"]),
        200,
    )
    assert rejected["status"] == "REJECTED"

    commitment_after = get_commitment(chain["commitment"]["id"])
    assert commitment_after["cumulative_rejected_tons"] == pytest.approx(20.0)
    # 20.0 exactly equals the 100 x 0.20 tolerance: strictly-greater does not fire.
    assert commitment_after["status"] == "ACTIVE", (
        "a cumulative total exactly equal to the threshold does not suspend"
    )


def _setup_two_accepted_then_void(api):
    """S1 60 t and S2 45 t both ACCEPTED (total_credits 105.0, SILVER); S2 is
    then voided. Returns (chain, s1, s2, voided_s2)."""
    chain = setup_dispatch_ready_chain(
        committed_agreement_tons=500, committed_commitment_tons=500,
    )
    s1 = book_dispatch_deliver(chain, gross_tons=60)
    accept_shipment(chain, s1["id"])
    s2 = book_dispatch_deliver(chain, gross_tons=45, pickup_date="2026-08-06")
    accept_shipment(chain, s2["id"])

    voided = validate_success(
        api.void_shipment(s2["id"], {"reason": "audit failure"}, BROKER), 200
    )
    return chain, s1, s2, voided


def test_void_posts_exact_reversal_and_restores_tier(api):
    """PRD §3.6: "Voiding unwinds the full acceptance cascade: a sustainability
    credit entry of `entry_type` `REVERSAL` is posted for the same generator
    and shipment, in the current logical `period`, with `tons_credited` equal
    to the shipment's `net_billable_tons` and `credits` exactly equal to the
    original `ACCRUAL` credits of that shipment; the generator's
    `total_credits` is recomputed as the accrual sum minus the reversal sum,
    and `credit_tier` is re-derived against the same thresholds, which may now
    downgrade the tier."

    Design: Difficulty/compensating_invariant/accrual_void_reversal_conserves_credit_balance
    """
    chain, _, s2, voided = _setup_two_accepted_then_void(api)
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "audit failure"

    entries, meta = validate_paginated(api.list_shipment_credit_entries(s2["id"], BROKER))
    assert meta["total_count"] == 2, "voided shipment carries ACCRUAL + REVERSAL entries"
    by_type = {e["entry_type"]: e for e in entries}
    accrual = by_type["ACCRUAL"]
    reversal = by_type["REVERSAL"]
    assert accrual["credits"] == pytest.approx(45.0)
    assert reversal["credits"] == pytest.approx(45.0), (
        "REVERSAL credits must exactly equal the original ACCRUAL credits"
    )
    assert reversal["tons_credited"] == pytest.approx(45.0)
    assert reversal["period"] == "2026-08"

    generator_after = get_generator(chain["generator"]["id"])
    assert generator_after["total_credits"] == pytest.approx(60.0), (
        "total_credits returns to the pre-acceptance value: 105.0 - 45.0"
    )
    assert generator_after["credit_tier"] == "STANDARD", (
        "the tier is re-derived downward once the balance falls below 100"
    )


def test_void_unwinds_agreement_and_commitment_counters(api):
    """PRD §3.6: "The agreement's `delivered_month_to_date_tons` decreases by
    `net_billable_tons` after rollover (floored at zero) with
    `fulfillment_status` recomputed and `version` advanced, and the
    commitment's `accepted_month_to_date_tons` decreases the same way, floored
    at zero, with its `version` advanced."

    Design: Difficulty/compensating_invariant/accrual_void_reversal_conserves_credit_balance
    """
    chain, _, _, _ = _setup_two_accepted_then_void(api)

    agreement_after = get_agreement(chain["agreement"]["id"])
    assert agreement_after["delivered_month_to_date_tons"] == pytest.approx(60.0), (
        "the void unwinds the 45 t acceptance, leaving the 60 t first delivery"
    )
    commitment_after = get_commitment(chain["commitment"]["id"])
    assert commitment_after["accepted_month_to_date_tons"] == pytest.approx(60.0)


def test_standard_credits_net_voided_via_reversal(api):
    """PRD §3.8: "The **standard** variant is the ledger view: for a given
    period, `standard_credits` is the signed sum of that period's entries —
    accrual amounts added, reversal amounts subtracted — so a voided shipment
    offsets its own accrual."

    Design: Difficulty/dual_variant_calc/standard_vs_attested_credit_variants_diverge
    """
    chain, _, _, _ = _setup_two_accepted_then_void(api)

    resp = api.get_credit_summary(chain["generator"]["id"], BROKER)
    summary = validate_success(resp, 200)
    # 60.0 + 45.0 - 45.0 = 60.0 for period 2026-08 (default = current logical month).
    assert summary["standard_credits"] == pytest.approx(60.0), (
        "the standard ledger variant offsets the voided 45 t via its REVERSAL row"
    )

    generator_after = get_generator(chain["generator"]["id"])
    assert generator_after["total_credits"] == pytest.approx(60.0)


def test_attested_credits_exclude_voided_shipments(api):
    """PRD §3.8: "The **attested** variant, produced for regulatory reporting,
    is instead computed directly from shipments: it considers the generator's
    loads that remain in `ACCEPTED` status and were accepted during the period
    — voided shipments are excluded entirely rather than offset — sums their
    `net_billable_tons` (reported as `total_net_tons`), multiplies the total by
    0.92, and rounds half-up to two decimal places to produce
    `attested_credits`."

    Design: Difficulty/dual_variant_calc/standard_vs_attested_credit_variants_diverge
    """
    chain, _, _, _ = _setup_two_accepted_then_void(api)

    resp = api.get_credit_summary(chain["generator"]["id"], BROKER)
    summary = validate_success(resp, 200)
    # Only the still-ACCEPTED 60 t shipment counts: 60.0 x 0.92 = 55.2.
    assert summary["total_net_tons"] == pytest.approx(60.0), (
        "the attested basis excludes the voided 45 t entirely"
    )
    assert summary["attested_credits"] == pytest.approx(55.2), (
        "attested variant applies the 0.92 factor to shipments still ACCEPTED"
    )
    # Same diversion history, different variant: attested is strictly lower here.
    assert summary["standard_credits"] == pytest.approx(60.0)
