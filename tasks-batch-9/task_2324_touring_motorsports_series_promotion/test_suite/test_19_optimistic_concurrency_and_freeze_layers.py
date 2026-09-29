"""Concurrency tokens, the safety freeze and the derived counters that ride along.

Three layers of the domain meet here. The two concurrency tokens — the tier
version on a ticket order and the season version on a marketing allocation —
each refuse a stale read and each advance on writes the client never made. The
safety suspension freezes a whole stop and its children, and the thaw back to
selling takes two deliberate operator acts. And every ledger the stop and the
season keep is reconciled after a create, a state change and a release.
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import ApiClient, ApiErrorId
from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers import fixtures as helpers
from test_helpers import validate_error, validate_error_is_one_of, validate_paginated
from test_helpers import validate_success


def _place_order(
    api: ApiClient,
    stop_id: str,
    tier_id: str,
    expected_tier_version: int,
    headers: Dict[str, str],
    **overrides: Any,
):
    """Place one order carrying exactly the tier version the caller last saw."""
    return api.create_ticket_order(
        F.make_ticket_order_payload(
            stop_id, tier_id, expected_tier_version, **overrides
        ),
        headers=headers,
    )


def _commit_allocation(
    api: ApiClient,
    stop_id: str,
    expected_season_version: int,
    headers: Dict[str, str],
    **overrides: Any,
):
    """Commit one allocation carrying exactly the season version the caller last saw."""
    return api.create_marketing_allocation(
        stop_id,
        F.make_marketing_allocation_payload(expected_season_version, **overrides),
        headers=headers,
    )


def _second_market_kwargs() -> Dict[str, Any]:
    """Venue and booking overrides that put a second stop in another market."""
    return {
        "venue_name": C.SECOND_VENUE_NAME,
        "market_code": C.SECOND_VENUE_MARKET_CODE,
        "city": C.SECOND_VENUE_CITY,
        "state_code": C.SECOND_VENUE_STATE_CODE,
        "tour_date": C.SECOND_TOUR_DATE,
        "load_in_start_utc": C.SECOND_LOAD_IN_START_UTC,
        "tear_down_end_utc": C.SECOND_TEAR_DOWN_END_UTC,
    }


def _stop_with_priced_seats(
    api: ApiClient, allotment: int = 500, price_cents: int = 3200
) -> Dict[str, Any]:
    """An on-sale stop with a single general-admission tier of known size."""
    return helpers.stop_on_sale(
        api,
        include_second_tier=False,
        tier_code="GA",
        price_cents=price_cents,
        allotment=allotment,
    )


def _stop_with_certified_plan_no_marketing(
    api: ApiClient, duration_minutes: int = 40
) -> Dict[str, Any]:
    """A stop with its run order, price card and certified plan, but no spend yet.

    The marketing pool is deliberately untouched so that the commit and release
    deltas measured by the counter tests start from zero.
    """
    state = helpers.stop_with_show_timing(api)
    state.update(
        helpers.create_show_segment(
            api,
            state["stop_id"],
            segment_type="COMPETITION",
            segment_title="Heat Races",
            run_order_position=1,
            duration_minutes=duration_minutes,
        )
    )
    state.update(
        helpers.create_ticket_tier(
            api, state["stop_id"], tier_code="GA", price_cents=3200, allotment=500
        )
    )
    state.update(helpers.certified_safety_plan(api, state["stop_id"]))
    state["stop"] = helpers.fetch_stop(api, state["stop_id"])
    return state


class TestTicketOrderTierVersionToken:
    """The tier version token on ``POST /ticket-orders``."""

    def test_order_creation_bumps_the_tier_version_and_reserves_the_seats(
        self, api: ApiClient, ticketing_headers: Dict[str, str]
    ) -> None:
        """PRD §3.7: "A created order opens with `status` `PENDING`, `paid_at`,
        `refunded_at` and `void_reason` all null; its `qty` is added to the tier's
        `reserved_seat_count`, `available_seat_count` falls by the same amount, and
        the tier's `version` increments by one — which is exactly why the next
        client to write against that tier needs a fresh
        `expected_ticket_tier_version`."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_ticket_order_refuses_a_stale_tier_version_and_bumps_on_every_write
        """
        state = _stop_with_priced_seats(api)
        observed_version = helpers.fetch_tier_version(api, state["tier_id"])

        order = validate_success(
            _place_order(
                api,
                state["stop_id"],
                state["tier_id"],
                observed_version,
                ticketing_headers,
                qty=4,
            ),
            201,
        )

        assert order["status"] == "PENDING"
        assert order["paid_at"] is None
        assert order["refunded_at"] is None
        assert order["void_reason"] is None

        tier = helpers.fetch_tier(api, state["tier_id"])
        assert tier["version"] == observed_version + 1
        assert tier["reserved_seat_count"] == 4
        assert tier["sold_seat_count"] == 0
        assert tier["available_seat_count"] == 496
        A.assert_seat_pool_conserved(tier)

    def test_second_order_reusing_the_same_expected_version_is_refused(
        self, api: ApiClient, ticketing_headers: Dict[str, str]
    ) -> None:
        """PRD §2.7: "If that value does not equal the tier's current `version`, the
        create is rejected with `ERR_STALE_TIER_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_ticket_order_refuses_a_stale_tier_version_and_bumps_on_every_write
        """
        state = _stop_with_priced_seats(api)
        stop_id, tier_id = state["stop_id"], state["tier_id"]
        observed_version = helpers.fetch_tier_version(api, tier_id)

        validate_success(
            _place_order(api, stop_id, tier_id, observed_version, ticketing_headers, qty=4),
            201,
        )

        stale = _place_order(
            api,
            stop_id,
            tier_id,
            observed_version,
            ticketing_headers,
            qty=4,
            purchaser_email="second@example.com",
        )
        validate_error(stale, ApiErrorId.ERR_STALE_TIER_VERSION, 412)

        # The refused write consumed nothing: the pool and the token stand where
        # the first order left them.
        tier = helpers.fetch_tier(api, tier_id)
        assert tier["version"] == observed_version + 1
        assert tier["reserved_seat_count"] == 4
        assert tier["available_seat_count"] == 496
        A.assert_seat_pool_conserved(tier)

        orders, _ = validate_paginated(
            api.list_ticket_orders(
                params={"tour_stop_id": stop_id}, headers=ticketing_headers
            )
        )
        assert len(orders) == 1

        # Re-reading the tier is all the client needs to succeed.
        retried = validate_success(
            _place_order(
                api,
                stop_id,
                tier_id,
                tier["version"],
                ticketing_headers,
                qty=4,
                purchaser_email="second@example.com",
            ),
            201,
        )
        assert retried["status"] == "PENDING"
        tier = helpers.fetch_tier(api, tier_id)
        assert tier["reserved_seat_count"] == 8
        assert tier["available_seat_count"] == 492

    def test_paying_an_order_advances_the_tier_version_and_stales_an_earlier_read(
        self, api: ApiClient, ticketing_headers: Dict[str, str]
    ) -> None:
        """PRD §3.7: "Both the tier's and the stop's `version` increment by one."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_ticket_order_refuses_a_stale_tier_version_and_bumps_on_every_write
        """
        state = _stop_with_priced_seats(api)
        stop_id, tier_id = state["stop_id"], state["tier_id"]

        first = validate_success(
            _place_order(
                api,
                stop_id,
                tier_id,
                helpers.fetch_tier_version(api, tier_id),
                ticketing_headers,
                qty=4,
            ),
            201,
        )
        version_after_create = helpers.fetch_tier_version(api, tier_id)

        validate_success(api.pay_ticket_order(first["id"], headers=ticketing_headers))

        tier = helpers.fetch_tier(api, tier_id)
        assert tier["version"] == version_after_create + 1
        assert tier["reserved_seat_count"] == 0
        assert tier["sold_seat_count"] == 4
        assert tier["available_seat_count"] == 496
        A.assert_seat_pool_conserved(tier)

        # A client holding the version it read before the payment is now stale,
        # even though it never wrote against the tier itself.
        validate_error(
            _place_order(
                api,
                stop_id,
                tier_id,
                version_after_create,
                ticketing_headers,
                qty=2,
                purchaser_email="later@example.com",
            ),
            ApiErrorId.ERR_STALE_TIER_VERSION,
            412,
        )

    def test_refunding_an_order_advances_the_tier_version_and_stales_an_earlier_read(
        self, api: ApiClient, ticketing_headers: Dict[str, str]
    ) -> None:
        """PRD §3.7: "Both the tier's and the stop's `version` increment."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_ticket_order_refuses_a_stale_tier_version_and_bumps_on_every_write
        """
        state = _stop_with_priced_seats(api)
        stop_id, tier_id = state["stop_id"], state["tier_id"]

        paid = helpers.place_paid_ticket_order(api, stop_id, tier_id, qty=4)
        version_after_pay = helpers.fetch_tier_version(api, tier_id)

        validate_success(
            api.refund_ticket_order(
                paid["order_id"], F.make_refund_payload(), headers=ticketing_headers
            )
        )

        tier = helpers.fetch_tier(api, tier_id)
        assert tier["version"] == version_after_pay + 1
        assert tier["sold_seat_count"] == 0
        assert tier["reserved_seat_count"] == 0
        assert tier["available_seat_count"] == 500
        A.assert_seat_pool_conserved(tier)

        validate_error(
            _place_order(
                api,
                stop_id,
                tier_id,
                version_after_pay,
                ticketing_headers,
                qty=2,
                purchaser_email="later@example.com",
            ),
            ApiErrorId.ERR_STALE_TIER_VERSION,
            412,
        )


class TestMarketingAllocationSeasonVersionToken:
    """The season version token on ``POST /tour-stops/{id}/marketing-allocations``."""

    def test_a_commit_in_one_market_stales_the_token_held_by_another(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """PRD §2.7: "If that value does not equal the season's current `version`,
        the commit is rejected with `ERR_STALE_SEASON_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_marketing_allocation_refuses_a_stale_season_version_including_after_a_release
        """
        first = helpers.confirmed_booking(api)
        second = helpers.confirmed_booking(
            api, season_id=first["season_id"], **_second_market_kwargs()
        )
        observed_version = helpers.fetch_season_version(api, first["season_id"])

        validate_success(
            _commit_allocation(
                api,
                first["stop_id"],
                observed_version,
                promoter_headers,
                channel="RADIO",
                amount_cents=500000,
            ),
            201,
        )

        season = helpers.fetch_season(api, first["season_id"])
        assert season["version"] == observed_version + 1
        assert season["marketing_allocated_cents"] == 500000
        assert season["marketing_unallocated_cents"] == 39500000
        A.assert_marketing_budget_conserved(season)

        # The second market planned against the pool as it was a moment ago.
        stale = _commit_allocation(
            api,
            second["stop_id"],
            observed_version,
            promoter_headers,
            channel="RADIO",
            amount_cents=700000,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_SEASON_VERSION, 412)

        # Nothing partial landed anywhere.
        season = helpers.fetch_season(api, first["season_id"])
        assert season["version"] == observed_version + 1
        assert season["marketing_allocated_cents"] == 500000
        second_stop = helpers.fetch_stop(api, second["stop_id"])
        assert second_stop["marketing_spend_committed_cents"] == 0
        rows, _ = validate_paginated(
            api.list_marketing_allocations(second["stop_id"], headers=promoter_headers)
        )
        assert rows == []

        # With a fresh token the same commit is admitted.
        validate_success(
            _commit_allocation(
                api,
                second["stop_id"],
                season["version"],
                promoter_headers,
                channel="RADIO",
                amount_cents=700000,
            ),
            201,
        )
        season = helpers.fetch_season(api, first["season_id"])
        assert season["marketing_allocated_cents"] == 1200000
        assert season["marketing_unallocated_cents"] == 38800000
        A.assert_marketing_budget_conserved(season)
        assert (
            helpers.fetch_stop(api, first["stop_id"])["marketing_spend_committed_cents"]
            == 500000
        )

    def test_a_release_also_stales_the_token_held_by_a_planner(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """PRD §2.7: "The season's `marketing_unallocated_cents` is the single pool
        every market draws from, and its `version` advances on every commit and
        every release, so a stale value means the client may be planning against
        money another market has already committed or handed back."

        Design: Corner/cross_cutting_complexity_layers/corner_occ_marketing_allocation_refuses_a_stale_season_version_including_after_a_release
        """
        state = helpers.confirmed_booking(api)
        stop_id, season_id = state["stop_id"], state["season_id"]

        allocation = validate_success(
            _commit_allocation(
                api,
                stop_id,
                helpers.fetch_season_version(api, season_id),
                promoter_headers,
                channel="RADIO",
                amount_cents=500000,
            ),
            201,
        )
        version_before_release = helpers.fetch_season_version(api, season_id)

        released = validate_success(
            api.release_marketing_allocation(allocation["id"], headers=promoter_headers)
        )
        assert released["state"] == "RELEASED"

        season = helpers.fetch_season(api, season_id)
        assert season["version"] == version_before_release + 1
        assert season["marketing_allocated_cents"] == 0
        assert season["marketing_unallocated_cents"] == 40000000
        A.assert_marketing_budget_conserved(season)

        validate_error(
            _commit_allocation(
                api,
                stop_id,
                version_before_release,
                promoter_headers,
                channel="GRASSROOTS",
                amount_cents=250000,
            ),
            ApiErrorId.ERR_STALE_SEASON_VERSION,
            412,
        )

        validate_success(
            _commit_allocation(
                api,
                stop_id,
                season["version"],
                promoter_headers,
                channel="GRASSROOTS",
                amount_cents=250000,
            ),
            201,
        )
        season = helpers.fetch_season(api, season_id)
        assert season["marketing_allocated_cents"] == 250000
        A.assert_marketing_budget_conserved(season)


class TestSafetySuspensionFreezeAndTwoStepThaw:
    """The suspension freeze, what it voids, and the two acts that undo it."""

    @staticmethod
    def _on_sale_stop_with_three_orders(api: ApiClient) -> Dict[str, Any]:
        """An on-sale stop carrying one paid order and two pending ones."""
        state = _stop_with_priced_seats(api)
        stop_id, tier_id = state["stop_id"], state["tier_id"]
        state["paid_order_id"] = helpers.place_paid_ticket_order(
            api, stop_id, tier_id, qty=10, purchaser_email="paid@example.com"
        )["order_id"]
        state["pending_small_id"] = helpers.place_ticket_order(
            api, stop_id, tier_id, qty=4, purchaser_email="pending-a@example.com"
        )["order_id"]
        state["pending_large_id"] = helpers.place_ticket_order(
            api, stop_id, tier_id, qty=6, purchaser_email="pending-b@example.com"
        )["order_id"]
        return state

    def test_suspension_freezes_the_posture_and_halts_sales_in_one_response(
        self,
        api: ApiClient,
        safety_official_headers: Dict[str, str],
    ) -> None:
        """PRD §3.5: "Suspension moves `safety_state` to `SAFETY_SUSPENDED`,
        recomputes the posture to `FROZEN`, and — because the posture left `OPEN` —
        drives a stop that was `ON_SALE` to `SALES_HALTED`, which voids every
        `PENDING` order of the stop and releases their reserved seats."

        Design: Corner/cross_cutting_complexity_layers/corner_layer_safety_suspension_freezes_the_stop_and_the_thaw_is_two_steps
        """
        state = self._on_sale_stop_with_three_orders(api)

        before = helpers.fetch_tier(api, state["tier_id"])
        assert before["sold_seat_count"] == 10
        assert before["reserved_seat_count"] == 10
        assert before["available_seat_count"] == 480

        suspended = validate_success(
            api.safety_suspend_tour_stop(
                state["stop_id"],
                F.make_safety_suspend_payload(),
                headers=safety_official_headers,
            )
        )

        assert suspended["safety_state"] == "SAFETY_SUSPENDED"
        assert suspended["sales_state"] == "SALES_HALTED"
        A.assert_stop_frozen(suspended)
        A.assert_readiness_posture(suspended, "FROZEN")

    def test_the_halt_voids_only_the_pending_orders_and_releases_their_seats(
        self,
        api: ApiClient,
        safety_official_headers: Dict[str, str],
        ticketing_headers: Dict[str, str],
    ) -> None:
        """PRD §2.8: "Whenever a recomputation leaves the posture at something other
        than `OPEN` while `sales_state` is `ON_SALE`, the server immediately drives
        the stop from `ON_SALE` to `SALES_HALTED`, and every `TicketOrder` of the
        stop still in `PENDING` is moved to `VOID` with `void_reason` set to
        `SALES_HALTED`, releasing its `qty` from the tier's `reserved_seat_count`
        and recomputing `available_seat_count`."

        Design: Corner/cross_cutting_complexity_layers/corner_layer_safety_suspension_freezes_the_stop_and_the_thaw_is_two_steps
        """
        state = self._on_sale_stop_with_three_orders(api)

        validate_success(
            api.safety_suspend_tour_stop(
                state["stop_id"],
                F.make_safety_suspend_payload(),
                headers=safety_official_headers,
            )
        )

        for order_id in (state["pending_small_id"], state["pending_large_id"]):
            voided = validate_success(
                api.get_ticket_order(order_id, headers=ticketing_headers)
            )
            assert voided["status"] == "VOID"
            assert voided["void_reason"] == "SALES_HALTED"

        paid = validate_success(
            api.get_ticket_order(state["paid_order_id"], headers=ticketing_headers)
        )
        assert paid["status"] == "PAID"
        assert paid["paid_at"] is not None
        assert paid["void_reason"] is None

        tier = helpers.fetch_tier(api, state["tier_id"])
        assert tier["reserved_seat_count"] == 0
        assert tier["sold_seat_count"] == 10
        assert tier["available_seat_count"] == 490
        A.assert_seat_pool_conserved(tier)

    def test_a_frozen_stop_refuses_writes_to_its_children(
        self,
        api: ApiClient,
        safety_official_headers: Dict[str, str],
        promoter_headers: Dict[str, str],
        ticketing_headers: Dict[str, str],
    ) -> None:
        """PRD §2.8: "`FROZEN` rejects every mutation of the stop or of any of its
        children — the sole exception being a safety reinstatement, which exists
        precisely to lift the freeze — with `ERR_STOP_FROZEN` (409)."

        Design: Corner/cross_cutting_complexity_layers/corner_layer_safety_suspension_freezes_the_stop_and_the_thaw_is_two_steps
        """
        state = self._on_sale_stop_with_three_orders(api)
        stop_id = state["stop_id"]

        validate_success(
            api.safety_suspend_tour_stop(
                stop_id, F.make_safety_suspend_payload(), headers=safety_official_headers
            )
        )

        segment_attempt = api.create_show_segment(
            stop_id,
            F.make_show_segment_payload(
                segment_type="INTERMISSION", title="Interval", run_order_position=2
            ),
            headers=promoter_headers,
        )
        validate_error(segment_attempt, ApiErrorId.ERR_STOP_FROZEN, 409)

        tier_attempt = api.create_ticket_tier(
            stop_id,
            F.make_ticket_tier_payload(tier_code="LATE", allotment=100),
            headers=ticketing_headers,
        )
        validate_error(tier_attempt, ApiErrorId.ERR_STOP_FROZEN, 409)

        allocation_attempt = _commit_allocation(
            api,
            stop_id,
            helpers.fetch_season_version(api, state["season_id"]),
            promoter_headers,
            channel="DIGITAL",
            amount_cents=100000,
        )
        validate_error(allocation_attempt, ApiErrorId.ERR_STOP_FROZEN, 409)

    def test_sales_cannot_resume_while_the_posture_is_frozen(
        self,
        api: ApiClient,
        safety_official_headers: Dict[str, str],
        ticketing_headers: Dict[str, str],
    ) -> None:
        """PRD §2.8: "`OPEN` is the only posture from which sales may be opened or
        resumed."

        Design: Corner/cross_cutting_complexity_layers/corner_layer_safety_suspension_freezes_the_stop_and_the_thaw_is_two_steps
        """
        state = self._on_sale_stop_with_three_orders(api)
        stop_id = state["stop_id"]

        validate_success(
            api.safety_suspend_tour_stop(
                stop_id, F.make_safety_suspend_payload(), headers=safety_official_headers
            )
        )

        attempt = api.resume_tour_stop_sales(stop_id, headers=ticketing_headers)
        assert attempt.status_code == 409, attempt.text
        # Three gates of the ladder cover a frozen resume — the freeze itself, the
        # uncertified safety dimension and the composite readiness gate.
        validate_error_is_one_of(
            attempt,
            [
                ApiErrorId.ERR_STOP_FROZEN.value,
                ApiErrorId.ERR_SAFETY_NOT_CERTIFIED.value,
                ApiErrorId.ERR_STOP_NOT_READY.value,
            ],
        )

        stop = helpers.fetch_stop(api, stop_id)
        assert stop["sales_state"] == "SALES_HALTED"
        A.assert_stop_frozen(stop)

    def test_reinstatement_thaws_the_posture_but_leaves_sales_halted(
        self,
        api: ApiClient,
        safety_official_headers: Dict[str, str],
        ticketing_headers: Dict[str, str],
    ) -> None:
        """PRD §3.5: "Reinstatement deliberately does **not** restore sales: a stop
        halted by a suspension stays at `SALES_HALTED` until a `TicketingManager`
        resumes it."

        Design: Corner/cross_cutting_complexity_layers/corner_layer_safety_suspension_freezes_the_stop_and_the_thaw_is_two_steps
        """
        state = self._on_sale_stop_with_three_orders(api)
        stop_id = state["stop_id"]

        validate_success(
            api.safety_suspend_tour_stop(
                stop_id, F.make_safety_suspend_payload(), headers=safety_official_headers
            )
        )

        reinstated = validate_success(
            api.safety_reinstate_tour_stop(
                stop_id,
                F.make_safety_reinstate_payload(),
                headers=safety_official_headers,
            )
        )

        assert reinstated["safety_state"] == "SAFETY_CERTIFIED"
        assert reinstated["sales_state"] == "SALES_HALTED"
        A.assert_readiness_posture(reinstated, "OPEN")

        # The freeze lifted, but the orders it voided are terminal.
        for order_id in (state["pending_small_id"], state["pending_large_id"]):
            order = validate_success(
                api.get_ticket_order(order_id, headers=ticketing_headers)
            )
            assert order["status"] == "VOID"
            assert order["void_reason"] == "SALES_HALTED"

        tier = helpers.fetch_tier(api, state["tier_id"])
        assert tier["reserved_seat_count"] == 0
        assert tier["available_seat_count"] == 490
        A.assert_seat_pool_conserved(tier)

    def test_the_second_step_of_the_thaw_is_an_explicit_resume(
        self,
        api: ApiClient,
        safety_official_headers: Dict[str, str],
        ticketing_headers: Dict[str, str],
    ) -> None:
        """PRD §3.7: "Resumption is an operator act: a `TicketingManager` moves the
        stop from `SALES_HALTED` back to `ON_SALE`, which requires the posture to be
        `OPEN` again and re-runs the same certification and readiness gates as going
        on sale, reporting `ERR_SAFETY_NOT_CERTIFIED` and `ERR_STOP_NOT_READY` on
        the same terms."

        Design: Corner/cross_cutting_complexity_layers/corner_layer_safety_suspension_freezes_the_stop_and_the_thaw_is_two_steps
        """
        state = self._on_sale_stop_with_three_orders(api)
        stop_id = state["stop_id"]

        validate_success(
            api.safety_suspend_tour_stop(
                stop_id, F.make_safety_suspend_payload(), headers=safety_official_headers
            )
        )
        validate_success(
            api.safety_reinstate_tour_stop(
                stop_id,
                F.make_safety_reinstate_payload(),
                headers=safety_official_headers,
            )
        )

        resumed = validate_success(
            api.resume_tour_stop_sales(stop_id, headers=ticketing_headers)
        )
        assert resumed["sales_state"] == "ON_SALE"
        assert resumed["safety_state"] == "SAFETY_CERTIFIED"
        A.assert_readiness_posture(resumed, "OPEN")

        # Selling works again from the reopened stop.
        tier = helpers.fetch_tier(api, state["tier_id"])
        fresh = validate_success(
            _place_order(
                api,
                stop_id,
                state["tier_id"],
                tier["version"],
                ticketing_headers,
                qty=2,
                purchaser_email="after-thaw@example.com",
            ),
            201,
        )
        assert fresh["status"] == "PENDING"


class TestDerivedCountersReconcile:
    """Every ledger reconciles after a create, a state change and a release."""

    def test_marketing_counters_reconcile_after_two_commits_and_one_release(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """PRD §2.5: "For any `Season`, `total_marketing_budget_cents` always equals
        `marketing_allocated_cents` plus `marketing_unallocated_cents`."

        Design: Corner/cross_cutting_complexity_layers/corner_layer_derived_counters_reconcile_after_create_update_and_delete
        """
        state = _stop_with_certified_plan_no_marketing(api)
        stop_id, season_id = state["stop_id"], state["season_id"]

        radio = validate_success(
            _commit_allocation(
                api,
                stop_id,
                helpers.fetch_season_version(api, season_id),
                promoter_headers,
                channel="RADIO",
                amount_cents=500000,
            ),
            201,
        )
        grassroots = validate_success(
            _commit_allocation(
                api,
                stop_id,
                helpers.fetch_season_version(api, season_id),
                promoter_headers,
                channel="GRASSROOTS",
                amount_cents=250000,
            ),
            201,
        )

        season = helpers.fetch_season(api, season_id)
        assert season["marketing_allocated_cents"] == 750000
        assert season["marketing_unallocated_cents"] == 39250000
        A.assert_marketing_budget_conserved(season)
        stop = helpers.fetch_stop(api, stop_id)
        assert stop["marketing_spend_committed_cents"] == 750000

        validate_success(
            api.release_marketing_allocation(
                grassroots["id"], headers=promoter_headers
            )
        )

        season = helpers.fetch_season(api, season_id)
        assert season["marketing_allocated_cents"] == 500000
        assert season["marketing_unallocated_cents"] == 39500000
        A.assert_marketing_budget_conserved(season)
        stop = helpers.fetch_stop(api, stop_id)
        assert stop["marketing_spend_committed_cents"] == 500000

        # The release is a state change on a row that stays in the ledger, not a
        # physical delete.
        rows, _ = validate_paginated(
            api.list_marketing_allocations(stop_id, headers=promoter_headers)
        )
        by_id = {row["id"]: row for row in rows}
        assert set(by_id) == {radio["id"], grassroots["id"]}
        assert by_id[radio["id"]]["state"] == "COMMITTED"
        assert by_id[grassroots["id"]]["state"] == "RELEASED"
        assert by_id[grassroots["id"]]["released_at"] is not None

    def test_stop_roll_ups_reconcile_across_order_create_payment_and_refund(
        self,
        api: ApiClient,
        promoter_headers: Dict[str, str],
        ticketing_headers: Dict[str, str],
    ) -> None:
        """PRD §3.7: "It stamps `refunded_at` from the logical clock, decrements the
        tier's `sold_seat_count` by `qty` and restores `available_seat_count` — the
        seat conservation invariant again — and subtracts exactly the same four
        money and count amounts from the stop's roll-ups that payment added."

        Design: Corner/cross_cutting_complexity_layers/corner_layer_derived_counters_reconcile_after_create_update_and_delete
        """
        state = _stop_with_certified_plan_no_marketing(api)
        stop_id, tier_id = state["stop_id"], state["tier_id"]
        validate_success(
            _commit_allocation(
                api,
                stop_id,
                helpers.fetch_season_version(api, state["season_id"]),
                promoter_headers,
                channel="RADIO",
                amount_cents=500000,
            ),
            201,
        )
        validate_success(api.open_tour_stop_sales(stop_id, headers=ticketing_headers))

        expected = A.expected_order_amounts(
            3200,
            25,
            C.DEFAULT_PER_TICKET_FACILITY_FEE_CENTS,
            pit_party_price_cents=C.DEFAULT_PIT_PARTY_PRICE_CENTS,
            pit_party_addon_qty=5,
        )
        order = validate_success(
            _place_order(
                api,
                stop_id,
                tier_id,
                helpers.fetch_tier_version(api, tier_id),
                ticketing_headers,
                qty=25,
                pit_party_addon_qty=5,
            ),
            201,
        )

        # A pending order reserves seats but contributes nothing to the money.
        stop = helpers.fetch_stop(api, stop_id)
        assert stop["tickets_sold_count"] == 0
        assert stop["gross_ticket_revenue_cents"] == 0
        assert stop["facility_fee_collected_cents"] == 0
        assert stop["addon_revenue_cents"] == 0
        assert stop["pit_party_sold_count"] == 0

        validate_success(api.pay_ticket_order(order["id"], headers=ticketing_headers))

        stop = helpers.fetch_stop(api, stop_id)
        assert stop["tickets_sold_count"] == 25
        assert stop["gross_ticket_revenue_cents"] == (
            expected["line_subtotal_cents"] - expected["group_discount_cents"]
        )
        assert stop["facility_fee_collected_cents"] == expected["facility_fee_cents"]
        assert stop["addon_revenue_cents"] == (
            expected["addon_subtotal_cents"] - expected["addon_discount_cents"]
        )
        assert stop["pit_party_sold_count"] == 5
        tier = helpers.fetch_tier(api, tier_id)
        assert tier["sold_seat_count"] == 25
        assert tier["reserved_seat_count"] == 0
        A.assert_seat_pool_conserved(tier)

        validate_success(
            api.refund_ticket_order(
                order["id"], F.make_refund_payload(), headers=ticketing_headers
            )
        )

        stop = helpers.fetch_stop(api, stop_id)
        assert stop["tickets_sold_count"] == 0
        assert stop["gross_ticket_revenue_cents"] == 0
        assert stop["facility_fee_collected_cents"] == 0
        assert stop["addon_revenue_cents"] == 0
        assert stop["pit_party_sold_count"] == 0
        tier = helpers.fetch_tier(api, tier_id)
        assert tier["sold_seat_count"] == 0
        assert tier["reserved_seat_count"] == 0
        assert tier["available_seat_count"] == 500
        A.assert_seat_pool_conserved(tier)

    def test_the_run_order_end_offset_reconciles_after_a_second_segment(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """PRD §3.4: "When the walk finishes, the stop's
        `run_order_end_offset_minutes` is set to the final offset, which is exactly
        the `end_offset_minutes` of the highest-positioned segment."

        Design: Corner/cross_cutting_complexity_layers/corner_layer_derived_counters_reconcile_after_create_update_and_delete
        """
        state = _stop_with_certified_plan_no_marketing(api, duration_minutes=40)
        stop_id = state["stop_id"]

        stop = helpers.fetch_stop(api, stop_id)
        assert stop["competition_segment_count"] == 1
        assert stop["run_order_end_offset_minutes"] == 40

        interval = validate_success(
            api.create_show_segment(
                stop_id,
                F.make_show_segment_payload(
                    segment_type="INTERMISSION",
                    title="Interval",
                    run_order_position=2,
                    duration_minutes=15,
                ),
                headers=promoter_headers,
            ),
            201,
        )
        assert interval["reset_gap_minutes"] == 0
        assert interval["start_offset_minutes"] == 40
        assert interval["end_offset_minutes"] == 55

        stop = helpers.fetch_stop(api, stop_id)
        assert stop["run_order_end_offset_minutes"] == 55
        assert stop["competition_segment_count"] == 1
