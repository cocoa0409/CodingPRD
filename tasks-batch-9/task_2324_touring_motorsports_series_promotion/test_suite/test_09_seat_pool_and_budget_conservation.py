"""Two conserved quantities and the operations that compensate for each other.

The first is seats. A tier's ``allotment`` is split across four buckets, and
three different aggregates move the summands: an order reserves, a sponsorship
activation holds, payment converts a reservation into a sale and a refund gives
the seats back. The second is money in the season's marketing ledger, where
releasing an allocation applies exactly the inverse deltas of committing it.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

import pytest

from test_helpers import (
    ApiClient,
    assert_marketing_budget_conserved,
    assert_seat_pool_conserved,
    create_sponsorship_activation,
    fetch_season,
    fetch_season_version,
    fetch_stop,
    fetch_tier,
    make_marketing_allocation_payload,
    make_refund_payload,
    place_ticket_order,
    stop_on_sale,
    validate_paginated,
    validate_success,
)

#: Provisioning that meets the requirement floors of a 100-seat stop.
_LEAN_PROVISIONING: Dict[str, int] = {
    "barrier_linear_feet": 1200,
    "catch_fence_height_ft": 6,
    "medical_als_staff_count": 1,
    "medical_bls_staff_count": 2,
    "ambulance_count": 1,
    "emergency_access_lanes": 1,
}


def _distribution(tier: Dict[str, Any]) -> Tuple[int, int, int, int]:
    """The four seat buckets of a tier, in reserve/sold/held/available order."""
    return (
        tier["reserved_seat_count"],
        tier["sold_seat_count"],
        tier["held_seat_count"],
        tier["available_seat_count"],
    )


@pytest.fixture
def on_sale_stop_with_hospitality_proposal(api: ApiClient) -> Dict[str, Any]:
    """An on-sale stop with one 100-seat tier and a proposed hospitality package.

    The single tier keeps the arithmetic legible: every seat in play belongs to
    ``UPPER``. The activation is only proposed, so its ten hospitality seats have
    not yet reached the tier's held bucket.
    """
    state = stop_on_sale(
        api,
        include_second_tier=False,
        tier_code="UPPER",
        price_cents=2500,
        allotment=100,
        channel="RADIO",
        amount_cents=500000,
        **_LEAN_PROVISIONING,
    )
    state.update(
        create_sponsorship_activation(
            api,
            state["stop_id"],
            hospitality_tier_id=state["tier_id"],
            company_name="Redline Fuel",
            sponsor_category="FUEL",
            contact_email="rep@redline.example",
            exclusive_category=False,
            fee_cents=300000,
            vehicle_branding_slots=0,
            signage_units=4,
            hospitality_seat_count=10,
        )
    )
    return state


class TestTicketTierSeatPoolIsConserved:
    """Seats move between buckets; the allotment itself never moves."""

    def test_reserving_holding_and_paying_move_seats_without_changing_the_total(
        self,
        api: ApiClient,
        on_sale_stop_with_hospitality_proposal: Dict[str, Any],
        ticketing_headers: Dict[str, str],
        promoter_headers: Dict[str, str],
    ) -> None:
        """PRD §2.5: "For any `TicketTier`, its `allotment` always equals `available_seat_count` plus `reserved_seat_count` plus `sold_seat_count` plus `held_seat_count`."

        PRD §2.5: "Reserving, paying, refunding, voiding and holding seats move quantity between those buckets; nothing adds to or subtracts from `allotment` itself."

        PRD §3.8: "The `hospitality_seat_count` is added to the named tier's `held_seat_count`, that tier's `available_seat_count` is recomputed and its `version` increments by one — which is another reason a box-office client's `expected_ticket_tier_version` can go stale without any order being written."

        PRD §3.7: "Payment stamps `paid_at` from the logical clock, moves `qty` from the tier's `reserved_seat_count` to its `sold_seat_count` while leaving `available_seat_count` unchanged, and adds four amounts and two counts to the stop's roll-ups: `line_subtotal_cents` minus `group_discount_cents` goes to `gross_ticket_revenue_cents`, `addon_subtotal_cents` minus `addon_discount_cents` goes to `addon_revenue_cents`, `facility_fee_cents` goes to `facility_fee_collected_cents`, `qty` goes to `tickets_sold_count`, and `pit_party_addon_qty` goes to `pit_party_sold_count`."

        Design: Difficulty/compensating_invariant/ticket_tier_seat_pool_is_conserved_across_reserve_hold_pay_and_refund
        """
        state = on_sale_stop_with_hospitality_proposal

        baseline = fetch_tier(api, state["tier_id"])
        assert baseline["allotment"] == 100
        assert _distribution(baseline) == (0, 0, 0, 100)
        assert_seat_pool_conserved(baseline)

        placed = place_ticket_order(
            api,
            state["stop_id"],
            state["tier_id"],
            qty=30,
            purchaser_name="Conservation Test",
            purchaser_email="conserve@example.com",
        )
        after_reserve = fetch_tier(api, state["tier_id"])
        assert _distribution(after_reserve) == (30, 0, 0, 70)
        assert_seat_pool_conserved(after_reserve)

        validate_success(
            api.activate_sponsorship_activation(
                state["activation_id"], headers=promoter_headers
            )
        )
        after_hold = fetch_tier(api, state["tier_id"])
        assert _distribution(after_hold) == (30, 0, 10, 60)
        assert_seat_pool_conserved(after_hold)
        held_stop = fetch_stop(api, state["stop_id"])
        assert held_stop["held_hospitality_seat_count"] == 10
        assert held_stop["sponsorship_committed_cents"] == 300000

        validate_success(
            api.pay_ticket_order(placed["order_id"], headers=ticketing_headers)
        )
        after_pay = fetch_tier(api, state["tier_id"])
        assert _distribution(after_pay) == (0, 30, 10, 60)
        assert after_pay["allotment"] == 100
        assert_seat_pool_conserved(after_pay)

        paid_stop = fetch_stop(api, state["stop_id"])
        assert paid_stop["tickets_sold_count"] == 30
        assert paid_stop["gross_ticket_revenue_cents"] == 75000
        assert paid_stop["facility_fee_collected_cents"] == 10500

    def test_the_refund_restores_the_distribution_and_leaves_the_money_record(
        self,
        api: ApiClient,
        on_sale_stop_with_hospitality_proposal: Dict[str, Any],
        ticketing_headers: Dict[str, str],
        promoter_headers: Dict[str, str],
    ) -> None:
        """PRD §3.7: "It stamps `refunded_at` from the logical clock, decrements the tier's `sold_seat_count` by `qty` and restores `available_seat_count` — the seat conservation invariant again — and subtracts exactly the same four money and count amounts from the stop's roll-ups that payment added."

        PRD §3.7: "The order's money is computed once, at creation, and frozen on the row; it is never recomputed afterwards, even if the tier's price or the stop's pit party price later changes."

        Design: Difficulty/compensating_invariant/ticket_tier_seat_pool_is_conserved_across_reserve_hold_pay_and_refund
        """
        state = on_sale_stop_with_hospitality_proposal

        placed = place_ticket_order(
            api,
            state["stop_id"],
            state["tier_id"],
            qty=30,
            purchaser_name="Conservation Test",
            purchaser_email="conserve@example.com",
        )
        validate_success(
            api.activate_sponsorship_activation(
                state["activation_id"], headers=promoter_headers
            )
        )
        validate_success(
            api.pay_ticket_order(placed["order_id"], headers=ticketing_headers)
        )

        refunded = validate_success(
            api.refund_ticket_order(
                placed["order_id"],
                make_refund_payload(reason="purchaser cancelled the block"),
                headers=ticketing_headers,
            )
        )
        assert refunded["status"] == "REFUNDED"
        assert refunded["refunded_at"] is not None
        # The counters reversed, but the frozen money on the row did not.
        assert refunded["total_cents"] == 85500

        after_refund = fetch_tier(api, state["tier_id"])
        assert _distribution(after_refund) == (0, 0, 10, 90)
        assert after_refund["allotment"] == 100
        assert_seat_pool_conserved(after_refund)

        stop = fetch_stop(api, state["stop_id"])
        assert stop["tickets_sold_count"] == 0
        assert stop["gross_ticket_revenue_cents"] == 0
        assert stop["facility_fee_collected_cents"] == 0
        # The sponsor's hold is untouched by the purchaser's refund.
        assert stop["held_hospitality_seat_count"] == 10


class TestSeasonMarketingBudgetIsConserved:
    """Committing and releasing marketing money are exact inverses."""

    def test_two_commits_split_the_budget_without_changing_the_total(
        self,
        api: ApiClient,
        confirmed_booking: Dict[str, Any],
        promoter_headers: Dict[str, str],
    ) -> None:
        """PRD §2.5: "The second is the season's marketing budget. For any `Season`, `total_marketing_budget_cents` always equals `marketing_allocated_cents` plus `marketing_unallocated_cents`."

        PRD §3.1: "Its ledger fields open at a known state: `marketing_allocated_cents` is 0 and `marketing_unallocated_cents` equals `total_marketing_budget_cents`."

        PRD §3.9: "The commit adds `amount_cents` to the season's `marketing_allocated_cents`, recomputes `marketing_unallocated_cents` as the total budget minus the allocated figure, increments the season's `version` by one, adds `amount_cents` to the stop's `marketing_spend_committed_cents`, and recomputes the stop's posture — which is how the first marketing dollar in a market lifts one of the conditions holding the stop at `RESTRICTED`."

        Design: Difficulty/compensating_invariant/season_marketing_budget_is_conserved_across_allocate_and_release
        """
        season_id = confirmed_booking["season_id"]
        stop_id = confirmed_booking["stop_id"]

        baseline = fetch_season(api, season_id)
        assert baseline["total_marketing_budget_cents"] == 40000000
        assert baseline["marketing_allocated_cents"] == 0
        assert baseline["marketing_unallocated_cents"] == 40000000
        assert_marketing_budget_conserved(baseline)

        radio = validate_success(
            api.create_marketing_allocation(
                stop_id,
                make_marketing_allocation_payload(
                    fetch_season_version(api, season_id),
                    channel="RADIO",
                    amount_cents=3200000,
                ),
                headers=promoter_headers,
            ),
            expected_status=201,
        )
        assert radio["state"] == "COMMITTED"
        assert radio["released_at"] is None

        after_radio = fetch_season(api, season_id)
        assert after_radio["marketing_allocated_cents"] == 3200000
        assert after_radio["marketing_unallocated_cents"] == 36800000
        assert after_radio["version"] > baseline["version"]
        assert_marketing_budget_conserved(after_radio)
        assert fetch_stop(api, stop_id)["marketing_spend_committed_cents"] == 3200000

        validate_success(
            api.create_marketing_allocation(
                stop_id,
                make_marketing_allocation_payload(
                    fetch_season_version(api, season_id),
                    channel="DIGITAL",
                    amount_cents=1200000,
                ),
                headers=promoter_headers,
            ),
            expected_status=201,
        )

        after_digital = fetch_season(api, season_id)
        assert after_digital["marketing_allocated_cents"] == 4400000
        assert after_digital["marketing_unallocated_cents"] == 35600000
        assert after_digital["version"] > after_radio["version"]
        assert_marketing_budget_conserved(after_digital)
        assert fetch_stop(api, stop_id)["marketing_spend_committed_cents"] == 4400000

    def test_releasing_one_allocation_applies_the_exact_inverse_deltas(
        self,
        api: ApiClient,
        confirmed_booking: Dict[str, Any],
        promoter_headers: Dict[str, str],
    ) -> None:
        """PRD §3.9: "Releasing an allocation moves it from `COMMITTED` to `RELEASED`, stamps `released_at` from the logical clock, and applies exactly the inverse deltas: the amount comes off `marketing_allocated_cents`, `marketing_unallocated_cents` is restored, the season's `version` increments by one, the stop's `marketing_spend_committed_cents` falls, and the posture is recomputed — which can pull a stop back to `RESTRICTED` if the release leaves the market with no committed spend at all, halting an `ON_SALE` stop."

        PRD §3.9: "The released row is returned so the conserved ledger is observable."

        Design: Difficulty/compensating_invariant/season_marketing_budget_is_conserved_across_allocate_and_release
        """
        season_id = confirmed_booking["season_id"]
        stop_id = confirmed_booking["stop_id"]

        radio = validate_success(
            api.create_marketing_allocation(
                stop_id,
                make_marketing_allocation_payload(
                    fetch_season_version(api, season_id),
                    channel="RADIO",
                    amount_cents=3200000,
                ),
                headers=promoter_headers,
            ),
            expected_status=201,
        )
        digital = validate_success(
            api.create_marketing_allocation(
                stop_id,
                make_marketing_allocation_payload(
                    fetch_season_version(api, season_id),
                    channel="DIGITAL",
                    amount_cents=1200000,
                ),
                headers=promoter_headers,
            ),
            expected_status=201,
        )
        before_release = fetch_season(api, season_id)

        released = validate_success(
            api.release_marketing_allocation(radio["id"], headers=promoter_headers)
        )
        assert released["state"] == "RELEASED"
        assert released["released_at"] is not None
        assert released["amount_cents"] == 3200000

        # The row survives its release and stays readable.
        reread = validate_success(
            api.get_marketing_allocation(radio["id"], headers=promoter_headers)
        )
        assert reread["state"] == "RELEASED"

        after_release = fetch_season(api, season_id)
        assert after_release["marketing_allocated_cents"] == 1200000
        assert after_release["marketing_unallocated_cents"] == 38800000
        assert after_release["version"] > before_release["version"]
        assert_marketing_budget_conserved(after_release)
        assert fetch_stop(api, stop_id)["marketing_spend_committed_cents"] == 1200000

        # The digital commitment is no part of the radio reversal.
        untouched = validate_success(
            api.get_marketing_allocation(digital["id"], headers=promoter_headers)
        )
        assert untouched["state"] == "COMMITTED"
        assert untouched["amount_cents"] == 1200000

    def test_the_released_channel_headroom_becomes_reusable_at_its_original_size(
        self,
        api: ApiClient,
        confirmed_booking: Dict[str, Any],
        promoter_headers: Dict[str, str],
    ) -> None:
        """PRD §3.9: "Allocations in `RELEASED` are excluded from both running totals."

        PRD §3.9: "The per-stop ceiling is 20 percent of the season's `total_marketing_budget_cents`, rounded half up to whole cents; each channel's ceiling is a share of that stop ceiling, again rounded half up — 40 percent for `RADIO`, 60 percent for `DIGITAL` and 30 percent for `GRASSROOTS`."

        PRD §3.9: "All caps are inclusive: a running total landing exactly on a ceiling is admitted."

        Design: Difficulty/compensating_invariant/season_marketing_budget_is_conserved_across_allocate_and_release
        """
        season_id = confirmed_booking["season_id"]
        stop_id = confirmed_booking["stop_id"]

        radio = validate_success(
            api.create_marketing_allocation(
                stop_id,
                make_marketing_allocation_payload(
                    fetch_season_version(api, season_id),
                    channel="RADIO",
                    amount_cents=3200000,
                ),
                headers=promoter_headers,
            ),
            expected_status=201,
        )
        validate_success(
            api.create_marketing_allocation(
                stop_id,
                make_marketing_allocation_payload(
                    fetch_season_version(api, season_id),
                    channel="DIGITAL",
                    amount_cents=1200000,
                ),
                headers=promoter_headers,
            ),
            expected_status=201,
        )
        validate_success(
            api.release_marketing_allocation(radio["id"], headers=promoter_headers)
        )
        before_recommit = fetch_season(api, season_id)

        # The whole 3,200,000 radio ceiling is free again, which is only true if
        # the released row left the channel's running total.
        recommitted = validate_success(
            api.create_marketing_allocation(
                stop_id,
                make_marketing_allocation_payload(
                    fetch_season_version(api, season_id),
                    channel="RADIO",
                    amount_cents=3200000,
                ),
                headers=promoter_headers,
            ),
            expected_status=201,
        )
        assert recommitted["state"] == "COMMITTED"
        assert recommitted["id"] != radio["id"]

        after_recommit = fetch_season(api, season_id)
        assert after_recommit["marketing_allocated_cents"] == 4400000
        assert after_recommit["marketing_unallocated_cents"] == 35600000
        assert after_recommit["version"] > before_recommit["version"]
        assert_marketing_budget_conserved(after_recommit)

        rows, _meta = validate_paginated(
            api.list_marketing_allocations(stop_id, headers=promoter_headers)
        )
        assert len(rows) == 3
        assert sorted(row["state"] for row in rows) == [
            "COMMITTED",
            "COMMITTED",
            "RELEASED",
        ]
