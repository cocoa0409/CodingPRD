"""Entity-specific not-found codes and the state guards of the action endpoints.

One HTTP status shared by many rules is not the same thing as one error code:
every collection answers a miss with the code named for its own entity, and
every action endpoint answers a wrong-state call with the code named for its own
transition. These tests drive each guard from the state it actually rejects.
"""
import pytest
from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.factories import (
    create_telemetry_sample_payload,
    clearing_result_payload,
)
from test_helpers.fixtures import (
    ASSET_MANAGER,
    CLOSING_OFFICER,
    DISPATCH_DAY_CLOCK,
    MARKET_OPERATOR,
    TRADER,
    accept_dispatch,
    append_sample,
    cleared_bid,
    close_event,
    complete_dispatch,
    draft_bid,
    execute_dispatch,
    hold_reservation,
    issue_dispatch,
    open_safety_event,
    provision_asset,
    refresh_asset,
    refresh_bid,
    refresh_dispatch,
    refresh_safety_event,
    set_clock,
    settle_score,
)
from test_helpers.test_users import (
    make_control_room_headers,
    make_site_controller_headers,
)

RESERVATION_WINDOW = ("2026-08-10T12:00:00Z", "2026-08-10T20:00:00Z")
SETPOINT_WINDOW = ("2026-08-10T12:00:00Z", "2026-08-10T14:00:00Z")


def _pending_delivery(instructed_mw=10.0):
    """A cleared 10 MW position with its instruction left PENDING."""
    set_clock(DISPATCH_DAY_CLOCK)
    asset = provision_asset()
    reservation = hold_reservation(
        asset["id"],
        reserved_mwh=40.0,
        window_start=RESERVATION_WINDOW[0],
        window_end=RESERVATION_WINDOW[1],
    )
    bid = cleared_bid(
        asset["id"],
        reservation["id"],
        cleared_price_usd_per_mwh=45.00,
        cleared_mw=instructed_mw,
        offer_mw=instructed_mw,
    )
    dispatch = issue_dispatch(
        bid["id"],
        asset["id"],
        instructed_mw=instructed_mw,
        setpoint_start=SETPOINT_WINDOW[0],
        setpoint_end=SETPOINT_WINDOW[1],
    )
    return asset, dispatch


class TestEveryCollectionHasItsOwnNotFoundCode:
    """A well-formed but absent id is answered by the entity's own 404 code."""

    @pytest.mark.parametrize(
        "read, absent_id, expected_error",
        [
            (
                api_client.get_storage_asset,
                "00000000-0000-4000-8000-00000000fff1",
                "ERR_ASSET_NOT_FOUND",
            ),
            (
                api_client.get_soc_reservation,
                "00000000-0000-4000-8000-00000000fff2",
                "ERR_RESERVATION_NOT_FOUND",
            ),
            (
                api_client.get_market_bid,
                "00000000-0000-4000-8000-00000000fff3",
                "ERR_BID_NOT_FOUND",
            ),
            (
                api_client.get_safety_event,
                "00000000-0000-4000-8000-00000000fff4",
                "ERR_SAFETY_EVENT_NOT_FOUND",
            ),
            (
                api_client.get_capacity_obligation,
                "00000000-0000-4000-8000-00000000fff5",
                "ERR_OBLIGATION_NOT_FOUND",
            ),
            (
                api_client.get_capacity_test,
                "00000000-0000-4000-8000-00000000fff6",
                "ERR_TEST_NOT_FOUND",
            ),
            (
                api_client.get_warranty_claim,
                "00000000-0000-4000-8000-00000000fff7",
                "ERR_CLAIM_NOT_FOUND",
            ),
        ],
    )
    def test_each_entity_answers_with_its_own_code(self, read, absent_id, expected_error):
        """Seven collections, seven distinct codes — never one shared generic code.

        PRD: "A miss yields the not-found code of the entity that failed to resolve: `ERR_ASSET_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_BID_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND`, `ERR_SAFETY_EVENT_NOT_FOUND`, `ERR_OBLIGATION_NOT_FOUND`, `ERR_TEST_NOT_FOUND` or `ERR_CLAIM_NOT_FOUND`, each HTTP 404."

        Design: Corner/errors/every_path_id_returns_its_own_entity_specific_not_found
        """
        validate_error(read(absent_id, ASSET_MANAGER), expected_error, expected_status=404)

    def test_an_absent_instruction_reports_the_dispatch_code(self):
        """The eighth code in the same sentence belongs to the instruction collection.

        PRD: "A miss yields the not-found code of the entity that failed to resolve: `ERR_ASSET_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_BID_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND`, `ERR_SAFETY_EVENT_NOT_FOUND`, `ERR_OBLIGATION_NOT_FOUND`, `ERR_TEST_NOT_FOUND` or `ERR_CLAIM_NOT_FOUND`, each HTTP 404."

        Design: Corner/errors/every_path_id_returns_its_own_entity_specific_not_found
        """
        validate_error(
            api_client.get_dispatch_instruction(
                "00000000-0000-4000-8000-00000000fff8", ASSET_MANAGER
            ),
            "ERR_DISPATCH_NOT_FOUND",
            expected_status=404,
        )

    def test_a_nested_telemetry_read_resolves_its_path_id_first(self):
        """The telemetry collection hangs off an instruction, so the miss is the instruction's.

        PRD: "The resource named by an `{id}` path segment exists; when a path carries more than one identifier they are resolved strictly left to right."

        Design: Corner/errors/every_path_id_returns_its_own_entity_specific_not_found
        """
        validate_error(
            api_client.list_telemetry_samples(
                "00000000-0000-4000-8000-00000000fff9", ASSET_MANAGER
            ),
            "ERR_DISPATCH_NOT_FOUND",
            expected_status=404,
        )


class TestDraftOfferRejectsClearingAndRevision:
    """Both `ERR_BID_NOT_SUBMITTED` surfaces are reachable from a fresh DRAFT."""

    def _drafted(self):
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()
        reservation = hold_reservation(
            asset["id"],
            reserved_mwh=40.0,
            window_start=RESERVATION_WINDOW[0],
            window_end=RESERVATION_WINDOW[1],
        )
        return draft_bid(asset["id"], reservation["id"], offer_mw=10.0)

    def test_a_new_offer_starts_in_draft_with_no_revisions(self):
        """The state both probes depart from is the one creation leaves behind.

        PRD: "A draft is created with `status` `DRAFT`, `revision_count` of 0, `cleared_price_usd_per_mwh` and `cleared_mw` and `withdrawn_reason` and `submitted_by_user_id` all null, and returns HTTP 201."

        Design: Corner/errors/clearing_result_and_revise_on_a_draft_bid_return_bid_not_submitted
        """
        bid = self._drafted()

        assert bid["status"] == "DRAFT"
        assert bid["revision_count"] == 0
        assert bid["cleared_price_usd_per_mwh"] is None
        assert bid["cleared_mw"] is None

    def test_clearing_a_draft_offer_is_refused(self):
        """The market cannot answer an offer that was never made.

        PRD: "Posting a clearing result against an offer whose `status` is not `SUBMITTED` is refused with `ERR_BID_NOT_SUBMITTED`, and the operation also requires the asset's `market_state` to be `AVAILABLE`."

        Design: Corner/errors/clearing_result_and_revise_on_a_draft_bid_return_bid_not_submitted
        """
        bid = self._drafted()

        validate_error(
            api_client.post_clearing_result(
                bid["id"],
                clearing_result_payload(
                    "CLEARED", cleared_price_usd_per_mwh=45.0, cleared_mw=10.0
                ),
                MARKET_OPERATOR,
            ),
            "ERR_BID_NOT_SUBMITTED",
            expected_status=409,
        )

        after = refresh_bid(bid["id"])
        assert after["status"] == "DRAFT"
        assert after["cleared_price_usd_per_mwh"] is None

    def test_revising_a_draft_offer_is_refused_and_writes_nothing(self):
        """A draft is edited by withdrawing and re-offering, never by revising.

        PRD: "A `MarketTrader` revises an offer that is `UNCLEARED`, and a revision request against an offer in any other status is refused with `ERR_BID_NOT_SUBMITTED`."

        Design: Corner/errors/clearing_result_and_revise_on_a_draft_bid_return_bid_not_submitted
        """
        bid = self._drafted()

        validate_error(
            api_client.revise_market_bid(bid["id"], {"offer_mw": 9.0}, TRADER),
            "ERR_BID_NOT_SUBMITTED",
            expected_status=409,
        )

        after = refresh_bid(bid["id"])
        assert after["status"] == "DRAFT"
        assert after["offer_mw"] == pytest.approx(10.0, abs=0.01)
        assert after["revision_count"] == 0


class TestDispatchActionsCarryTheirOwnStateCodes:
    """Four action endpoints, four distinct 409 codes, one PENDING instruction."""

    def test_a_new_instruction_starts_pending_and_unscored(self):
        """The two axes start independently, which is why two guards exist.

        PRD: "A new instruction inherits `direction` from the offer it executes — `DISCHARGE` or `CHARGE` — and starts with `execution_status` of `PENDING`, `scoring_status` of `NOT_SCORED`, `delivered_mwh` of 0.0, `soc_delta_mwh` of 0.0, `telemetry_sample_count` of 0, `non_performance_charge_usd` of 0.0, and `accuracy_score`, `deadband_pct`, `composite_score`, `failure_reason` and `accepted_by_user_id` all null."

        Design: Corner/errors/dispatch_out_of_order_actions_return_their_own_state_codes
        """
        _, dispatch = _pending_delivery()

        assert dispatch["execution_status"] == "PENDING"
        assert dispatch["scoring_status"] == "NOT_SCORED"
        assert dispatch["telemetry_sample_count"] == 0

    def test_executing_a_pending_instruction_reports_not_accepted(self):
        """The plant cannot start an order the control room has not taken up.

        PRD: "Execution on an instruction whose `execution_status` is not `ACCEPTED` is refused with `ERR_DISPATCH_NOT_ACCEPTED`."

        Design: Corner/errors/dispatch_out_of_order_actions_return_their_own_state_codes
        """
        asset, dispatch = _pending_delivery()

        validate_error(
            api_client.execute_dispatch_instruction(
                dispatch["id"], make_site_controller_headers(asset["id"])
            ),
            "ERR_DISPATCH_NOT_ACCEPTED",
            expected_status=409,
        )
        assert refresh_dispatch(dispatch["id"])["execution_status"] == "PENDING"

    def test_settling_a_pending_instruction_reports_the_execution_guard(self):
        """The execution axis is examined before the scoring axis, so it answers first.

        PRD: "Where one operation is guarded by two independent state axes, the execution axis is checked before the scoring axis: settling a performance score reports `ERR_DISPATCH_NOT_COMPLETED` before it would report `ERR_SCORE_NOT_PROVISIONAL`."

        Design: Corner/errors/dispatch_out_of_order_actions_return_their_own_state_codes
        """
        _, dispatch = _pending_delivery()

        validate_error(
            api_client.settle_dispatch_score(dispatch["id"], MARKET_OPERATOR),
            "ERR_DISPATCH_NOT_COMPLETED",
            expected_status=409,
        )
        assert refresh_dispatch(dispatch["id"])["scoring_status"] == "NOT_SCORED"

    def test_acceptance_still_works_after_the_rejections(self):
        """Rejected calls leave no residue: the legal transition is still available.

        PRD: "A `ControlRoomOperator` moves an instruction `PENDING → ACCEPTED`, which requires the offer to still be `CLEARED`, the asset's `safety_state` not to be `LOCKOUT`, and the asset's `market_state` to be `AVAILABLE`; while the asset's `safety_state` is `ELEVATED`, `instructed_mw` must additionally not exceed 50.0 percent of `power_rating_mw`, or the acceptance is refused with `ERR_ASSET_DERATED`."

        Design: Corner/errors/dispatch_out_of_order_actions_return_their_own_state_codes
        """
        asset, dispatch = _pending_delivery()
        validate_error(
            api_client.execute_dispatch_instruction(
                dispatch["id"], make_site_controller_headers(asset["id"])
            ),
            "ERR_DISPATCH_NOT_ACCEPTED",
        )
        validate_error(
            api_client.settle_dispatch_score(dispatch["id"], MARKET_OPERATOR),
            "ERR_DISPATCH_NOT_COMPLETED",
        )

        accepted = accept_dispatch(dispatch["id"])

        assert accepted["execution_status"] == "ACCEPTED"

    def test_completing_an_accepted_instruction_reports_not_executing(self):
        """Delivery has to begin before it can be closed out.

        PRD: "completion of an instruction whose `execution_status` is not `EXECUTING` is refused with `ERR_DISPATCH_NOT_EXECUTING`."

        Design: Corner/errors/dispatch_out_of_order_actions_return_their_own_state_codes
        """
        asset, dispatch = _pending_delivery()
        accept_dispatch(dispatch["id"])

        validate_error(
            api_client.complete_dispatch_instruction(
                dispatch["id"], make_site_controller_headers(asset["id"])
            ),
            "ERR_DISPATCH_NOT_EXECUTING",
            expected_status=409,
        )
        assert refresh_dispatch(dispatch["id"])["execution_status"] == "ACCEPTED"

    def test_telemetry_against_an_accepted_instruction_is_refused(self):
        """The same code guards the ingestion surface, not just completion.

        PRD: "A sample may be appended only while the instruction's `execution_status` is `EXECUTING` or `COMPLETED`; appending to an instruction in any other execution state is refused with `ERR_DISPATCH_NOT_EXECUTING`."

        Design: Corner/errors/dispatch_out_of_order_actions_return_their_own_state_codes
        """
        asset, dispatch = _pending_delivery()
        accept_dispatch(dispatch["id"])

        validate_error(
            api_client.create_telemetry_sample(
                create_telemetry_sample_payload(
                    dispatch["id"],
                    1,
                    "2026-08-10T13:00:00Z",
                    measured_mw=10.0,
                    measured_mvar=4.0,
                    soc_mwh_reading=78.0,
                    max_cell_temp_c=40.0,
                ),
                make_site_controller_headers(asset["id"]),
            ),
            "ERR_DISPATCH_NOT_EXECUTING",
            expected_status=409,
        )
        assert refresh_dispatch(dispatch["id"])["telemetry_sample_count"] == 0


class TestSettlementIsOneShot:
    """`COMPLETED` clears the first guard, so only the scoring guard can reject."""

    def _delivered(self):
        asset, dispatch = _pending_delivery()
        accept_dispatch(dispatch["id"])
        execute_dispatch(dispatch["id"], asset["id"])
        append_sample(
            dispatch["id"],
            asset["id"],
            1,
            "2026-08-10T13:00:00Z",
            measured_mw=10.0,
            soc_mwh_reading=78.0,
            max_cell_temp_c=40.0,
        )
        return asset, complete_dispatch(dispatch["id"], asset["id"])

    def test_completion_scores_the_delivery_provisionally_without_charging(self):
        """One sample dead on setpoint scores 100.00 and the provisional pass never charges.

        PRD: "Its `non_performance_charge_usd` is forced to 0.0 regardless of how poor the composite score is — the provisional pass never charges."

        Design: Corner/errors/settling_a_settled_score_returns_score_not_provisional
        """
        _, dispatch = self._delivered()

        assert dispatch["scoring_status"] == "PROVISIONAL"
        assert dispatch["delivered_mwh"] == pytest.approx(2.5, abs=0.01)
        assert dispatch["accuracy_score"] == pytest.approx(100.00, abs=0.01)
        assert dispatch["deadband_pct"] == pytest.approx(100.00, abs=0.01)
        assert dispatch["composite_score"] == pytest.approx(100.00, abs=0.01)
        assert dispatch["non_performance_charge_usd"] == pytest.approx(0.0, abs=0.01)

    def test_settlement_moves_the_scoring_axis_and_assesses_no_charge(self):
        """A composite at or above the floor of 75.00 costs nothing.

        PRD: "`accuracy_score`, `deadband_pct` and `composite_score` are recomputed from the wider set, and the charge is then assessed: `non_performance_charge_usd` is the greater of 0 and 75.00 minus `composite_score`, multiplied by `instructed_mw`, multiplied by 4.00 dollars, rounded half up to 2 decimal places."

        Design: Corner/errors/settling_a_settled_score_returns_score_not_provisional
        """
        _, dispatch = self._delivered()

        settled = settle_score(dispatch["id"])

        assert settled["scoring_status"] == "SETTLED"
        assert settled["execution_status"] == "COMPLETED"
        assert settled["composite_score"] == pytest.approx(100.00, abs=0.01)
        assert settled["non_performance_charge_usd"] == pytest.approx(0.00, abs=0.01)

    def test_a_second_settlement_reports_the_scoring_guard(self):
        """`SETTLED` is terminal on the scoring axis, so the second call is refused.

        PRD: "It requires the execution axis to be `COMPLETED`, and the two guards are ordered: an instruction that is not `COMPLETED` is refused with `ERR_DISPATCH_NOT_COMPLETED` before the scoring axis is examined at all, while an instruction that is `COMPLETED` but whose scoring axis is not `PROVISIONAL` — one already settled, for instance — is refused with `ERR_SCORE_NOT_PROVISIONAL`."

        Design: Corner/errors/settling_a_settled_score_returns_score_not_provisional
        """
        _, dispatch = self._delivered()
        settle_score(dispatch["id"])

        validate_error(
            api_client.settle_dispatch_score(dispatch["id"], MARKET_OPERATOR),
            "ERR_SCORE_NOT_PROVISIONAL",
            expected_status=409,
        )

    def test_the_rejected_settlement_assesses_nothing_twice(self):
        """The charge may not be assessed twice against the same instruction.

        PRD: "The settled pass is a `MarketOperator`'s act on an instruction whose scoring axis is `PROVISIONAL`, and it produces `PROVISIONAL → SETTLED`."

        Design: Corner/errors/settling_a_settled_score_returns_score_not_provisional
        """
        _, dispatch = self._delivered()
        settle_score(dispatch["id"])
        validate_error(
            api_client.settle_dispatch_score(dispatch["id"], MARKET_OPERATOR),
            "ERR_SCORE_NOT_PROVISIONAL",
        )

        after = refresh_dispatch(dispatch["id"])
        assert after["scoring_status"] == "SETTLED"
        assert after["composite_score"] == pytest.approx(100.00, abs=0.01)
        assert after["non_performance_charge_usd"] == pytest.approx(0.00, abs=0.01)


class TestClosedEventRejectsBothSafetyActions:
    """A `CLOSED` event is the single state that trips both safety-event codes."""

    def _closed_advisory_event(self):
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()
        event = open_safety_event(
            asset["id"],
            event_type="THERMAL_ANOMALY",
            severity="ADVISORY",
            detected_max_cell_temp_c=41.0,
            headers=make_control_room_headers("cro_1"),
        )
        closed = close_event(event["id"], responder_cleared=True)
        return asset, closed

    def test_an_advisory_event_imposes_nothing_and_closes_unsuppressed(self):
        """An advisory event contributes no posture, so closure needs no suppression.

        PRD: "`event_type` is one of `THERMAL_ANOMALY`, `THERMAL_RUNAWAY`, `OFFGAS_DETECTED` or `SMOKE_DETECTED`; `severity` is one of `ADVISORY`, `WARNING` or `CRITICAL`."

        Design: Corner/errors/closed_event_rejects_suppression_and_a_second_close
        """
        asset, closed = self._closed_advisory_event()

        assert closed["imposed_safety_state"] == "NONE"
        assert closed["status"] == "CLOSED"
        assert refresh_asset(asset["id"])["safety_state"] == "NORMAL"

    def test_suppression_on_a_closed_event_reports_not_open(self):
        """Discharge demands `OPEN`, and `CLOSED` is not it.

        PRD: "The transition requires `suppression_discharged` to be false beforehand, and discharging on an event whose `status` is not `OPEN` is refused with `ERR_EVENT_NOT_OPEN`."

        Design: Corner/errors/closed_event_rejects_suppression_and_a_second_close
        """
        _, closed = self._closed_advisory_event()

        validate_error(
            api_client.discharge_suppression(
                closed["id"], {"suppression_agent_kg": 12.5}, CLOSING_OFFICER
            ),
            "ERR_EVENT_NOT_OPEN",
            expected_status=409,
        )

    def test_a_second_close_reports_not_suppressing(self):
        """Closure accepts `OPEN` or `SUPPRESSION_ACTIVE`, so a closed event is refused.

        PRD: "Closing an event whose `status` is neither `OPEN` nor `SUPPRESSION_ACTIVE` is refused with `ERR_EVENT_NOT_SUPPRESSING`."

        Design: Corner/errors/closed_event_rejects_suppression_and_a_second_close
        """
        _, closed = self._closed_advisory_event()

        validate_error(
            api_client.close_safety_event(
                closed["id"], CLOSING_OFFICER, {"responder_cleared": True}
            ),
            "ERR_EVENT_NOT_SUPPRESSING",
            expected_status=409,
        )

    def test_neither_rejected_call_wrote_anything(self):
        """The suppression fields stay exactly as creation left them.

        PRD: "A manually reported event is created with `source` of `MANUAL`, `status` of `OPEN`, `opened_by_user_id` set to the acting identifier, `suppression_discharged` false, `suppression_agent_kg` null, `emergency_response_ack_at` null, `emergency_ack_agencies` as an empty array, `responder_cleared` false, `closed_by_user_id` null, and `source_dispatch_id` and `source_sample_index` null."

        Design: Corner/errors/closed_event_rejects_suppression_and_a_second_close
        """
        _, closed = self._closed_advisory_event()
        validate_error(
            api_client.discharge_suppression(
                closed["id"], {"suppression_agent_kg": 12.5}, CLOSING_OFFICER
            ),
            "ERR_EVENT_NOT_OPEN",
        )
        validate_error(
            api_client.close_safety_event(
                closed["id"], CLOSING_OFFICER, {"responder_cleared": True}
            ),
            "ERR_EVENT_NOT_SUPPRESSING",
        )

        after = refresh_safety_event(closed["id"])
        assert after["suppression_discharged"] is False
        assert after["suppression_agent_kg"] is None
        assert after["status"] == "CLOSED"


class TestCriticalClosureNeedsTheWholeAcknowledgement:
    """Three parts, one code: any missing part keeps the plant out of the market."""

    ACK_AT = "2026-08-10T01:30:00Z"
    AGENCY = "Mesa County Fire District 4"

    def _alarmed_asset(self):
        set_clock(DISPATCH_DAY_CLOCK)
        asset = provision_asset()
        event = open_safety_event(
            asset["id"],
            event_type="OFFGAS_DETECTED",
            severity="CRITICAL",
            detected_max_cell_temp_c=58.0,
            headers=make_control_room_headers("cro_1"),
        )
        return asset, event

    def test_a_critical_non_runaway_event_alarms_and_suspends_the_plant(self):
        """`CRITICAL` on a non-runaway type imposes `ALARM`, which suspends the market.

        PRD: "Link two fires because the recomputed posture is `ALARM` or `LOCKOUT`: the asset's `market_state` moves `AVAILABLE → SUSPENDED`, `suspension_reason` becomes `SAFETY_ALARM` when the posture is `ALARM` and `SAFETY_LOCKOUT` when it is `LOCKOUT`, and `suspended_at` records the current logical instant."

        Design: Corner/errors/critical_event_close_requires_full_emergency_acknowledgement
        """
        asset, event = self._alarmed_asset()

        assert event["imposed_safety_state"] == "ALARM"
        after = refresh_asset(asset["id"])
        assert after["safety_state"] == "ALARM"
        assert after["market_state"] == "SUSPENDED"
        assert after["suspension_reason"] == "SAFETY_ALARM"

    def test_a_bare_closure_of_a_critical_event_is_refused(self):
        """With no acknowledgement at all the closure cannot proceed.

        PRD: "For an event whose `severity` is `CRITICAL` all three are mandatory: `emergency_response_ack_at` must be supplied, `responder_cleared` must be true, and `emergency_ack_agencies` must name at least one agency, or the closure is refused with `ERR_EMERGENCY_ACK_REQUIRED` (HTTP 422)."

        Design: Corner/errors/critical_event_close_requires_full_emergency_acknowledgement
        """
        _, event = self._alarmed_asset()

        validate_error(
            api_client.close_safety_event(event["id"], CLOSING_OFFICER),
            "ERR_EMERGENCY_ACK_REQUIRED",
            expected_status=422,
        )
        assert refresh_safety_event(event["id"])["status"] == "OPEN"

    def test_an_uncleared_responder_still_blocks_the_closure(self):
        """The acknowledgement timestamp alone is not enough.

        PRD: "For an event whose `severity` is `CRITICAL` all three are mandatory: `emergency_response_ack_at` must be supplied, `responder_cleared` must be true, and `emergency_ack_agencies` must name at least one agency, or the closure is refused with `ERR_EMERGENCY_ACK_REQUIRED` (HTTP 422)."

        Design: Corner/errors/critical_event_close_requires_full_emergency_acknowledgement
        """
        _, event = self._alarmed_asset()

        validate_error(
            api_client.close_safety_event(
                event["id"],
                CLOSING_OFFICER,
                {
                    "emergency_response_ack_at": self.ACK_AT,
                    "emergency_ack_agencies": [self.AGENCY],
                    "responder_cleared": False,
                },
            ),
            "ERR_EMERGENCY_ACK_REQUIRED",
            expected_status=422,
        )
        assert refresh_safety_event(event["id"])["status"] == "OPEN"

    def test_an_empty_agency_list_still_blocks_the_closure(self):
        """The agency list must name at least one coordinating body.

        PRD: "For an event whose `severity` is `CRITICAL` all three are mandatory: `emergency_response_ack_at` must be supplied, `responder_cleared` must be true, and `emergency_ack_agencies` must name at least one agency, or the closure is refused with `ERR_EMERGENCY_ACK_REQUIRED` (HTTP 422)."

        Design: Corner/errors/critical_event_close_requires_full_emergency_acknowledgement
        """
        _, event = self._alarmed_asset()

        validate_error(
            api_client.close_safety_event(
                event["id"],
                CLOSING_OFFICER,
                {
                    "emergency_response_ack_at": self.ACK_AT,
                    "emergency_ack_agencies": [],
                    "responder_cleared": True,
                },
            ),
            "ERR_EMERGENCY_ACK_REQUIRED",
            expected_status=422,
        )
        assert refresh_safety_event(event["id"])["status"] == "OPEN"

    def test_a_complete_acknowledgement_returns_the_plant_to_market(self):
        """All three parts supplied, and the market axis comes back with the posture.

        PRD: "Whenever the recomputed posture is neither `ALARM` nor `LOCKOUT` and the asset was suspended, `market_state` moves `SUSPENDED → AVAILABLE`, `suspension_reason` and `suspended_at` return to null, and every capacity obligation of this asset whose `accrual_started_at` is not null closes its accrual: `unavailable_hours` becomes its previous value plus the number of hours between `accrual_started_at` and the current logical instant, rounded half up to 2 decimal places, and `accrual_started_at` returns to null."

        Design: Corner/errors/critical_event_close_requires_full_emergency_acknowledgement
        """
        asset, event = self._alarmed_asset()

        closed = validate_success(
                api_client.close_safety_event(
                    event["id"],
                    CLOSING_OFFICER,
                    {
                        "emergency_response_ack_at": self.ACK_AT,
                        "emergency_ack_agencies": [
                            self.AGENCY,
                            "State Utility Commission",
                        ],
                        "responder_cleared": True,
                    },
                )
            )

        assert closed["status"] == "CLOSED"
        after = refresh_asset(asset["id"])
        assert after["safety_state"] == "NORMAL"
        assert after["market_state"] == "AVAILABLE"
        assert after["suspension_reason"] is None
