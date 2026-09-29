"""Two gates that live on a different row from the one being written."""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_cents,
    assert_instant,
    assert_nurse_load,
    assert_whole_minutes,
)


@pytest.fixture
def weekend_practice_with_a_draft_window(world):
    """A Saturday clock and a coverage window still sitting in DRAFT."""
    world.bootstrap(clock="2026-08-01T14:30:00Z")
    window = world.create_coverage_window(
        start_utc="2026-08-01T00:00:00Z",
        end_utc="2026-08-08T00:00:00Z",
        coverage_kind="WEEKEND",
    )
    return window


class TestAfterHoursIntakeIsGatedOnTheCoverageWindow:
    def test_a_draft_window_does_not_authorize_a_weekend_call(
        self, world, weekend_practice_with_a_draft_window
    ):
        """PRD §3.3: "the server looks for a window belonging to that practice whose
        `status` is `ACTIVE` and whose interval contains the logical clock, meaning
        the clock is at or after `start_utc` and strictly before `end_utc`."

        Design: Difficulty/cross_entity_state_dependency/after_hours_intake_is_gated_on_a_third_partys_coverage_window_being_active
        """
        window = weekend_practice_with_a_draft_window
        assert window["status"] == "DRAFT"

        response = world.api.create_triage_call(
            f.triage_call_payload(world.practice_id), world.intake
        )

        validate_error(response, ApiErrorId.ERR_NO_ACTIVE_COVERAGE, 409)

    def test_no_call_row_is_created_by_the_refused_intake(
        self, world, weekend_practice_with_a_draft_window
    ):
        """PRD §3.3: "If no such window exists, the call is refused with
        `ERR_NO_ACTIVE_COVERAGE` and no row is created."

        Design: Difficulty/cross_entity_state_dependency/after_hours_intake_is_gated_on_a_third_partys_coverage_window_being_active
        """
        world.api.create_triage_call(
            f.triage_call_payload(world.practice_id), world.intake
        )

        _, meta = validate_paginated(world.api.list_triage_calls(world.admin))
        assert meta["total_count"] == 0

    def test_activating_the_window_lets_the_identical_request_through(
        self, world, weekend_practice_with_a_draft_window
    ):
        """PRD §3.3: "the same practice hours on a Saturday give an after-hours call
        at 14:30 anyway when the weekend flag is set".

        Design: Difficulty/cross_entity_state_dependency/after_hours_intake_is_gated_on_a_third_partys_coverage_window_being_active
        """
        window = weekend_practice_with_a_draft_window
        world.api.create_triage_call(
            f.triage_call_payload(world.practice_id), world.intake
        )

        world.activate_coverage_window(window["id"])
        call = world.open_call()

        assert call["status"] == "INTAKE"
        assert call["is_after_hours"] is True
        assert call["patient_id"] is None, "identification has not happened yet"
        _, meta = validate_paginated(world.api.list_triage_calls(world.admin))
        assert meta["total_count"] == 1, "only the second attempt wrote a row"

    def test_the_activated_window_carries_no_suspension(
        self, world, weekend_practice_with_a_draft_window
    ):
        """PRD §3.3: "The window's `coverage_kind` is contractual metadata only and
        never narrows this check — any `ACTIVE` window of any kind satisfies it."

        Design: Difficulty/cross_entity_state_dependency/after_hours_intake_is_gated_on_a_third_partys_coverage_window_being_active
        """
        window = weekend_practice_with_a_draft_window

        world.activate_coverage_window(window["id"])

        activated = world.coverage_window(window["id"])
        assert activated["status"] == "ACTIVE"
        assert activated["suspend_reason"] is None
        assert activated["coverage_kind"] == "WEEKEND"
        assert activated["version"] > window["version"]


@pytest.fixture
def emergency_call_awaiting_handoff(world):
    """A call whose acuity of exactly 85 forces a warm transfer before closure."""
    world.bootstrap(clock="2026-08-03T14:30:00Z", protocol={"base_severity": 61})
    call, assessment, disposition = world.dispositioned_call(
        "EMERGENCY_911", "nurse_a", red_flag_count=3
    )
    return call, assessment, disposition


class TestCallCompletionIsGatedOnTheWarmTransferAggregate:
    def test_closing_before_any_handoff_is_refused(
        self, world, emergency_call_awaiting_handoff
    ):
        """PRD §3.9: "if the call's `requires_warm_transfer` is true, then some warm
        transfer for that call must have reached `HANDOFF_COMPLETE`, and otherwise
        the request is refused with `ERR_WARM_TRANSFER_INCOMPLETE`."

        Design: Difficulty/cross_entity_state_dependency/call_completion_is_gated_on_a_separate_warm_transfer_aggregate_reaching_handoff_complete
        """
        call, assessment, _ = emergency_call_awaiting_handoff
        assert assessment["acuity_score"] == 85
        assert call["requires_warm_transfer"] is True

        response = world.api.complete_call(
            call["id"], f.complete_payload(13), world.nurse_headers("nurse_a")
        )

        validate_error(response, ApiErrorId.ERR_WARM_TRANSFER_INCOMPLETE, 409)

    def test_a_rejected_transfer_does_not_open_the_closure_gate(
        self, world, emergency_call_awaiting_handoff
    ):
        """PRD §3.7: "On refusal the transfer moves
        `LOCATION_CONFIRMED → REJECTED_BY_PSAP`, `psap_incident_number` stays
        absent, and — this is the part that matters clinically — the call's
        `requires_warm_transfer` stays true, so the call still cannot be completed
        until a fresh transfer reaches `HANDOFF_COMPLETE`."

        Design: Difficulty/cross_entity_state_dependency/call_completion_is_gated_on_a_separate_warm_transfer_aggregate_reaching_handoff_complete
        """
        call, _, _ = emergency_call_awaiting_handoff
        first = world.open_warm_transfer(call["id"], "nurse_a")
        world.confirm_location(first["id"], "nurse_a", 90)

        rejected = world.psap_response(first["id"], accepted=False)

        assert rejected["status"] == "REJECTED_BY_PSAP"
        assert rejected["psap_incident_number"] is None
        assert world.call(call["id"])["requires_warm_transfer"] is True
        response = world.api.complete_call(
            call["id"], f.complete_payload(13), world.nurse_headers("nurse_a")
        )
        validate_error(response, ApiErrorId.ERR_WARM_TRANSFER_INCOMPLETE, 409)

    def test_a_second_transfer_reaching_handoff_lets_the_call_close_and_bill(
        self, world, emergency_call_awaiting_handoff
    ):
        """PRD §3.7: "it also stamps `warm_transfer_completed_at` on the call with
        the current logical-clock instant and increases the call's `version` by one.
        That terminal state is the precondition for closing the call itself."

        Design: Difficulty/cross_entity_state_dependency/call_completion_is_gated_on_a_separate_warm_transfer_aggregate_reaching_handoff_complete
        """
        call, _, _ = emergency_call_awaiting_handoff
        first = world.open_warm_transfer(call["id"], "nurse_a")
        world.confirm_location(first["id"], "nurse_a", 90)
        world.psap_response(first["id"], accepted=False)

        world.full_warm_transfer(
            call["id"],
            "nurse_a",
            psap_center_code="SF-PSAP-02",
            location_source="DEVICE_GPS",
        )
        closed = world.complete_call(call["id"], "nurse_a", handle_minutes=13)

        assert closed["status"] == "CLOSED"
        assert_instant(
            closed["warm_transfer_completed_at"],
            "2026-08-03T14:30:00Z",
            "warm_transfer_completed_at",
        )
        assert_whole_minutes(closed["billable_minutes"], 15, "billable_minutes")
        assert_cents(closed["advice_fee_cents"], 63, "advice_fee_cents")

    def test_both_transfers_survive_in_their_own_terminal_states(
        self, world, emergency_call_awaiting_handoff
    ):
        """PRD §3.7: "Only a transfer that ended at `REJECTED_BY_PSAP` frees the slot
        for a second attempt."

        Design: Difficulty/cross_entity_state_dependency/call_completion_is_gated_on_a_separate_warm_transfer_aggregate_reaching_handoff_complete
        """
        call, _, _ = emergency_call_awaiting_handoff
        first = world.open_warm_transfer(call["id"], "nurse_a")
        world.confirm_location(first["id"], "nurse_a", 90)
        world.psap_response(first["id"], accepted=False)
        second = world.full_warm_transfer(
            call["id"],
            "nurse_a",
            psap_center_code="SF-PSAP-02",
            location_source="DEVICE_GPS",
        )
        world.complete_call(call["id"], "nurse_a", handle_minutes=13)

        rejected = world.warm_transfer(first["id"])
        handed_off = world.warm_transfer(second["id"])

        assert rejected["status"] == "REJECTED_BY_PSAP"
        assert rejected["psap_incident_number"] is None
        assert rejected["location_confidence_pct"] == 90
        assert handed_off["status"] == "HANDOFF_COMPLETE"
        assert handed_off["location_verified_by"] == world.nurse_id("nurse_a")
        assert handed_off["psap_incident_number"] == "SFFD-2026-0001"
        _, meta = validate_paginated(
            world.api.list_call_warm_transfers(call["id"], world.admin)
        )
        assert meta["total_count"] == 2

    def test_closing_the_emergency_call_releases_both_nurse_counters(
        self, world, emergency_call_awaiting_handoff
    ):
        """PRD §2.9: "`Nurse.pending_high_risk_count` is the number of calls
        assigned to that nurse that require a warm transfer and whose `status` is
        `ASSIGNED`, `ASSESSING` or `DISPOSITIONED`."

        Design: Difficulty/cross_entity_state_dependency/call_completion_is_gated_on_a_separate_warm_transfer_aggregate_reaching_handoff_complete
        """
        call, _, _ = emergency_call_awaiting_handoff
        assert_nurse_load(
            world.nurse("nurse_a"), active=1, high_risk=1, eligibility="ON_ROTATION"
        )
        world.full_warm_transfer(call["id"], "nurse_a")

        world.complete_call(call["id"], "nurse_a", handle_minutes=13)

        assert_nurse_load(
            world.nurse("nurse_a"), active=0, high_risk=0, eligibility="ON_ROTATION"
        )
        assert_cents(
            world.practice()["advice_fee_accrued_cents"], 63, "advice_fee_accrued_cents"
        )
