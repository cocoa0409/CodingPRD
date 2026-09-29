"""State machine corners: opening states, terminal rows and cyclic paths.

Every entity in this domain carries a declared lifecycle, and the interesting
behaviour lives at the edges of those lifecycles: the state a row is born in,
the states from which there is no route back, the two dimensions of a tour stop
that advance on their own triggers, and the plan cycle that runs back through
draft as many times as the safety desk demands.
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assert_seat_pool_conserved,
    constants as C,
    factories as F,
    fixtures as helpers,
    get_success_data,
    test_users as users,
    validate_error,
    validate_paginated,
    validate_success,
)

# The provisioning a plan needs when the house is a 500-seat single tier: every
# figure sits exactly on its requirement floor, so the plan submits and certifies
# without any headroom to hide a recomputation.
_FLOOR_PROVISIONING: Dict[str, Any] = {
    "barrier_linear_feet": 1200,
    "catch_fence_height_ft": 6,
    "medical_als_staff_count": 1,
    "medical_bls_staff_count": 2,
    "ambulance_count": 1,
    "emergency_access_lanes": 1,
}

_RETURN_REASON = "want a second ambulance on a dirt floor"


def _stop_with_returned_plan(api: ApiClient) -> Dict[str, Any]:
    """A stop whose safety plan was authored, submitted and then returned.

    The price card is built before the plan so the requirement floors are
    computed against the house that will actually be sold.
    """
    state = helpers.stop_with_show_timing(api)
    state.update(
        helpers.create_ticket_tier(
            api, state["stop_id"], tier_code="GA", price_cents=3200, allotment=500
        )
    )
    state.update(
        helpers.submitted_safety_plan(api, state["stop_id"], **_FLOOR_PROVISIONING)
    )
    state["plan"] = get_success_data(
        api.return_safety_plan(
            state["plan_id"],
            F.make_return_plan_payload(reason=_RETURN_REASON),
            headers=users.make_safety_certifier_headers(),
        )
    )
    state["stop"] = helpers.fetch_stop(api, state["stop_id"])
    return state


class TestVenueBookingInitialStateAndTerminalLockdown:
    """A booking's opening state, and the lockdown that follows withdrawal."""

    def test_fresh_booking_opens_in_terms_proposed(
        self, api: ApiClient, season: Dict[str, Any], venue: Dict[str, Any],
        promoter_headers: Dict[str, str],
    ) -> None:
        """PRD §3.1: "A fresh booking opens in `state` `TERMS_PROPOSED` with
        `negotiation_round` at 1, `terms_source` at `PROMOTER`, and
        `last_counter_by_user_id`, `confirmed_at` and `withdraw_reason` all null;
        the season's `booking_count` rises by one."

        Design: Corner/state_machines/corner_venue_booking_initial_state_and_terminal_lockdown
        """
        booking = validate_success(
            api.create_venue_booking(
                F.make_venue_booking_payload(season["season_id"], venue["venue_id"]),
                headers=promoter_headers,
            ),
            expected_status=201,
        )

        assert booking["state"] == "TERMS_PROPOSED"
        assert booking["negotiation_round"] == 1
        assert booking["terms_source"] == "PROMOTER"
        assert booking["last_counter_by_user_id"] is None
        assert booking["confirmed_at"] is None
        assert booking["withdraw_reason"] is None
        assert helpers.fetch_season(api, season["season_id"])["booking_count"] == 1

    def test_withdrawal_from_terms_proposed_leaves_no_stop_behind(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """PRD §3.1: "From `TERMS_PROPOSED` or `COUNTERED` there are no
        preconditions at all: the booking simply becomes `WITHDRAWN`, the
        season's `booking_count` decrements by one and the season's `version`
        increments by one, and nothing further happens because no stop exists
        yet."

        Design: Corner/state_machines/corner_venue_booking_initial_state_and_terminal_lockdown
        """
        state = helpers.proposed_booking(api)
        season_version_before = helpers.fetch_season_version(api, state["season_id"])

        withdrawn = validate_success(
            api.withdraw_venue_booking(
                state["booking_id"],
                F.make_withdraw_payload(reason="date released back to the building"),
                headers=promoter_headers,
            )
        )

        assert withdrawn["state"] == "WITHDRAWN"
        assert withdrawn["withdraw_reason"] == "date released back to the building"

        season = helpers.fetch_season(api, state["season_id"])
        assert season["booking_count"] == 0
        assert season["version"] == season_version_before + 1

        rows, meta = validate_paginated(
            api.list_tour_stops(
                {"venue_booking_id": state["booking_id"]}, headers=promoter_headers
            )
        )
        assert rows == []
        assert meta["total_count"] == 0

    def test_withdrawn_booking_refuses_accept_counter_and_revise(
        self, api: ApiClient, promoter_headers: Dict[str, str],
        venue_manager_headers,
    ) -> None:
        """PRD §3.1: "`CONFIRMED` and `WITHDRAWN` are both terminal for a
        booking; there is no route back."

        PRD §2.10: "`ERR_INVALID_STATE_TRANSITION` (409) — the addressed row is
        not in a state from which the requested transition is declared."

        Design: Corner/state_machines/corner_venue_booking_initial_state_and_terminal_lockdown
        """
        state = helpers.proposed_booking(api)
        get_success_data(
            api.withdraw_venue_booking(
                state["booking_id"],
                F.make_withdraw_payload(reason="date released back to the building"),
                headers=promoter_headers,
            )
        )

        validate_error(
            api.accept_venue_booking(state["booking_id"], headers=promoter_headers),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        )
        validate_error(
            api.counter_venue_booking(
                state["booking_id"],
                F.make_counter_terms_payload(),
                headers=venue_manager_headers(state["venue_id"]),
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        )
        validate_error(
            api.revise_venue_booking(
                state["booking_id"],
                F.make_revise_terms_payload(),
                headers=promoter_headers,
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        )

        booking = validate_success(
            api.get_venue_booking(state["booking_id"], headers=promoter_headers)
        )
        assert booking["state"] == "WITHDRAWN"
        assert booking["negotiation_round"] == 1
        assert booking["confirmed_at"] is None


class TestOrderTransitionsRefuseTheSecondAttempt:
    """Payment and refund are each declared from exactly one state."""

    def test_second_pay_attempt_is_refused_without_double_counting(
        self, api: ApiClient, ticketing_headers: Dict[str, str]
    ) -> None:
        """PRD §3.7: "Paying an order moves it from `PENDING` to `PAID`."

        PRD §3.7: "Payment stamps `paid_at` from the logical clock, moves `qty`
        from the tier's `reserved_seat_count` to its `sold_seat_count` while
        leaving `available_seat_count` unchanged, and adds four amounts and two
        counts to the stop's roll-ups: `line_subtotal_cents` minus
        `group_discount_cents` goes to `gross_ticket_revenue_cents`,
        `addon_subtotal_cents` minus `addon_discount_cents` goes to
        `addon_revenue_cents`, `facility_fee_cents` goes to
        `facility_fee_collected_cents`, `qty` goes to `tickets_sold_count`, and
        `pit_party_addon_qty` goes to `pit_party_sold_count`."

        Design: Corner/state_machines/corner_idempotent_retry_of_pay_is_refused_on_the_second_attempt
        """
        state = helpers.stop_with_paid_order(
            api,
            include_second_tier=False,
            tier_code="GA",
            price_cents=3200,
            allotment=500,
            per_ticket_facility_fee_cents=350,
            qty=10,
        )
        assert state["order"]["status"] == "PAID"

        validate_error(
            api.pay_ticket_order(state["order_id"], headers=ticketing_headers),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        )

        tier = helpers.fetch_tier(api, state["tier_id"])
        assert tier["sold_seat_count"] == 10
        assert tier["reserved_seat_count"] == 0
        assert tier["available_seat_count"] == 490
        assert_seat_pool_conserved(tier)

        stop = helpers.fetch_stop(api, state["stop_id"])
        assert stop["tickets_sold_count"] == 10
        assert stop["gross_ticket_revenue_cents"] == 32000
        assert stop["facility_fee_collected_cents"] == 3500

    def test_second_refund_attempt_is_refused_after_the_seats_come_back(
        self, api: ApiClient, ticketing_headers: Dict[str, str]
    ) -> None:
        """PRD §3.7: "Refunding an order moves it from `PAID` to `REFUNDED` with
        a supplied `reason`, and is admissible as long as the stop's
        `sales_state` is not `SETTLED`."

        PRD §3.7: "`REFUNDED` and `VOID` are both terminal for an order."

        Design: Corner/state_machines/corner_idempotent_retry_of_pay_is_refused_on_the_second_attempt
        """
        state = helpers.stop_with_paid_order(
            api,
            include_second_tier=False,
            tier_code="GA",
            price_cents=3200,
            allotment=500,
            per_ticket_facility_fee_cents=350,
            qty=10,
        )

        refunded = validate_success(
            api.refund_ticket_order(
                state["order_id"],
                F.make_refund_payload(reason="purchaser cancelled the trip"),
                headers=ticketing_headers,
            )
        )
        assert refunded["status"] == "REFUNDED"

        validate_error(
            api.refund_ticket_order(
                state["order_id"],
                F.make_refund_payload(reason="second refund attempt"),
                headers=ticketing_headers,
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        )

        tier = helpers.fetch_tier(api, state["tier_id"])
        assert tier["sold_seat_count"] == 0
        assert tier["available_seat_count"] == 500
        assert_seat_pool_conserved(tier)


class TestParallelStateDimensionsMoveIndependently:
    """The safety dimension can push the sales dimension, but never pull it back."""

    def test_safety_suspension_freezes_the_stop_and_halts_sales(
        self,
        api: ApiClient,
        safety_certifier_headers: Dict[str, str],
        ticketing_headers: Dict[str, str],
    ) -> None:
        """PRD §3.5: "Suspension moves `safety_state` to `SAFETY_SUSPENDED`,
        recomputes the posture to `FROZEN`, and — because the posture left
        `OPEN` — drives a stop that was `ON_SALE` to `SALES_HALTED`, which voids
        every `PENDING` order of the stop and releases their reserved seats."

        Design: Corner/state_machines/corner_parallel_state_dimensions_on_a_tour_stop_move_independently
        """
        state = helpers.stop_with_pending_order(
            api,
            include_second_tier=False,
            tier_code="GA",
            price_cents=3200,
            allotment=500,
            qty=12,
        )
        assert state["stop"]["sales_state"] == "ON_SALE"
        assert state["stop"]["safety_state"] == "SAFETY_CERTIFIED"
        assert state["stop"]["readiness_posture"] == "OPEN"

        suspended = validate_success(
            api.safety_suspend_tour_stop(
                state["stop_id"],
                F.make_safety_suspend_payload(
                    reason="unsafe catch fence anchor discovered on site"
                ),
                headers=safety_certifier_headers,
            )
        )

        assert suspended["safety_state"] == "SAFETY_SUSPENDED"
        assert suspended["readiness_posture"] == "FROZEN"
        assert suspended["sales_state"] == "SALES_HALTED"

        voided = validate_success(
            api.get_ticket_order(state["order_id"], headers=ticketing_headers)
        )
        assert voided["status"] == "VOID"
        assert voided["void_reason"] == "SALES_HALTED"

        tier = helpers.fetch_tier(api, state["tier_id"])
        assert tier["reserved_seat_count"] == 0
        assert tier["available_seat_count"] == 500
        assert_seat_pool_conserved(tier)

    def test_reinstatement_restores_the_safety_dimension_only(
        self, api: ApiClient, safety_certifier_headers: Dict[str, str]
    ) -> None:
        """PRD §3.5: "Reinstatement deliberately does **not** restore sales: a
        stop halted by a suspension stays at `SALES_HALTED` until a
        `TicketingManager` resumes it."

        Design: Corner/state_machines/corner_parallel_state_dimensions_on_a_tour_stop_move_independently
        """
        state = helpers.stop_with_pending_order(
            api,
            include_second_tier=False,
            tier_code="GA",
            price_cents=3200,
            allotment=500,
            qty=12,
        )
        get_success_data(
            api.safety_suspend_tour_stop(
                state["stop_id"],
                F.make_safety_suspend_payload(
                    reason="unsafe catch fence anchor discovered on site"
                ),
                headers=safety_certifier_headers,
            )
        )

        reinstated = validate_success(
            api.safety_reinstate_tour_stop(
                state["stop_id"],
                F.make_safety_reinstate_payload(note="anchor re-drilled and re-inspected"),
                headers=safety_certifier_headers,
            )
        )

        assert reinstated["safety_state"] == "SAFETY_CERTIFIED"
        assert reinstated["readiness_posture"] == "OPEN"
        assert reinstated["sales_state"] == "SALES_HALTED"

    def test_sales_resume_only_on_their_own_trigger(
        self, api: ApiClient, safety_certifier_headers: Dict[str, str],
        ticketing_headers: Dict[str, str],
    ) -> None:
        """PRD §3.7: "Resumption is an operator act: a `TicketingManager` moves
        the stop from `SALES_HALTED` back to `ON_SALE`, which requires the
        posture to be `OPEN` again and re-runs the same certification and
        readiness gates as going on sale, reporting `ERR_SAFETY_NOT_CERTIFIED`
        and `ERR_STOP_NOT_READY` on the same terms."

        Design: Corner/state_machines/corner_parallel_state_dimensions_on_a_tour_stop_move_independently
        """
        state = helpers.stop_with_pending_order(
            api,
            include_second_tier=False,
            tier_code="GA",
            price_cents=3200,
            allotment=500,
            qty=12,
        )
        get_success_data(
            api.safety_suspend_tour_stop(
                state["stop_id"],
                F.make_safety_suspend_payload(
                    reason="unsafe catch fence anchor discovered on site"
                ),
                headers=safety_certifier_headers,
            )
        )
        get_success_data(
            api.safety_reinstate_tour_stop(
                state["stop_id"],
                F.make_safety_reinstate_payload(note="anchor re-drilled and re-inspected"),
                headers=safety_certifier_headers,
            )
        )

        resumed = validate_success(
            api.resume_tour_stop_sales(state["stop_id"], headers=ticketing_headers)
        )

        assert resumed["sales_state"] == "ON_SALE"
        assert resumed["safety_state"] == "SAFETY_CERTIFIED"
        assert resumed["readiness_posture"] == "OPEN"


class TestSafetyPlanReturnThenPatchCyclesBackToDraft:
    """The plan cycle DRAFT to SUBMITTED to RETURNED to DRAFT and round again."""

    def test_certification_is_refused_while_the_plan_sits_at_returned(
        self, api: ApiClient, safety_certifier_headers: Dict[str, str]
    ) -> None:
        """PRD §3.5: "Certification moves a `SUBMITTED` plan to `CERTIFIED`."

        PRD §2.10: "`ERR_INVALID_STATE_TRANSITION` (409) — the addressed row is
        not in a state from which the requested transition is declared."

        Design: Corner/state_machines/corner_safety_plan_return_then_patch_cycles_back_to_draft
        """
        state = _stop_with_returned_plan(api)
        assert state["plan"]["state"] == "RETURNED"
        assert state["plan"]["return_count"] == 1
        assert state["plan"]["return_reason"] == _RETURN_REASON
        assert state["stop"]["safety_state"] == "SAFETY_DRAFT"

        validate_error(
            api.certify_safety_plan(
                state["plan_id"],
                F.make_certify_payload(),
                headers=safety_certifier_headers,
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        )

        assert helpers.fetch_safety_plan(api, state["plan_id"])["state"] == "RETURNED"

    def test_patching_a_returned_plan_moves_it_back_to_draft(
        self, api: ApiClient, safety_author_headers: Dict[str, str]
    ) -> None:
        """PRD §3.5: "A revision is admissible from `DRAFT`, where the plan
        simply stays in `DRAFT`, and from `RETURNED`, where it moves back to
        `DRAFT`; those two paths are otherwise identical."

        PRD §3.5: "The plan's `safety_cost_cents` is the provisioning bill that
        later flows into settlement: each ALS medic costs 45,000 cents, each BLS
        medic 28,000 cents, each ambulance 120,000 cents, and each linear foot of
        barrier 350 cents, and the cost is the sum of `medical_als_staff_count`,
        `medical_bls_staff_count`, `ambulance_count` and `barrier_linear_feet`
        each multiplied by its own rate."

        Design: Corner/state_machines/corner_safety_plan_return_then_patch_cycles_back_to_draft
        """
        state = _stop_with_returned_plan(api)

        revised = validate_success(
            api.update_safety_plan(
                state["plan_id"],
                F.make_safety_plan_update_payload(ambulance_count=2),
                headers=safety_author_headers,
            )
        )

        assert revised["state"] == "DRAFT"
        assert revised["ambulance_count"] == 2
        assert revised["authored_by_user_id"] == users.SAFETY_AUTHOR_USER_ID
        # 1 ALS 45000 + 2 BLS 56000 + 2 ambulances 240000 + 1200 ft 420000.
        assert revised["safety_cost_cents"] == 761000

    def test_return_is_refused_while_the_plan_sits_at_draft(
        self, api: ApiClient, safety_author_headers: Dict[str, str],
        safety_certifier_headers: Dict[str, str],
    ) -> None:
        """PRD §3.5: "Returning a `SUBMITTED` plan sends it to `RETURNED` with no
        preconditions at all."

        PRD §2.10: "`ERR_INVALID_STATE_TRANSITION` (409) — the addressed row is
        not in a state from which the requested transition is declared."

        Design: Corner/state_machines/corner_safety_plan_return_then_patch_cycles_back_to_draft
        """
        state = _stop_with_returned_plan(api)
        drafted = get_success_data(
            api.update_safety_plan(
                state["plan_id"],
                F.make_safety_plan_update_payload(ambulance_count=2),
                headers=safety_author_headers,
            )
        )
        assert drafted["state"] == "DRAFT"

        validate_error(
            api.return_safety_plan(
                state["plan_id"],
                F.make_return_plan_payload(reason="cannot return a draft"),
                headers=safety_certifier_headers,
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        )

        plan = helpers.fetch_safety_plan(api, state["plan_id"])
        assert plan["state"] == "DRAFT"
        assert plan["return_count"] == 1

    def test_resubmission_and_certification_complete_the_plan_cycle(
        self, api: ApiClient, safety_author_headers: Dict[str, str],
        safety_certifier_headers: Dict[str, str],
    ) -> None:
        """PRD §3.5: "Submitting the plan moves it from `DRAFT` to `SUBMITTED`,
        and is equally admissible from `RETURNED` to `SUBMITTED` with exactly the
        same preconditions and side effects — which is how the plan cycle `DRAFT
        → SUBMITTED → RETURNED → DRAFT` repeats."

        PRD §3.5: "On success `certified_by_user_id` is set to the caller, and
        the stop's `safety_state` moves from `SAFETY_REVIEW` to
        `SAFETY_CERTIFIED`, with the posture recomputed — which is the moment a
        stop can first become `OPEN`."

        Design: Corner/state_machines/corner_safety_plan_return_then_patch_cycles_back_to_draft
        """
        state = _stop_with_returned_plan(api)
        get_success_data(
            api.update_safety_plan(
                state["plan_id"],
                F.make_safety_plan_update_payload(ambulance_count=2),
                headers=safety_author_headers,
            )
        )

        submitted = validate_success(
            api.submit_safety_plan(state["plan_id"], headers=safety_author_headers)
        )
        assert submitted["state"] == "SUBMITTED"
        assert submitted["return_count"] == 1
        assert helpers.fetch_stop(api, state["stop_id"])["safety_state"] == "SAFETY_REVIEW"

        certified = validate_success(
            api.certify_safety_plan(
                state["plan_id"],
                F.make_certify_payload(),
                headers=safety_certifier_headers,
            )
        )
        assert certified["state"] == "CERTIFIED"
        assert certified["certified_by_user_id"] == users.SAFETY_CERTIFIER_USER_ID
        assert certified["return_count"] == 1
        assert (
            helpers.fetch_stop(api, state["stop_id"])["safety_state"]
            == "SAFETY_CERTIFIED"
        )


class TestSeasonClosesOnlyWhenTheLastStopSettles:
    """Cascade C rolls each approval up, and closes the season only at the end."""

    def test_first_approval_rolls_up_but_leaves_the_season_planning(
        self, api: ApiClient, ticketing_headers: Dict[str, str],
        finance_preparer_headers: Dict[str, str],
        finance_approver_headers: Dict[str, str],
    ) -> None:
        """PRD §2.9: "Because the stop became `SETTLED`, the season's
        `settled_stop_count` increments by one, the settlement's
        `net_to_promoter_cents` is added to the season's `season_net_cents`, and
        the season's `version` increments by one."

        PRD §2.9: "If, after that, the season has at least one tour stop, every
        tour stop of the season has `sales_state` in `SETTLED` or `CANCELLED`,
        and at least one of them is `SETTLED`, the season's `status` moves from
        `PLANNING` to `CLOSED` and the season's `version` increments again."

        Design: Corner/state_machines/corner_season_closes_only_when_the_last_outstanding_stop_settles
        """
        state = helpers.multi_market_season(
            api,
            market_count=2,
            settle=False,
            include_second_tier=False,
            tier_code="GA",
            price_cents=3200,
            allotment=500,
            qty=10,
        )
        season_id = state["season_id"]
        first, second = state["stops"]

        get_success_data(
            api.close_tour_stop_sales(first["stop_id"], headers=ticketing_headers)
        )
        settlement = get_success_data(
            api.create_settlement(first["stop_id"], headers=finance_preparer_headers)
        )
        version_before = helpers.fetch_season_version(api, season_id)

        approved = validate_success(
            api.approve_settlement(
                settlement["id"],
                F.make_approve_settlement_payload(note="ATL settled with the building"),
                headers=finance_approver_headers,
            )
        )

        assert approved["state"] == "APPROVED"
        assert approved["variant"] == "FINAL"
        assert helpers.fetch_stop(api, first["stop_id"])["sales_state"] == "SETTLED"

        season = helpers.fetch_season(api, season_id)
        assert season["settled_stop_count"] == 1
        assert season["season_net_cents"] == approved["net_to_promoter_cents"]
        assert season["status"] == "PLANNING"
        assert season["version"] > version_before
        assert helpers.fetch_stop(api, second["stop_id"])["sales_state"] != "SETTLED"

    def test_settling_the_last_outstanding_stop_closes_the_season(
        self, api: ApiClient, ticketing_headers: Dict[str, str],
        finance_preparer_headers: Dict[str, str],
        finance_approver_headers: Dict[str, str],
    ) -> None:
        """PRD §2.9: "If, after that, the season has at least one tour stop,
        every tour stop of the season has `sales_state` in `SETTLED` or
        `CANCELLED`, and at least one of them is `SETTLED`, the season's `status`
        moves from `PLANNING` to `CLOSED` and the season's `version` increments
        again."

        Design: Corner/state_machines/corner_season_closes_only_when_the_last_outstanding_stop_settles
        """
        state = helpers.multi_market_season(
            api,
            market_count=2,
            settle=False,
            include_second_tier=False,
            tier_code="GA",
            price_cents=3200,
            allotment=500,
            qty=10,
        )
        season_id = state["season_id"]

        for index, stop_state in enumerate(state["stops"]):
            get_success_data(
                api.close_tour_stop_sales(
                    stop_state["stop_id"], headers=ticketing_headers
                )
            )
            settlement = get_success_data(
                api.create_settlement(
                    stop_state["stop_id"], headers=finance_preparer_headers
                )
            )
            version_before = helpers.fetch_season_version(api, season_id)
            validate_success(
                api.approve_settlement(
                    settlement["id"],
                    F.make_approve_settlement_payload(),
                    headers=finance_approver_headers,
                )
            )
            season = helpers.fetch_season(api, season_id)
            assert season["version"] > version_before
            assert season["settled_stop_count"] == index + 1
            assert season["status"] == ("PLANNING" if index == 0 else "CLOSED")

        assert helpers.fetch_season(api, season_id)["status"] == "CLOSED"


class TestActivationReachesFulfilledAndRecognizesItsFullFee:
    """An activation's two forward moves, and the terminal state at the end."""

    def _staged_stop_with_proposed_activation(self, api: ApiClient) -> Dict[str, Any]:
        """An on-sale stop with a cleared entry and a proposed activation on it.

        Fulfilment reads the stop's `sales_state`, so the stop is taken on sale
        before the package is proposed.
        """
        state = helpers.stop_on_sale(
            api,
            include_second_tier=False,
            tier_code="GA",
            price_cents=3200,
            allotment=500,
        )
        state.update(helpers.staged_entry(api, state["stop_id"]))
        helpers.file_tech_inspection(api, state["entry_id"], result="PASSED")
        state.update(
            helpers.create_sponsorship_activation(
                api,
                state["stop_id"],
                hospitality_tier_id=state["tier_id"],
                branded_vehicle_entry_id=state["entry_id"],
                company_name="Apex Tire",
                fee_cents=900000,
                vehicle_branding_slots=2,
                signage_units=6,
                hospitality_seat_count=15,
            )
        )
        return state

    def test_activation_places_holds_on_the_tier_entry_and_stop(
        self, api: ApiClient, promoter_headers: Dict[str, str]
    ) -> None:
        """PRD §3.8: "Activation is the promoter's act, moving the package from
        `PROPOSED` to `ACTIVATED`."

        PRD §3.8: "The `hospitality_seat_count` is added to the named tier's
        `held_seat_count`, that tier's `available_seat_count` is recomputed and
        its `version` increments by one — which is another reason a box-office
        client's `expected_ticket_tier_version` can go stale without any order
        being written."

        PRD §3.8: "The `fee_cents` is added to the stop's
        `sponsorship_committed_cents`, which sums fees over the stop's
        activations in `ACTIVATED` or `FULFILLED`, and the
        `hospitality_seat_count` is added to the stop's
        `held_hospitality_seat_count`, which sums hospitality seats over the same
        set."

        Design: Corner/state_machines/corner_activation_reaches_fulfilled_and_recognizes_its_full_fee
        """
        state = self._staged_stop_with_proposed_activation(api)
        assert state["activation"]["state"] == "PROPOSED"
        assert state["activation"]["recognized_fee_cents"] == 0
        assert state["activation"]["obligations_fulfilled_at"] is None
        assert helpers.fetch_tier(api, state["tier_id"])["held_seat_count"] == 0
        assert helpers.fetch_entry(api, state["entry_id"])["branding_slots_committed"] == 0

        activated = validate_success(
            api.activate_sponsorship_activation(
                state["activation_id"], headers=promoter_headers
            )
        )

        assert activated["state"] == "ACTIVATED"

        tier = helpers.fetch_tier(api, state["tier_id"])
        assert tier["held_seat_count"] == 15
        assert tier["available_seat_count"] == 485
        assert_seat_pool_conserved(tier)

        assert helpers.fetch_entry(api, state["entry_id"])["branding_slots_committed"] == 2

        stop = helpers.fetch_stop(api, state["stop_id"])
        assert stop["sponsorship_committed_cents"] == 900000
        assert stop["held_hospitality_seat_count"] == 15

    def test_fulfilment_recognizes_the_full_fee_and_leaves_the_holds_alone(
        self, api: ApiClient, promoter_headers: Dict[str, str], sponsor_rep_headers
    ) -> None:
        """PRD §3.8: "It stamps `obligations_fulfilled_at` from the logical clock
        and sets `recognized_fee_cents` to the full `fee_cents`, because no
        holdback ever applies to a fulfilled activation under either settlement
        variant."

        Design: Corner/state_machines/corner_activation_reaches_fulfilled_and_recognizes_its_full_fee
        """
        state = self._staged_stop_with_proposed_activation(api)
        get_success_data(
            api.activate_sponsorship_activation(
                state["activation_id"], headers=promoter_headers
            )
        )
        helpers.set_clock(api, C.DEFAULT_CHECK_IN_CLOCK_UTC)

        fulfilled = validate_success(
            api.fulfill_sponsorship_activation(
                state["activation_id"],
                F.make_fulfill_payload(
                    note="signage hung, hospitality seats ticketed, wrap photographed"
                ),
                headers=sponsor_rep_headers(state["sponsor_id"]),
            )
        )

        assert fulfilled["state"] == "FULFILLED"
        assert fulfilled["recognized_fee_cents"] == 900000
        assert fulfilled["obligations_fulfilled_at"] is not None
        assert fulfilled["obligations_fulfilled_at"].startswith("2026-11-14T17:00:00")

        tier = helpers.fetch_tier(api, state["tier_id"])
        assert tier["held_seat_count"] == 15
        assert tier["available_seat_count"] == 485
        assert helpers.fetch_entry(api, state["entry_id"])["branding_slots_committed"] == 2

        stop = helpers.fetch_stop(api, state["stop_id"])
        assert stop["sponsorship_committed_cents"] == 900000
        assert stop["held_hospitality_seat_count"] == 15

    def test_second_fulfilment_is_refused_because_fulfilled_is_terminal(
        self, api: ApiClient, promoter_headers: Dict[str, str], sponsor_rep_headers
    ) -> None:
        """PRD §3.8: "`FULFILLED` is terminal."

        PRD §2.10: "`ERR_INVALID_STATE_TRANSITION` (409) — the addressed row is
        not in a state from which the requested transition is declared."

        Design: Corner/state_machines/corner_activation_reaches_fulfilled_and_recognizes_its_full_fee
        """
        state = self._staged_stop_with_proposed_activation(api)
        get_success_data(
            api.activate_sponsorship_activation(
                state["activation_id"], headers=promoter_headers
            )
        )
        get_success_data(
            api.fulfill_sponsorship_activation(
                state["activation_id"],
                F.make_fulfill_payload(),
                headers=sponsor_rep_headers(state["sponsor_id"]),
            )
        )

        validate_error(
            api.fulfill_sponsorship_activation(
                state["activation_id"],
                F.make_fulfill_payload(note="second fulfil attempt"),
                headers=sponsor_rep_headers(state["sponsor_id"]),
            ),
            ApiErrorId.ERR_INVALID_STATE_TRANSITION,
        )

        activation = validate_success(
            api.get_sponsorship_activation(
                state["activation_id"], headers=promoter_headers
            )
        )
        assert activation["state"] == "FULFILLED"
        assert activation["recognized_fee_cents"] == 900000
