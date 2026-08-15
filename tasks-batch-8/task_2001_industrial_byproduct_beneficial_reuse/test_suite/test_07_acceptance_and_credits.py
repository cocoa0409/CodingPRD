"""Acceptance quality gate, immediate consistency of the accept response, and
the acceptance -> credit entry -> generator tier cascade."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_shipment,
    assert_credit_entry,
    book_dispatch_deliver,
    get_agreement,
    get_commitment,
    get_generator,
    get_shipment,
    setup_dispatch_ready_chain,
    validate_error,
    validate_paginated,
    validate_success,
)

BROKER = TEST_USERS["broker_ops_headers"]


def test_accept_at_moisture_boundary_inclusive(api):
    """PRD §3.5: "Accepting a load is declared only from `DELIVERED` (else
    `ERR_INVALID_STATE`) and first enforces the commitment's quality
    specification: the destination moisture reading must not exceed the
    commitment's `max_moisture_pct` by more than 2.0 percentage points, and the
    destination arsenic reading must not exceed `max_arsenic_ppm` at all; a
    breach of either limit is rejected with `ERR_QUALITY_OUT_OF_SPEC` and
    leaves the shipment in `DELIVERED`."

    Design: Difficulty/boundary_precision_check/accept_at_moisture_tolerance_boundary
    """
    chain = setup_dispatch_ready_chain(
        committed_agreement_tons=500, committed_commitment_tons=500,
        revenue_share_pct_to_generator=0.5, freight_share_pct_to_generator=0.25,
        index_price_cents_per_ton=400,
    )
    delivered = book_dispatch_deliver(
        chain, gross_tons=50, destination_moisture_pct=12.0,
    )

    # 12.0 is exactly max_moisture_pct (10.0) + 2.0: the inclusive boundary.
    accepted = accept_shipment(chain, delivered["id"])
    assert accepted["status"] == "ACCEPTED"
    assert accepted["moisture_deduction_pct"] == pytest.approx(2.0)
    assert accepted["net_billable_tons"] == pytest.approx(49.0)  # 50 x 0.98
    assert accepted["final_gross_revenue_cents"] == 19600  # 49.0 x 400
    assert accepted["final_generator_share_cents"] == 9800
    assert accepted["final_broker_share_cents"] == 9800


def test_accept_above_moisture_boundary_rejected(api):
    """PRD §3.5: "the destination moisture reading must not exceed the
    commitment's `max_moisture_pct` by more than 2.0 percentage points, and the
    destination arsenic reading must not exceed `max_arsenic_ppm` at all; a
    breach of either limit is rejected with `ERR_QUALITY_OUT_OF_SPEC` and
    leaves the shipment in `DELIVERED`."

    Design: Difficulty/boundary_precision_check/accept_at_moisture_tolerance_boundary
    """
    chain = setup_dispatch_ready_chain(
        committed_agreement_tons=500, committed_commitment_tons=500,
        revenue_share_pct_to_generator=0.5, freight_share_pct_to_generator=0.25,
        index_price_cents_per_ton=400,
    )
    delivered = book_dispatch_deliver(
        chain, gross_tons=10, destination_moisture_pct=12.1,
    )

    # 12.1 exceeds the 12.0 boundary.
    resp = api.accept_shipment(delivered["id"], chain["offtaker_headers"])
    validate_error(resp, ApiErrorId.ERR_QUALITY_OUT_OF_SPEC)

    shipment_after = get_shipment(delivered["id"])
    assert shipment_after["status"] == "DELIVERED", (
        "an out-of-spec accept leaves the shipment in DELIVERED"
    )


def test_accept_response_contains_final_settlement_immediately(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field."
    PRD §3.5: "A passing load transitions to `ACCEPTED` and runs the final
    settlement in a pinned evaluation order."

    Design: Corner/consistency_model/accept_response_contains_final_settlement_immediately
    """
    chain = setup_dispatch_ready_chain(committed_agreement_tons=100,
                                       committed_commitment_tons=100)
    delivered = book_dispatch_deliver(chain, gross_tons=10)

    resp = api.accept_shipment(delivered["id"], chain["offtaker_headers"])
    data = validate_success(resp, 200)
    # The accept response body itself carries the completed final settlement.
    assert data["status"] == "ACCEPTED"
    assert data["net_billable_tons"] == pytest.approx(10.0)
    assert data["final_gross_revenue_cents"] == 3000  # 10.0 t x 300
    assert data["final_generator_share_cents"] == 1800  # 3000 x 0.6
    assert data["final_broker_share_cents"] == 1200  # residual


def test_accept_posts_accrual_credit_entry(api):
    """PRD §3.5: "A sustainability credit entry is posted with `entry_type`
    `ACCRUAL`, crediting the agreement's generator, referencing this shipment,
    posted to the current logical month as its `period`, with `tons_credited`
    equal to `net_billable_tons` and `credits` equal to those net billable tons
    multiplied by 1.0 credit per ton, rounded half-up to two decimal places."

    Design: Difficulty/transitive_cascade/accept_cascade_shipment_to_credit_entry_to_generator_tier
    """
    chain = setup_dispatch_ready_chain(committed_agreement_tons=500,
                                       committed_commitment_tons=500)
    delivered1 = book_dispatch_deliver(chain, gross_tons=60)
    accept_shipment(chain, delivered1["id"])

    delivered2 = book_dispatch_deliver(chain, gross_tons=45, pickup_date="2026-08-06")
    accepted2 = accept_shipment(chain, delivered2["id"])
    assert accepted2["status"] == "ACCEPTED"
    assert accepted2["net_billable_tons"] == pytest.approx(45.0)

    entries, meta = validate_paginated(
        api.list_shipment_credit_entries(accepted2["id"], BROKER)
    )
    assert meta["total_count"] == 1 and len(entries) == 1
    entry = entries[0]
    assert_credit_entry(entry)
    assert entry["entry_type"] == "ACCRUAL"
    assert entry["credits"] == pytest.approx(45.0)
    assert entry["tons_credited"] == pytest.approx(45.0)
    assert entry["period"] == "2026-08", "entry posts to the current logical month"
    assert entry["generator_id"] == chain["generator"]["id"]
    assert entry["shipment_id"] == accepted2["id"]


def test_accept_cascade_recomputes_generator_tier_and_counters(api):
    """PRD §3.5: "Posting that entry recomputes the generator's `total_credits`
    — the sum of `ACCRUAL` credits minus the sum of `REVERSAL` credits across
    all its entries — and re-derives `credit_tier`: `GOLD` when the balance
    reaches at least 250, otherwise `SILVER` when it reaches at least 100,
    otherwise `STANDARD`, with inclusive boundaries so that exactly 100.00
    credits already yields `SILVER`."
    PRD §3.5: "The agreement's `delivered_month_to_date_tons` increases by
    `net_billable_tons` (after rollover), its `fulfillment_status` is
    recomputed, and its `version` advances by one; the commitment's
    `accepted_month_to_date_tons` increases by the same tonnage (after
    rollover) and its `version` advances by one."

    Design: Difficulty/transitive_cascade/accept_cascade_shipment_to_credit_entry_to_generator_tier
    """
    chain = setup_dispatch_ready_chain(committed_agreement_tons=500,
                                       committed_commitment_tons=500)
    # First acceptance: 60 t -> total_credits 60.0, tier stays STANDARD.
    first = book_dispatch_deliver(chain, gross_tons=60)
    accept_shipment(chain, first["id"])
    generator_mid = get_generator(chain["generator"]["id"])
    assert generator_mid["total_credits"] == pytest.approx(60.0)
    assert generator_mid["credit_tier"] == "STANDARD"

    # Second acceptance: 45 t -> total_credits 105.0, crossing the SILVER threshold.
    second = book_dispatch_deliver(chain, gross_tons=45, pickup_date="2026-08-06")
    accept_shipment(chain, second["id"])

    generator_after = get_generator(chain["generator"]["id"])
    assert generator_after["total_credits"] == pytest.approx(105.0)
    assert generator_after["credit_tier"] == "SILVER", (
        "105.0 credits crosses the inclusive >= 100 SILVER threshold"
    )

    agreement_after = get_agreement(chain["agreement"]["id"])
    assert agreement_after["delivered_month_to_date_tons"] == pytest.approx(105.0)
    commitment_after = get_commitment(chain["commitment"]["id"])
    assert commitment_after["accepted_month_to_date_tons"] == pytest.approx(105.0)


def test_credit_tier_gold_at_exact_threshold(api):
    """PRD §3.5: "re-derives `credit_tier`: `GOLD` when the balance reaches at
    least 250, otherwise `SILVER` when it reaches at least 100, otherwise
    `STANDARD`, with inclusive boundaries so that exactly 100.00 credits
    already yields `SILVER`."

    Design: Corner/calculations/credit_tier_gold_at_exact_threshold
    """
    chain = setup_dispatch_ready_chain(committed_agreement_tons=1000,
                                       committed_commitment_tons=1000)
    delivered = book_dispatch_deliver(chain, gross_tons=250)
    accept_shipment(chain, delivered["id"])

    generator_after = get_generator(chain["generator"]["id"])
    assert generator_after["total_credits"] == pytest.approx(250.0)
    assert generator_after["credit_tier"] == "GOLD", (
        "exactly 250.0 credits reaches the inclusive >= 250 GOLD threshold"
    )


def test_fulfillment_status_met_at_exact_committed_tonnage(api):
    """PRD §3.3: "As deliveries accumulate, `fulfillment_status` flips to `MET`
    whenever `delivered_month_to_date_tons` reaches at least
    `committed_monthly_tons` within the current counter month, and returns to
    `UNMET` if the delivered total falls back below the commitment."

    Design: Corner/calculations/fulfillment_status_met_at_exact_committed_tonnage
    """
    chain = setup_dispatch_ready_chain(committed_agreement_tons=100,
                                       committed_commitment_tons=500)
    delivered = book_dispatch_deliver(chain, gross_tons=100)
    accept_shipment(chain, delivered["id"])

    agreement_after = get_agreement(chain["agreement"]["id"])
    assert agreement_after["delivered_month_to_date_tons"] == pytest.approx(100.0)
    assert agreement_after["fulfillment_status"] == "MET", (
        "delivered exactly equal to committed_monthly_tons is MET (at least)"
    )
