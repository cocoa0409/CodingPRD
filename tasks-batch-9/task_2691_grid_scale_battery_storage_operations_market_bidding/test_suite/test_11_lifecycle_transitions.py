"""Entity lifecycles: initial states, terminal states and invalid transitions.

Every transition here is exercised through the public endpoints, so each test
drives the platform from registration to the posture under test and then asks
for the one move the PRD either permits or refuses.
"""
import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.factories import create_market_bid_payload
from test_helpers.fixtures import (
    CLOSING_OFFICER,
    CRITICAL_CLOSURE,
    DISPATCH_DAY_CLOCK,
    TRADER,
    accept_dispatch,
    cleared_bid,
    draft_bid,
    execute_dispatch,
    fail_dispatch,
    hold_reservation,
    issue_dispatch,
    lockout_asset,
    provision_asset,
    refresh_asset,
    refresh_bid,
    refresh_dispatch,
    refresh_reservation,
    refresh_safety_event,
    refresh_test,
    release_reservation,
    schedule_test,
    set_clock,
    withdraw_bid,
)
from test_helpers.test_users import make_control_room_headers, make_site_controller_headers


class TestOfferDraftInitialState:
    """A freshly drafted offer sits in `DRAFT` with every market field empty."""

    def _plant_with_a_hold(self):
        asset = provision_asset()
        reservation = hold_reservation(asset["id"], reserved_mwh=40.0)
        return asset, reservation

    def test_draft_is_created_in_the_draft_state(self):
        """Drafting an offer returns HTTP 201 with the documented initial state.

        PRD: "A draft is created with `status` `DRAFT`, `revision_count` of 0, `cleared_price_usd_per_mwh` and `cleared_mw` and `withdrawn_reason` and `submitted_by_user_id` all null, and returns HTTP 201."

        Design: Corner/state_machines/market_bid_starts_in_draft_initial_state
        """
        asset, reservation = self._plant_with_a_hold()

        response = api_client.create_market_bid(
            create_market_bid_payload(asset["id"], reservation["id"]), TRADER
        )

        bid = validate_success(response, expected_status=201)
        assert bid["status"] == "DRAFT"
        assert bid["revision_count"] == 0
        assert bid["cleared_price_usd_per_mwh"] is None
        assert bid["cleared_mw"] is None
        assert bid["submitted_by_user_id"] is None
        assert bid["withdrawn_reason"] is None

    def test_draft_reads_back_in_the_same_initial_state(self):
        """A read of the new draft repeats the initial state, unmutated.

        PRD: "A draft is created with `status` `DRAFT`, `revision_count` of 0, `cleared_price_usd_per_mwh` and `cleared_mw` and `withdrawn_reason` and `submitted_by_user_id` all null, and returns HTTP 201."

        Design: Corner/state_machines/market_bid_starts_in_draft_initial_state
        """
        asset, reservation = self._plant_with_a_hold()
        created = draft_bid(asset["id"], reservation["id"])

        stored = refresh_bid(created["id"])

        assert stored["status"] == "DRAFT"
        assert stored["revision_count"] == 0
        assert stored["cleared_price_usd_per_mwh"] is None
        assert stored["cleared_mw"] is None
        assert stored["submitted_by_user_id"] is None
        assert stored["withdrawn_reason"] is None


class TestWithdrawnOfferIsTerminal:
    """`WITHDRAWN` is terminal: the pool is credited once and never again."""

    def _withdrawn_draft(self):
        asset = provision_asset()
        reservation = hold_reservation(asset["id"], reserved_mwh=40.0)
        bid = draft_bid(asset["id"], reservation["id"])
        withdrawn = withdraw_bid(bid["id"])
        return asset, reservation, withdrawn

    def test_withdrawal_releases_the_backing_reservation(self):
        """The first withdrawal marks the offer withdrawn and frees its energy.

        PRD: "All three withdrawable branches set `withdrawn_reason` to `TRADER_WITHDRAWAL` and release the offer's backing reservation: a reservation in `HELD` moves to `RELEASED` with `released_reason` of `BID_WITHDRAWN`, after which the asset's `reserved_mwh_total` and `free_dispatchable_mwh` are recomputed — the compensating half of the pool's conservation rule, returning exactly the energy the offer had withheld."

        Design: Corner/state_machines/withdrawn_bid_is_terminal_and_second_withdraw_rejected
        """
        asset, reservation, withdrawn = self._withdrawn_draft()

        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["withdrawn_reason"] == "TRADER_WITHDRAWAL"

        released = refresh_reservation(reservation["id"])
        assert released["status"] == "RELEASED"
        assert released["released_reason"] == "BID_WITHDRAWN"

        plant = refresh_asset(asset["id"])
        assert plant["reserved_mwh_total"] == pytest.approx(0.0, abs=0.01)
        assert plant["free_dispatchable_mwh"] == pytest.approx(70.0, abs=0.01)

    def test_second_withdrawal_is_refused(self):
        """An offer already in `WITHDRAWN` cannot be withdrawn again.

        PRD: "A `MarketTrader` may withdraw an offer whose `status` is `DRAFT`, `SUBMITTED` or `CLEARED`; an offer that is already `WITHDRAWN`, or one sitting in `UNCLEARED`, cannot be withdrawn and the attempt is refused with `ERR_BID_NOT_DRAFT`."

        Design: Corner/state_machines/withdrawn_bid_is_terminal_and_second_withdraw_rejected
        """
        asset, reservation, withdrawn = self._withdrawn_draft()

        response = api_client.withdraw_market_bid(withdrawn["id"], TRADER)

        validate_error(response, "ERR_BID_NOT_DRAFT", expected_status=409)
        assert refresh_bid(withdrawn["id"])["status"] == "WITHDRAWN"

    def test_refused_second_withdrawal_does_not_credit_the_pool_twice(self):
        """The rejected repeat leaves the reservation and the pool untouched.

        PRD: "All three withdrawable branches set `withdrawn_reason` to `TRADER_WITHDRAWAL` and release the offer's backing reservation: a reservation in `HELD` moves to `RELEASED` with `released_reason` of `BID_WITHDRAWN`, after which the asset's `reserved_mwh_total` and `free_dispatchable_mwh` are recomputed — the compensating half of the pool's conservation rule, returning exactly the energy the offer had withheld."

        Design: Corner/state_machines/withdrawn_bid_is_terminal_and_second_withdraw_rejected
        """
        asset, reservation, withdrawn = self._withdrawn_draft()

        api_client.withdraw_market_bid(withdrawn["id"], TRADER)

        plant = refresh_asset(asset["id"])
        assert plant["free_dispatchable_mwh"] == pytest.approx(70.0, abs=0.01)
        assert plant["reserved_mwh_total"] == pytest.approx(0.0, abs=0.01)

        released = refresh_reservation(reservation["id"])
        assert released["status"] == "RELEASED"
        assert released["released_reason"] == "BID_WITHDRAWN"


class TestDispatchAcceptanceIsOnceOnly:
    """Acceptance departs from `PENDING`, so the second one has nowhere to go."""

    FIRST_OPERATOR = make_control_room_headers("cro_first")
    SECOND_OPERATOR = make_control_room_headers("cro_second")

    def _accepted_instruction(self):
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()
        reservation = hold_reservation(asset["id"], reserved_mwh=40.0)
        bid = cleared_bid(asset["id"], reservation["id"])
        dispatch = issue_dispatch(bid["id"], asset["id"])
        accepted = get_success_data(
            api_client.accept_dispatch_instruction(dispatch["id"], self.FIRST_OPERATOR)
        )
        return asset, accepted

    def test_first_acceptance_records_the_accepting_operator(self):
        """The accepted instruction remembers who took the delivery up.

        PRD: "On success `accepted_by_user_id` records the acting identifier for audit only."

        Design: Corner/state_machines/dispatch_second_accept_rejected_as_not_pending
        """
        asset, accepted = self._accepted_instruction()

        assert accepted["execution_status"] == "ACCEPTED"
        assert accepted["accepted_by_user_id"] == "cro_first"

    def test_second_acceptance_is_refused_and_changes_nothing(self):
        """A second acceptance, by another operator, is refused as not pending.

        PRD: "Accepting an instruction whose `execution_status` is not `PENDING` — including a second acceptance of the same instruction — is refused with `ERR_DISPATCH_NOT_PENDING`."

        Design: Corner/state_machines/dispatch_second_accept_rejected_as_not_pending
        """
        asset, accepted = self._accepted_instruction()

        response = api_client.accept_dispatch_instruction(
            accepted["id"], self.SECOND_OPERATOR
        )

        validate_error(response, "ERR_DISPATCH_NOT_PENDING", expected_status=409)
        stored = refresh_dispatch(accepted["id"])
        assert stored["execution_status"] == "ACCEPTED"
        assert stored["accepted_by_user_id"] == "cro_first"


class TestCapacityTestCannotSkipTheStart:
    """Completion departs from `IN_PROGRESS`, never straight from `SCHEDULED`."""

    SCHEDULED_DATE = "2026-08-05T00:00:00Z"

    def _scheduled_test(self):
        set_clock()
        asset = provision_asset()
        test = schedule_test(asset["id"], scheduled_date=self.SCHEDULED_DATE)
        return asset, test

    def test_completing_a_scheduled_test_is_refused(self):
        """A test that was never started cannot be completed.

        PRD: "Completion of a test whose `status` is not `IN_PROGRESS` is refused with `ERR_TEST_NOT_IN_PROGRESS`."

        Design: Corner/state_machines/capacity_test_complete_before_start_is_an_invalid_transition
        """
        asset, test = self._scheduled_test()

        response = api_client.complete_capacity_test(
            test["id"],
            {"measured_capacity_mwh": 90.0},
            make_site_controller_headers(asset["id"]),
        )

        validate_error(response, "ERR_TEST_NOT_IN_PROGRESS", expected_status=409)

    def test_refused_completion_leaves_the_test_in_its_scheduled_shape(self):
        """The measurement fields stay null and the status stays `SCHEDULED`.

        PRD: "A scheduled test is created with `status` `SCHEDULED`, `warranty_claim_triggered` false, `test_energy_throughput_mwh` 0.0, and `measured_capacity_mwh`, `measured_soh_pct`, `expected_soh_pct` and `soh_deficit_pct` all null; it returns HTTP 201."

        Design: Corner/state_machines/capacity_test_complete_before_start_is_an_invalid_transition
        """
        asset, test = self._scheduled_test()

        api_client.complete_capacity_test(
            test["id"],
            {"measured_capacity_mwh": 90.0},
            make_site_controller_headers(asset["id"]),
        )

        stored = refresh_test(test["id"])
        assert stored["status"] == "SCHEDULED"
        assert stored["measured_capacity_mwh"] is None
        assert stored["measured_soh_pct"] is None
        assert stored["expected_soh_pct"] is None
        assert stored["soh_deficit_pct"] is None
        assert stored["warranty_claim_triggered"] is False
        assert stored["test_energy_throughput_mwh"] == pytest.approx(0.0, abs=0.01)

    def test_refused_completion_moves_no_energy_on_the_plant(self):
        """The plant's health ledgers are untouched by the rejected completion.

        PRD: "`soh_pct` starts at 100.0."

        Design: Corner/state_machines/capacity_test_complete_before_start_is_an_invalid_transition
        """
        asset, test = self._scheduled_test()

        api_client.complete_capacity_test(
            test["id"],
            {"measured_capacity_mwh": 90.0},
            make_site_controller_headers(asset["id"]),
        )

        plant = refresh_asset(asset["id"])
        assert plant["soh_pct"] == pytest.approx(100.0, abs=0.01)
        assert plant["cumulative_throughput_mwh"] == pytest.approx(0.0, abs=0.01)


class TestLockoutEventClosureNeedsSuppression:
    """The unsuppressed closure branch is closed to lockout-imposing events."""

    def _locked_out_plant(self):
        set_clock()
        asset = provision_asset()
        event = lockout_asset(asset["id"])
        return asset, event

    def test_open_lockout_event_is_created_unsuppressed(self):
        """A manual runaway declaration opens unsuppressed and imposes lockout.

        PRD: "A manually reported event is created with `source` of `MANUAL`, `status` of `OPEN`, `opened_by_user_id` set to the acting identifier, `suppression_discharged` false, `suppression_agent_kg` null, `emergency_response_ack_at` null, `emergency_ack_agencies` as an empty array, `responder_cleared` false, `closed_by_user_id` null, and `source_dispatch_id` and `source_sample_index` null."

        Design: Corner/state_machines/lockout_event_close_without_suppression_rejected
        """
        asset, event = self._locked_out_plant()

        assert event["status"] == "OPEN"
        assert event["source"] == "MANUAL"
        assert event["imposed_safety_state"] == "LOCKOUT"
        assert event["suppression_discharged"] is False
        assert event["opened_by_user_id"] == "so_1"

    def test_closing_an_unsuppressed_lockout_event_is_refused(self):
        """Closure by the second officer is refused while suppression is absent.

        PRD: "Attempting to close a lockout-imposing event whose `suppression_discharged` is still false is refused with `ERR_SUPPRESSION_NOT_DISCHARGED` (HTTP 409)."

        Design: Corner/state_machines/lockout_event_close_without_suppression_rejected
        """
        asset, event = self._locked_out_plant()

        response = api_client.close_safety_event(
            event["id"], CLOSING_OFFICER, dict(CRITICAL_CLOSURE)
        )

        validate_error(response, "ERR_SUPPRESSION_NOT_DISCHARGED", expected_status=409)

    def test_refused_closure_leaves_the_event_open(self):
        """The event keeps its `OPEN` status and its closure fields stay empty.

        PRD: "From `OPEN → CLOSED` — the unsuppressed branch — closure requires that the event's `imposed_safety_state` not be `LOCKOUT`, because a lockout-imposing event may only be closed after suppression, and again that `X-User-ID` differ from `opened_by_user_id`."

        Design: Corner/state_machines/lockout_event_close_without_suppression_rejected
        """
        asset, event = self._locked_out_plant()

        api_client.close_safety_event(event["id"], CLOSING_OFFICER, dict(CRITICAL_CLOSURE))

        stored = refresh_safety_event(event["id"])
        assert stored["status"] == "OPEN"
        assert stored["closed_by_user_id"] is None
        assert stored["suppression_discharged"] is False

    def test_refused_closure_leaves_the_plant_locked_out(self):
        """The plant keeps the posture the still-open event imposes on it.

        PRD: "While the asset's `safety_state` is `LOCKOUT`, every write outside the safety-event surface is refused with `ERR_ASSET_SAFETY_LOCKOUT` (HTTP 409)."

        Design: Corner/state_machines/lockout_event_close_without_suppression_rejected
        """
        asset, event = self._locked_out_plant()

        api_client.close_safety_event(event["id"], CLOSING_OFFICER, dict(CRITICAL_CLOSURE))

        plant = refresh_asset(asset["id"])
        assert plant["safety_state"] == "LOCKOUT"
        assert plant["market_state"] == "SUSPENDED"
        assert plant["suspension_reason"] == "SAFETY_LOCKOUT"


class TestReleaseClearsDependentDrafts:
    """Releasing a hold takes its unsold drafts out of the market with it."""

    def _hold_with_one_draft(self):
        set_clock()
        asset = provision_asset()
        reservation = hold_reservation(asset["id"], reserved_mwh=40.0)
        bid = draft_bid(asset["id"], reservation["id"])
        return asset, reservation, bid

    def test_release_records_the_operator_reason(self):
        """An explicit release is stamped `OPERATOR_RELEASE`.

        PRD: "A `MarketTrader` or `AssetManager` may release it explicitly, giving `status` `RELEASED` and `released_reason` `OPERATOR_RELEASE`; the release is refused with `ERR_RESERVATION_NOT_HELD` when the reservation is not `HELD`, and also when any offer with `status` `SUBMITTED` or `CLEARED` still references it, since live market exposure cannot be un-backed by an operator's choice."

        Design: Corner/state_machines/reservation_release_withdraws_dependent_draft_bid
        """
        asset, reservation, bid = self._hold_with_one_draft()

        released = release_reservation(reservation["id"])

        assert released["status"] == "RELEASED"
        assert released["released_reason"] == "OPERATOR_RELEASE"

    def test_release_withdraws_the_dependent_draft(self):
        """The draft standing on the released hold becomes withdrawn.

        PRD: "A release does clear the reservation's drafts: every offer on this reservation whose `status` is `DRAFT` moves to `WITHDRAWN` with `withdrawn_reason` of `TRADER_WITHDRAWAL`."

        Design: Corner/state_machines/reservation_release_withdraws_dependent_draft_bid
        """
        asset, reservation, bid = self._hold_with_one_draft()

        release_reservation(reservation["id"])

        stored = refresh_bid(bid["id"])
        assert stored["status"] == "WITHDRAWN"
        assert stored["withdrawn_reason"] == "TRADER_WITHDRAWAL"

    def test_release_returns_the_energy_to_the_pool(self):
        """The released energy reappears in the plant's dispatchable pool.

        PRD: "The asset's `reserved_mwh_total` and `free_dispatchable_mwh` are recomputed and its `version` increases by one."

        Design: Corner/state_machines/reservation_release_withdraws_dependent_draft_bid
        """
        asset, reservation, bid = self._hold_with_one_draft()
        version_before = refresh_asset(asset["id"])["version"]

        release_reservation(reservation["id"])

        plant = refresh_asset(asset["id"])
        assert plant["reserved_mwh_total"] == pytest.approx(0.0, abs=0.01)
        assert plant["free_dispatchable_mwh"] == pytest.approx(70.0, abs=0.01)
        assert plant["version"] == version_before + 1


class TestClearedWithdrawalDependsOnDispatchState:
    """A cleared offer may only be withdrawn while every order is still pending."""

    def _cleared_offer_with_two_orders(self):
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()
        reservation = hold_reservation(
            asset["id"],
            reserved_mwh=40.0,
            window_start="2026-08-10T12:00:00Z",
            window_end="2026-08-10T20:00:00Z",
        )
        bid = cleared_bid(
            asset["id"],
            reservation["id"],
            cleared_price_usd_per_mwh=45.00,
            cleared_mw=20.0,
            offer_mw=20.0,
            delivery_start="2026-08-10T12:00:00Z",
            delivery_end="2026-08-10T18:00:00Z",
        )
        pending = issue_dispatch(
            bid["id"],
            asset["id"],
            instructed_mw=20.0,
            setpoint_start="2026-08-10T14:00:00Z",
            setpoint_end="2026-08-10T14:30:00Z",
        )
        taken_up = issue_dispatch(
            bid["id"],
            asset["id"],
            instructed_mw=20.0,
            setpoint_start="2026-08-10T16:00:00Z",
            setpoint_end="2026-08-10T16:30:00Z",
        )
        accept_dispatch(taken_up["id"])
        return asset, bid, pending, taken_up

    def test_withdrawal_is_refused_while_an_order_is_accepted(self):
        """An accepted order blocks withdrawal of the offer that produced it.

        PRD: "It is permitted only when no dispatch instruction of this offer has an `execution_status` of `ACCEPTED`, `EXECUTING` or `COMPLETED`; an attempt to withdraw an offer whose delivery has already been taken up by the control room is refused with `ERR_DISPATCH_NOT_PENDING`."

        Design: Corner/state_machines/cleared_bid_withdrawal_cascade_is_conditional_on_dispatch_state
        """
        asset, bid, pending, taken_up = self._cleared_offer_with_two_orders()

        response = api_client.withdraw_market_bid(bid["id"], TRADER)

        validate_error(response, "ERR_DISPATCH_NOT_PENDING", expected_status=409)
        assert refresh_bid(bid["id"])["status"] == "CLEARED"
        assert refresh_dispatch(pending["id"])["execution_status"] == "PENDING"

    def test_failing_the_accepted_order_clears_the_way(self):
        """Voiding the taken-up order returns the offer to a withdrawable shape.

        PRD: "From `EXECUTING → FAILED` — the no-delivery branch — the instruction must have a `delivered_mwh` of exactly 0.0 and a scoring axis of `NOT_SCORED`."

        Design: Corner/state_machines/cleared_bid_withdrawal_cascade_is_conditional_on_dispatch_state
        """
        asset, bid, pending, taken_up = self._cleared_offer_with_two_orders()

        execute_dispatch(taken_up["id"], asset["id"])
        failed = fail_dispatch(taken_up["id"], failure_reason="OPERATOR_FAILURE")

        assert failed["execution_status"] == "FAILED"
        assert failed["failure_reason"] == "OPERATOR_FAILURE"
        assert failed["delivered_mwh"] == pytest.approx(0.0, abs=0.01)

    def test_withdrawal_then_voids_only_the_pending_order(self):
        """The permitted withdrawal fails the pending order and spares the rest.

        PRD: "When it is permitted, every dispatch instruction of this offer whose `execution_status` is `PENDING` moves to `FAILED` with `failure_reason` of `DELIVERY_VOIDED`, because the delivery they were issued against no longer exists."

        Design: Corner/state_machines/cleared_bid_withdrawal_cascade_is_conditional_on_dispatch_state
        """
        asset, bid, pending, taken_up = self._cleared_offer_with_two_orders()
        execute_dispatch(taken_up["id"], asset["id"])
        fail_dispatch(taken_up["id"], failure_reason="OPERATOR_FAILURE")

        withdrawn = withdraw_bid(bid["id"])

        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["withdrawn_reason"] == "TRADER_WITHDRAWAL"

        voided = refresh_dispatch(pending["id"])
        assert voided["execution_status"] == "FAILED"
        assert voided["failure_reason"] == "DELIVERY_VOIDED"

        untouched = refresh_dispatch(taken_up["id"])
        assert untouched["execution_status"] == "FAILED"
        assert untouched["failure_reason"] == "OPERATOR_FAILURE"
