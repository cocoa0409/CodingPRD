"""Freight tier pricing, market price selection, provisional vs final
settlement, and pinned rounding order."""
import pytest

from test_helpers import (
    BROKER_OPS_USER_ID,
    TEST_USERS,
    assert_freight_split_invariants,
    assert_price_index_entry,
    book_dispatch_deliver,
    book_shipment,
    create_price_index_payload,
    dispatch_and_deliver,
    publish_price_index,
    setup_booking_ready_chain,
    setup_dispatch_ready_chain,
    validate_success,
    accept_shipment,
)

BROKER = TEST_USERS["broker_ops_headers"]


def test_price_index_entry_is_append_only(api):
    """PRD §2.5: "Two resources are append-only ledger records and carry only
    `id` and `created_at`: the market price index entry and the sustainability
    credit entry. Both `updated_at` and `version` are absent from these two
    resources — they are never modified after creation."
    PRD §3.8: "the publisher's `X-User-ID` is stamped as
    `published_by_user_id`."

    Design: Corner/entities/price_index_entry_immutable_common_fields_false
    """
    resp = api.create_price_index_entry(create_price_index_payload(), BROKER)
    data = validate_success(resp, 201)
    assert_price_index_entry(data)
    assert (
        data["published_by_user_id"] == BROKER_OPS_USER_ID
    ), "publisher X-User-ID must be stamped on the entry"


def test_freight_short_haul_tier1_only_with_base_fee(api):
    """PRD §3.4: "The total freight charge, stored as `freight_total_cents`, is
    the sum of a flat base fee of 15,000 cents and a tiered distance charge
    over the one-way haul: the first 100 miles are billed at 450 cents per
    mile, any further miles up to a cumulative 300 miles are billed at 320
    cents per mile, and every mile beyond 300 is billed at 210 cents per mile."
    PRD §3.4: "From that total, the generator absorbs
    `generator_freight_share_cents`: the freight total multiplied by the
    agreement's `freight_share_pct_to_generator`, rounded half-up to whole
    cents, and then capped at 60,000 cents"

    Design: Corner/calculations/freight_short_haul_tier1_only_with_base_fee
    """
    chain = setup_booking_ready_chain(
        committed_agreement_tons=100, committed_commitment_tons=100,
        revenue_share_pct_to_generator=0.5, freight_share_pct_to_generator=0.5,
    )
    shipment = book_shipment(chain, gross_tons=10, distance_miles=80)

    # 15000 + 80 x 450 = 51000; 50% share = 25500, below the cap.
    assert shipment["freight_total_cents"] == 51000
    assert shipment["generator_freight_share_cents"] == 25500
    assert shipment["broker_freight_share_cents"] == 25500
    assert_freight_split_invariants(shipment)


def test_freight_share_capped_at_max_on_long_haul(api):
    """PRD §3.4: "The total freight charge, stored as `freight_total_cents`, is
    the sum of a flat base fee of 15,000 cents and a tiered distance charge
    over the one-way haul: the first 100 miles are billed at 450 cents per
    mile, any further miles up to a cumulative 300 miles are billed at 320
    cents per mile, and every mile beyond 300 is billed at 210 cents per mile."
    PRD §3.4: "when the rounded product exceeds the cap, the generator absorbs
    exactly 60,000 cents. The broker absorbs the remainder, recorded as
    `broker_freight_share_cents`, which is always the total minus the
    generator's capped share."

    Design: Difficulty/combinatorial_formula/freight_tiered_marginal_rates_with_share_cap
    """
    chain = setup_booking_ready_chain(
        committed_agreement_tons=1000, committed_commitment_tons=3000,
        revenue_share_pct_to_generator=0.5, freight_share_pct_to_generator=0.5,
    )
    shipment = book_shipment(chain, gross_tons=10, distance_miles=600)

    # 15000 + 100x450 + 200x320 + 300x210 = 187000; 50% = 93500 -> capped 60000.
    assert shipment["freight_total_cents"] == 187000
    assert shipment["generator_freight_share_cents"] == 60000, (
        "the generator share is capped at 60,000 cents"
    )
    assert shipment["broker_freight_share_cents"] == 127000
    assert_freight_split_invariants(shipment)


def test_freight_tier_straddle_below_cap(api):
    """PRD §3.4: "The total freight charge, stored as `freight_total_cents`, is
    the sum of a flat base fee of 15,000 cents and a tiered distance charge
    over the one-way haul: the first 100 miles are billed at 450 cents per
    mile, any further miles up to a cumulative 300 miles are billed at 320
    cents per mile, and every mile beyond 300 is billed at 210 cents per mile."
    PRD §3.4: "From that total, the generator absorbs
    `generator_freight_share_cents`: the freight total multiplied by the
    agreement's `freight_share_pct_to_generator`, rounded half-up to whole
    cents, and then capped at 60,000 cents"

    Design: Difficulty/combinatorial_formula/freight_tiered_marginal_rates_with_share_cap
    """
    chain = setup_booking_ready_chain(
        committed_agreement_tons=1000, committed_commitment_tons=3000,
        revenue_share_pct_to_generator=0.5, freight_share_pct_to_generator=0.3,
    )
    shipment = book_shipment(chain, gross_tons=10, distance_miles=350)

    # 15000 + 100x450 + 200x320 + 50x210 = 134500; 30% = 40350, below the cap.
    assert shipment["freight_total_cents"] == 134500
    assert shipment["generator_freight_share_cents"] == 40350
    assert shipment["broker_freight_share_cents"] == 94150
    assert_freight_split_invariants(shipment)


def test_price_index_selector_latest_effective_wins(api):
    """PRD §3.8: "The candidate set is every index entry whose `material_type`
    matches the stream's material and whose `region_code` equals the
    commitment's `destination_state_code`, restricted to entries whose
    `effective_from` falls on or before the pricing date; dates compare at day
    granularity against the logical clock. The winner is the candidate with the
    latest `effective_from`, with ties broken in favor of the most recently
    created entry."
    PRD §3.4: "`provisional_settlement_cents` is the `gross_tons` multiplied by
    `price_at_pickup_cents_per_ton`, rounded half-up to whole cents, using
    gross tonnage with no moisture adjustment."

    Design: Corner/calculations/price_index_selector_latest_effective_wins
    """
    chain = setup_booking_ready_chain(committed_agreement_tons=100,
                                      committed_commitment_tons=100)
    # Second entry published before booking; effective 2026-07-15, still on or
    # before the 2026-08-05 pickup date.
    publish_price_index(effective_from="2026-07-15", price_cents_per_ton=350)

    shipment = book_shipment(chain, gross_tons=10, pickup_date="2026-08-05")
    assert shipment["price_at_pickup_cents_per_ton"] == 350, (
        "the entry with the latest effective_from on or before pickup wins"
    )
    assert shipment["provisional_settlement_cents"] == 3500  # 10 t x 350


def test_acceptance_price_falls_back_to_pickup_price_when_gap(api):
    """PRD §3.5: "Third, `price_at_acceptance_cents_per_ton` is selected from
    the market index for the stream's material and destination state as of the
    acceptance date, exactly as at booking — except that when no index entry is
    effective on that date, the acceptance price falls back to
    `price_at_pickup_cents_per_ton` instead of failing."
    PRD §3.8: "at acceptance, an empty set instead falls back to the shipment's
    `price_at_pickup_cents_per_ton`, so settlement can never stall on a
    publishing gap."

    Design: Corner/calculations/acceptance_price_falls_back_to_pickup_price_when_gap
    """
    # Sole index entry becomes effective 2026-08-03: effective at the 2026-08-05
    # pickup, but NOT at the 2026-08-01 acceptance (default logical clock).
    chain = setup_dispatch_ready_chain(
        committed_agreement_tons=100, committed_commitment_tons=100,
        index_price_cents_per_ton=500, index_effective_from="2026-08-03",
    )
    shipment = book_shipment(chain, gross_tons=10, pickup_date="2026-08-05")
    assert shipment["price_at_pickup_cents_per_ton"] == 500

    dispatch_and_deliver(chain, shipment["id"])
    accepted = accept_shipment(chain, shipment["id"])
    assert accepted["price_at_acceptance_cents_per_ton"] == 500, (
        "no index entry is effective on the 2026-08-01 acceptance date, so the "
        "acceptance price falls back to the pickup price"
    )
    assert accepted["net_billable_tons"] == pytest.approx(10.0)
    assert accepted["final_gross_revenue_cents"] == 5000  # 10.0 t x 500


def test_provisional_settlement_pinned_at_booking(api):
    """PRD §3.4: "Booking also records a provisional settlement estimate:
    `provisional_settlement_cents` is the `gross_tons` multiplied by
    `price_at_pickup_cents_per_ton`, rounded half-up to whole cents, using
    gross tonnage with no moisture adjustment."
    PRD §3.4: "The market price is pinned as `price_at_pickup_cents_per_ton`,
    selected per the index rules of §3.8 for the stream's `material_type` and
    the commitment's `destination_state_code` as of `pickup_date`."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_settlement_diverge_on_index_move
    """
    chain = setup_dispatch_ready_chain(
        committed_agreement_tons=100, committed_commitment_tons=100,
        revenue_share_pct_to_generator=0.6, freight_share_pct_to_generator=0.25,
    )
    shipment = book_shipment(chain, gross_tons=20, distance_miles=50,
                             pickup_date="2026-08-05")

    assert shipment["price_at_pickup_cents_per_ton"] == 300
    assert shipment["provisional_settlement_cents"] == 6000  # 20 t x 300
    assert shipment["final_gross_revenue_cents"] is None, (
        "acceptance-time financial fields remain null until acceptance"
    )


def test_final_settlement_reprices_at_acceptance_date_index(api):
    """PRD §3.5: "Because the final variant prices moisture-adjusted tonnage at
    the acceptance-date index while the provisional variant priced gross
    tonnage at the pickup-date index, the two figures for the same load diverge
    whenever the index moved or any moisture deduction applied."
    PRD §3.5: "Fifth, `final_generator_share_cents` is the gross revenue
    multiplied by the agreement's `revenue_share_pct_to_generator`, rounded
    half-up to whole cents. Sixth, `final_broker_share_cents` is the residual,
    gross revenue minus the generator share, so all rounding drift lands on the
    broker's side."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_settlement_diverge_on_index_move
    """
    chain = setup_dispatch_ready_chain(
        committed_agreement_tons=100, committed_commitment_tons=100,
        revenue_share_pct_to_generator=0.6, freight_share_pct_to_generator=0.25,
    )
    shipment = book_shipment(chain, gross_tons=20, distance_miles=50,
                             pickup_date="2026-08-05")
    assert shipment["provisional_settlement_cents"] == 6000

    # Index moves after booking: 350 effective 2026-07-15, effective on the
    # 2026-08-01 acceptance date.
    publish_price_index(effective_from="2026-07-15", price_cents_per_ton=350)
    dispatch_and_deliver(chain, shipment["id"])
    accepted = accept_shipment(chain, shipment["id"])

    assert accepted["price_at_acceptance_cents_per_ton"] == 350
    assert accepted["net_billable_tons"] == pytest.approx(20.0)  # no moisture deduction
    assert accepted["final_gross_revenue_cents"] == 7000  # 20.0 t x 350
    assert accepted["final_generator_share_cents"] == 4200  # 7000 x 0.6
    assert accepted["final_broker_share_cents"] == 2800  # residual
    assert accepted["provisional_settlement_cents"] == 6000, (
        "provisional stays pinned at the pickup-date economics"
    )
    assert accepted["provisional_settlement_cents"] != accepted["final_gross_revenue_cents"], (
        "the two variants diverge because the index moved between pickup and acceptance"
    )


def test_net_tons_rounded_before_money_multiply(api):
    """PRD §3.5: "First, `moisture_deduction_pct` is the amount by which
    `destination_moisture_pct` exceeds the commitment's `max_moisture_pct`, or
    zero when the reading is at or below the limit. Second, `net_billable_tons`
    is the shipment's `gross_tons` multiplied by one minus that deduction
    percentage divided by one hundred, rounded half-up to three decimal
    places." and "Fourth, `final_gross_revenue_cents` is the rounded
    `net_billable_tons` — never the unrounded tonnage — multiplied by the
    acceptance price, rounded half-up to whole cents."

    Design: Difficulty/combinatorial_formula/settlement_rounding_order_pinned
    """
    chain = setup_dispatch_ready_chain(
        committed_agreement_tons=500, committed_commitment_tons=500,
        revenue_share_pct_to_generator=0.475, freight_share_pct_to_generator=0.1,
        index_price_cents_per_ton=999,
    )
    delivered = book_dispatch_deliver(
        chain, gross_tons=17.75, distance_miles=120, destination_moisture_pct=11.9,
    )
    accepted = accept_shipment(chain, delivered["id"])

    # deduction 1.9 -> 17.75 x 0.981 = 17.41275 -> round 3dp -> 17.413;
    # 17.413 x 999 = 17395.587 -> 17396 (multiplying unrounded tons would give 17395).
    assert accepted["moisture_deduction_pct"] == pytest.approx(1.9)
    assert accepted["net_billable_tons"] == pytest.approx(17.413)
    assert accepted["final_gross_revenue_cents"] == 17396, (
        "money must be computed from the 3dp-rounded tonnage, not the unrounded value"
    )


def test_settlement_shares_freight_and_payout_derived(api):
    """PRD §3.5: "Fifth, `final_generator_share_cents` is the gross revenue
    multiplied by the agreement's `revenue_share_pct_to_generator`, rounded
    half-up to whole cents. Sixth, `final_broker_share_cents` is the residual,
    gross revenue minus the generator share, so all rounding drift lands on the
    broker's side. Seventh, `generator_net_payout_cents` is the generator's
    revenue share minus the `generator_freight_share_cents` fixed at booking."
    PRD §3.4: "`provisional_settlement_cents` is the `gross_tons` multiplied by
    `price_at_pickup_cents_per_ton`, rounded half-up to whole cents, using
    gross tonnage with no moisture adjustment."

    Design: Difficulty/combinatorial_formula/settlement_rounding_order_pinned
    """
    chain = setup_dispatch_ready_chain(
        committed_agreement_tons=500, committed_commitment_tons=500,
        revenue_share_pct_to_generator=0.475, freight_share_pct_to_generator=0.1,
        index_price_cents_per_ton=999,
    )
    shipment = book_shipment(chain, gross_tons=17.75, distance_miles=120)

    # Booking-time economics: freight 15000 + 100x450 + 20x320 = 66400,
    # generator share 66400 x 0.1 = 6640; provisional round(17.75 x 999) = 17732.
    assert shipment["freight_total_cents"] == 66400
    assert shipment["generator_freight_share_cents"] == 6640
    assert shipment["provisional_settlement_cents"] == 17732

    dispatch_and_deliver(chain, shipment["id"], destination_moisture_pct=11.9)
    accepted = accept_shipment(chain, shipment["id"])

    assert accepted["final_gross_revenue_cents"] == 17396
    assert accepted["final_generator_share_cents"] == 8263  # round(17396 x 0.475)
    assert accepted["final_broker_share_cents"] == 9133  # 17396 - 8263 residual
    assert accepted["generator_net_payout_cents"] == 1623  # 8263 - 6640
