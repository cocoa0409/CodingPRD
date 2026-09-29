"""Two cascades that reach far past the row the client wrote.

Withdrawing a confirmed booking tears the whole market down — stop, orders, seat
pools, money counters, marketing money and staging bays — and adding one pricing
tier walks the other way, from inventory into the safety envelope and back out to
the sales window.
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    AUTO_REQUIREMENT_INCREASE,
    ApiClient,
    ApiErrorId,
    BookingState,
    LogisticsState,
    MarketingState,
    OrderStatus,
    ReadinessPosture,
    SafetyPlanState,
    SafetyState,
    SalesState,
    VoidReason,
    assert_marketing_budget_conserved,
    assert_safety_requirements,
    assert_seat_pool_conserved,
    expected_safety_requirements,
    get_success_data,
    is_iso8601_timestamp,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers import factories as F
from test_helpers import fixtures as helpers

#: The reason text carried by the withdrawal, which the cascade copies onto the stop.
WITHDRAW_REASON = "arena roof repair, market pulled"


def _read_order(
    api: ApiClient, order_id: str, headers: Dict[str, str]
) -> Dict[str, Any]:
    """The order row as the server currently holds it."""
    return get_success_data(api.get_ticket_order(order_id, headers=headers))


class TestBookingWithdrawalCascade:
    """One withdrawal on the grandparent booking unwinds everything below it."""

    def test_withdrawal_cancels_the_stop_and_reverses_both_kinds_of_order(
        self,
        api: ApiClient,
        promoter_headers: Dict[str, str],
        ticketing_headers: Dict[str, str],
    ) -> None:
        """PRD §2.9: "Withdrawing a booking that is `CONFIRMED` sets the booking to
        `WITHDRAWN` with the supplied `withdraw_reason` and decrements the season's
        `booking_count`." "Because the booking left `CONFIRMED`, the stop it produced
        moves `sales_state` to `CANCELLED` — from whichever state it held, whether
        `SALES_PENDING`, `ON_SALE`, `SALES_HALTED` or `SALES_CLOSED` — moves
        `safety_state` to `SAFETY_SUSPENDED` from either `SAFETY_CERTIFIED` or
        `SAFETY_DRAFT`, and records `cancel_reason` from the same reason text."
        "Because the stop became `CANCELLED`, every `TicketOrder` of the stop in
        `PENDING` moves to `VOID` with `void_reason` set to `STOP_CANCELLED`, and
        every `TicketOrder` in `PAID` moves to `REFUNDED`." "Because those orders left
        `PENDING` and `PAID`, each order's tier decrements `reserved_seat_count` or
        `sold_seat_count` accordingly and recomputes `available_seat_count`, and the
        stop's `tickets_sold_count`, `gross_ticket_revenue_cents`,
        `addon_revenue_cents`, `facility_fee_collected_cents` and
        `pit_party_sold_count` all decrease by the reversed amounts."

        Design: Difficulty/transitive_cascade/withdrawing_a_confirmed_booking_unwinds_stop_orders_tiers_and_season_budget
        """
        state = helpers.stop_on_sale(api)
        stop_id = state["stop_id"]
        upper_tier_id = state["second_tier_id"]

        paid = helpers.place_paid_ticket_order(
            api,
            stop_id,
            upper_tier_id,
            qty=100,
            purchaser_name="Paid Patron",
            purchaser_email="paid@example.com",
        )
        pending = helpers.place_ticket_order(
            api,
            stop_id,
            upper_tier_id,
            qty=40,
            purchaser_name="Pending Patron",
            purchaser_email="pending@example.com",
        )

        # What the market looks like before the booking is pulled.
        before_stop = helpers.fetch_stop(api, stop_id)
        assert before_stop["tickets_sold_count"] == 100
        assert before_stop["gross_ticket_revenue_cents"] == 250000
        assert before_stop["facility_fee_collected_cents"] == 35000
        before_tier = helpers.fetch_tier(api, upper_tier_id)
        assert before_tier["sold_seat_count"] == 100
        assert before_tier["reserved_seat_count"] == 40
        assert before_tier["available_seat_count"] == 2860

        withdrawn = validate_success(
            api.withdraw_venue_booking(
                state["booking_id"],
                F.make_withdraw_payload(reason=WITHDRAW_REASON),
                headers=promoter_headers,
            ),
            expected_status=200,
        )
        assert withdrawn["state"] == BookingState.WITHDRAWN
        assert withdrawn["withdraw_reason"] == WITHDRAW_REASON

        stop = helpers.fetch_stop(api, stop_id)
        assert stop["sales_state"] == SalesState.CANCELLED
        assert stop["safety_state"] == SafetyState.SAFETY_SUSPENDED
        assert stop["cancel_reason"] == WITHDRAW_REASON

        # One trigger, two different terminal states for the two orders.
        voided = _read_order(api, pending["order_id"], ticketing_headers)
        assert voided["status"] == OrderStatus.VOID
        assert voided["void_reason"] == VoidReason.STOP_CANCELLED
        refunded = _read_order(api, paid["order_id"], ticketing_headers)
        assert refunded["status"] == OrderStatus.REFUNDED

        tier = helpers.fetch_tier(api, upper_tier_id)
        assert tier["reserved_seat_count"] == 0
        assert tier["sold_seat_count"] == 0
        assert tier["held_seat_count"] == 0
        assert tier["available_seat_count"] == 3000
        assert_seat_pool_conserved(tier)

        assert stop["tickets_sold_count"] == 0
        assert stop["gross_ticket_revenue_cents"] == 0
        assert stop["facility_fee_collected_cents"] == 0
        assert stop["addon_revenue_cents"] == 0
        assert stop["pit_party_sold_count"] == 0

    def test_withdrawal_releases_the_marketing_money_the_bay_and_freezes_the_stop(
        self,
        api: ApiClient,
        promoter_headers: Dict[str, str],
        ticketing_headers: Dict[str, str],
    ) -> None:
        """PRD §2.9: "Because the stop became `CANCELLED`, every
        `MarketingAllocation` of the stop in `COMMITTED` moves to `RELEASED` with
        `released_at` stamped from the logical clock, which decrements the season's
        `marketing_allocated_cents`, recomputes `marketing_unallocated_cents` and
        increments the season's `version` by one." "Every `VehicleEntry` of the stop
        whose `logistics_state` is `ENTERED` or `STAGED` moves to `WITHDRAWN` and has
        its `staging_bay_index` cleared, returning that bay to the selector pool."
        "Finally the stop's posture is recomputed and yields `FROZEN`." PRD §3.9:
        "Releasing an allocation moves it from `COMMITTED` to `RELEASED`, stamps
        `released_at` from the logical clock, and applies exactly the inverse deltas:
        the amount comes off `marketing_allocated_cents`, `marketing_unallocated_cents`
        is restored, the season's `version` increments by one, the stop's
        `marketing_spend_committed_cents` falls, and the posture is recomputed — which
        can pull a stop back to `RESTRICTED` if the release leaves the market with no
        committed spend at all, halting an `ON_SALE` stop." PRD §2.8: "`FROZEN`
        rejects every mutation of the stop or of any of its children — the sole
        exception being a safety reinstatement, which exists precisely to lift the
        freeze — with `ERR_STOP_FROZEN` (409)."

        Design: Difficulty/transitive_cascade/withdrawing_a_confirmed_booking_unwinds_stop_orders_tiers_and_season_budget
        """
        state = helpers.stop_on_sale(api)
        stop_id = state["stop_id"]
        season_id = state["season_id"]

        entry_state = helpers.create_vehicle_entry(api, stop_id)
        entry_id = entry_state["entry_id"]
        assert entry_state["entry"]["logistics_state"] == LogisticsState.ENTERED
        assert entry_state["entry"]["staging_bay_index"] is not None

        helpers.set_clock(api, "2026-09-15T10:30:00Z")
        season_before = helpers.fetch_season(api, season_id)
        assert season_before["marketing_allocated_cents"] == 800000

        validate_success(
            api.withdraw_venue_booking(
                state["booking_id"],
                F.make_withdraw_payload(reason=WITHDRAW_REASON),
                headers=promoter_headers,
            ),
            expected_status=200,
        )

        allocation = get_success_data(
            api.get_marketing_allocation(
                state["allocation_id"], headers=promoter_headers
            )
        )
        assert allocation["state"] == MarketingState.RELEASED
        assert is_iso8601_timestamp(allocation["released_at"])
        assert allocation["released_at"].startswith("2026-09-15T10:30:00")

        stop = helpers.fetch_stop(api, stop_id)
        assert stop["marketing_spend_committed_cents"] == 0
        assert stop["readiness_posture"] == ReadinessPosture.FROZEN

        season = helpers.fetch_season(api, season_id)
        assert season["marketing_allocated_cents"] == 0
        assert season["marketing_unallocated_cents"] == 40000000
        assert season["version"] > season_before["version"]
        assert_marketing_budget_conserved(season)

        entry = helpers.fetch_entry(api, entry_id)
        assert entry["logistics_state"] == LogisticsState.WITHDRAWN
        assert entry["staging_bay_index"] is None

        # The frozen stop refuses to be taken back on sale.
        rejected = api.open_tour_stop_sales(stop_id, headers=ticketing_headers)
        assert rejected.status_code == 409
        validate_error_is_one_of(
            rejected,
            [ApiErrorId.ERR_STOP_FROZEN, ApiErrorId.ERR_INVALID_STATE_TRANSITION],
        )


class TestTierAdditionCascade:
    """A pure inventory write walks into the safety envelope and halts the sale."""

    def test_a_new_tier_raises_attendance_and_auto_returns_the_certified_plan(
        self,
        api: ApiClient,
        ticketing_headers: Dict[str, str],
    ) -> None:
        """PRD §3.6: "It recomputes the stop's `expected_attendance` as the smaller
        of the venue's `seat_capacity` and the new sum of tier allotments, and then
        recomputes the stop's safety requirement floors." PRD §3.5:
        "`required_bls_staff_count` is the larger of 2 and the attendance divided by
        2500 rounded **up** to a whole number, plus one further medic when the booked
        venue's `floor_type` is `CONCRETE`." PRD §2.9: "When the recomputed
        requirements outrun what a `CERTIFIED` plan actually provisioned, the plan
        moves from `CERTIFIED` to `RETURNED`, its `certified_by_user_id` is cleared,
        its `return_count` increments by one, and its `return_reason` is set to the
        exact string `AUTO_REQUIREMENT_INCREASE`." "Because the plan left
        `CERTIFIED`, the stop's `safety_state` moves from `SAFETY_CERTIFIED` to
        `SAFETY_DRAFT` and its posture is recomputed to `RESTRICTED`."

        Design: Difficulty/transitive_cascade/adding_a_ticket_tier_decertifies_the_safety_plan_and_halts_sales
        """
        state = helpers.stop_on_sale(api)
        stop_id = state["stop_id"]
        plan_id = state["plan_id"]
        helpers.place_ticket_order(
            api,
            stop_id,
            state["second_tier_id"],
            qty=50,
            purchaser_name="Held Patron",
            purchaser_email="held@example.com",
        )

        # The plan is provisioned at exactly the requirement the 6000-seat house implies.
        before_stop = helpers.fetch_stop(api, stop_id)
        assert before_stop["expected_attendance"] == 6000
        before_plan = helpers.fetch_safety_plan(api, plan_id)
        assert before_plan["state"] == SafetyPlanState.CERTIFIED
        assert before_plan["required_bls_staff_count"] == 3
        assert before_plan["medical_bls_staff_count"] == 3

        floor_tier = validate_success(
            api.create_ticket_tier(
                stop_id,
                F.make_ticket_tier_payload(
                    tier_code="FLOOR", price_cents=6500, allotment=3000
                ),
                headers=ticketing_headers,
            ),
            expected_status=201,
        )
        assert floor_tier["available_seat_count"] == 3000

        stop = helpers.fetch_stop(api, stop_id)
        assert stop["expected_attendance"] == 9000
        assert stop["safety_state"] == SafetyState.SAFETY_DRAFT

        plan = helpers.fetch_safety_plan(api, plan_id)
        assert plan["required_bls_staff_count"] == 4
        assert plan["medical_bls_staff_count"] == 3
        assert plan["state"] == SafetyPlanState.RETURNED
        assert plan["return_count"] == 1
        assert plan["return_reason"] == AUTO_REQUIREMENT_INCREASE
        assert plan["certified_by_user_id"] is None

    def test_the_decertified_stop_halts_sales_voids_its_orders_and_stays_shut(
        self,
        api: ApiClient,
        ticketing_headers: Dict[str, str],
    ) -> None:
        """PRD §2.9: "Because the posture left `OPEN`, a stop that was `ON_SALE` moves
        to `SALES_HALTED`, and because sales were halted, every `PENDING` order of the
        stop moves to `VOID`, releasing `reserved_seat_count` on its tier." PRD §2.8:
        "Whenever a recomputation leaves the posture at something other than `OPEN`
        while `sales_state` is `ON_SALE`, the server immediately drives the stop from
        `ON_SALE` to `SALES_HALTED`, and every `TicketOrder` of the stop still in
        `PENDING` is moved to `VOID` with `void_reason` set to `SALES_HALTED`,
        releasing its `qty` from the tier's `reserved_seat_count` and recomputing
        `available_seat_count`." PRD §3.7: "Resumption is an operator act: a
        `TicketingManager` moves the stop from `SALES_HALTED` back to `ON_SALE`, which
        requires the posture to be `OPEN` again and re-runs the same certification and
        readiness gates as going on sale, reporting `ERR_SAFETY_NOT_CERTIFIED` and
        `ERR_STOP_NOT_READY` on the same terms."

        Design: Difficulty/transitive_cascade/adding_a_ticket_tier_decertifies_the_safety_plan_and_halts_sales
        """
        state = helpers.stop_on_sale(api)
        stop_id = state["stop_id"]
        upper_tier_id = state["second_tier_id"]
        order = helpers.place_ticket_order(
            api,
            stop_id,
            upper_tier_id,
            qty=50,
            purchaser_name="Held Patron",
            purchaser_email="held@example.com",
        )
        assert order["tier"]["reserved_seat_count"] == 50

        validate_success(
            api.create_ticket_tier(
                stop_id,
                F.make_ticket_tier_payload(
                    tier_code="FLOOR", price_cents=6500, allotment=3000
                ),
                headers=ticketing_headers,
            ),
            expected_status=201,
        )

        stop = helpers.fetch_stop(api, stop_id)
        assert stop["readiness_posture"] == ReadinessPosture.RESTRICTED
        assert stop["sales_state"] == SalesState.SALES_HALTED

        voided = _read_order(api, order["order_id"], ticketing_headers)
        assert voided["status"] == OrderStatus.VOID
        assert voided["void_reason"] == VoidReason.SALES_HALTED

        tier = helpers.fetch_tier(api, upper_tier_id)
        assert tier["reserved_seat_count"] == 0
        assert tier["available_seat_count"] == 3000
        assert_seat_pool_conserved(tier)

        # Only the BLS floor crossed what the plan provisioned; the other five
        # requirements sit exactly where they sat before the tier was added.
        plan = helpers.fetch_safety_plan(api, state["plan_id"])
        assert_safety_requirements(
            plan,
            expected_safety_requirements(
                expected_attendance=9000,
                live_entry_count=0,
                heavy_rig_present=False,
                floor_type="DIRT",
            ),
        )

        rejected = api.resume_tour_stop_sales(stop_id, headers=ticketing_headers)
        validate_error(rejected, ApiErrorId.ERR_SAFETY_NOT_CERTIFIED)
