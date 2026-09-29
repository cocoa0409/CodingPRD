"""Maintenance windows: acknowledged risk first, then buffered exclusivity.

Approving planned work runs a safety check against the request body before it runs
a temporal check against the schedule, and the temporal check works on closed
intervals widened by a thirty-minute change buffer on both sides.
"""

from test_helpers import (
    SHIFT_LEAD_HEADERS,
    SHIFT_LEAD_USER_ID,
    ApiErrorId,
    advance_clock,
    assert_circuit_posture,
    build_ewt_two_leg,
    build_wbf_circuit,
    create_carrier,
    create_circuit,
    propose_window,
    read_circuit,
    read_window,
    review_window,
    set_window_state,
    validate_error,
    window_review_payload,
)


def _approve(api, window_id: str, risk_acknowledged: bool):
    """Attempt an approval and hand back the raw response for either outcome."""
    return api.review_maintenance_window(
        window_id,
        window_review_payload("APPROVED", risk_acknowledged=risk_acknowledged),
        SHIFT_LEAD_HEADERS,
    )


class TestReviewCheckOrder:
    """The redundancy acknowledgement is demanded before the schedule is consulted."""

    def test_unacknowledged_redundancy_risk_outranks_the_schedule_conflict(self, api):
        """Both conditions hold, and the refusal names the risk, not the overlap.

        PRD 3.7: "If for any such path that projected count is at or below the path's `min_surviving_legs`, then `risk_acknowledged` must be true in the request body, and an approval without it is refused with `ERR_REDUNDANCY_RISK_UNACKNOWLEDGED`."
        PRD 3.7: "Then the redundancy check runs: for every application path that has an `ACTIVE` hop referencing the window's circuit, the reviewer's projected leg health is computed as the number of legs in which every `ACTIVE` hop's target currently counts as up *and* no `ACTIVE` hop references the window's circuit — in other words, how many legs would still be healthy with this circuit taken out."

        Design: Difficulty/priority_pair_validation_conflict/window_review_redundancy_risk_beats_window_overlap
        """
        state = build_ewt_two_leg(api, "2026-08-11T00:00:00Z")
        approved = propose_window(
            api,
            state["circuit_a_id"],
            "2026-08-11T02:00:00Z",
            "2026-08-11T03:00:00Z",
            origin="CARRIER_NOTIFIED",
            suppresses_monitoring=True,
            carrier_id=state["carrier_id"],
        )
        review_window(
            api, approved["id"], "APPROVED", risk_acknowledged=True,
            user_id=SHIFT_LEAD_USER_ID,
        )

        candidate = propose_window(
            api,
            state["circuit_a_id"],
            "2026-08-11T03:20:00Z",
            "2026-08-11T04:00:00Z",
            origin="INTERNAL_CHANGE",
            suppresses_monitoring=True,
        )

        validate_error(
            _approve(api, candidate["id"], False),
            ApiErrorId.ERR_REDUNDANCY_RISK_UNACKNOWLEDGED,
        )

        stored = read_window(api, candidate["id"])
        assert stored["state"] == "PROPOSED", (
            f"the refused review leaves the window proposed, got {stored['state']}"
        )
        assert stored["risk_acknowledged"] is False, (
            "a refused review persists no acknowledgement"
        )
        assert stored["approved_by_user_id"] is None, "no reviewer of record is stamped"
        assert read_window(api, approved["id"])["state"] == "APPROVED", (
            "the already-approved window is untouched by the refusal"
        )

    def test_acknowledging_the_risk_exposes_the_buffered_conflict_underneath(self, api):
        """The identical request with the risk owned now fails on exclusivity instead.

        PRD 3.7: "Finally the exclusivity check runs against other windows on the same circuit whose `state` is `APPROVED` or `IN_PROGRESS`, using a buffer of 30 minutes on both sides: approval is refused when the candidate window starts before an existing window's `window_end` plus 30 minutes *and* that existing window starts before the candidate's `window_end` plus 30 minutes."
        PRD 3.7: "A refusal is `ERR_WINDOW_OVERLAP`."

        Design: Difficulty/priority_pair_validation_conflict/window_review_redundancy_risk_beats_window_overlap
        """
        state = build_ewt_two_leg(api, "2026-08-11T00:00:00Z")
        approved = propose_window(
            api,
            state["circuit_a_id"],
            "2026-08-11T02:00:00Z",
            "2026-08-11T03:00:00Z",
            origin="CARRIER_NOTIFIED",
            suppresses_monitoring=True,
            carrier_id=state["carrier_id"],
        )
        review_window(
            api, approved["id"], "APPROVED", risk_acknowledged=True,
            user_id=SHIFT_LEAD_USER_ID,
        )
        candidate = propose_window(
            api,
            state["circuit_a_id"],
            "2026-08-11T03:20:00Z",
            "2026-08-11T04:00:00Z",
            origin="INTERNAL_CHANGE",
            suppresses_monitoring=True,
        )
        validate_error(
            _approve(api, candidate["id"], False),
            ApiErrorId.ERR_REDUNDANCY_RISK_UNACKNOWLEDGED,
        )

        validate_error(
            _approve(api, candidate["id"], True), ApiErrorId.ERR_WINDOW_OVERLAP
        )

        stored = read_window(api, candidate["id"])
        assert stored["state"] == "PROPOSED", (
            f"neither refusal approved the window, got {stored['state']}"
        )
        assert stored["approved_by_user_id"] is None, (
            "no reviewer of record survives either refusal"
        )
        assert read_window(api, approved["id"])["state"] == "APPROVED", (
            "the incumbent window keeps its slot"
        )
        assert_circuit_posture(
            read_circuit(api, state["circuit_a_id"]), monitoring_state="MONITORED"
        )


class TestChangeBufferBoundaries:
    """One circuit's schedule is a set of closed intervals widened by 30 minutes."""

    def _isolated_circuit_with_approved_window(self, api) -> dict:
        """A circuit with no path wiring, so only the temporal rule can bite."""
        state = build_wbf_circuit(
            api,
            "2026-08-13T00:00:00Z",
            circuit_identifier="WBF-CKT-4002",
            site_z_code="PHX01",
            bandwidth_mbps=500,
            mrc_cents=350000,
        )
        incumbent = propose_window(
            api,
            state["circuit_id"],
            "2026-08-13T02:00:00Z",
            "2026-08-13T03:00:00Z",
            origin="CARRIER_NOTIFIED",
            suppresses_monitoring=True,
            carrier_id=state["carrier_id"],
        )
        state["incumbent"] = review_window(
            api, incumbent["id"], "APPROVED", risk_acknowledged=False,
            user_id=SHIFT_LEAD_USER_ID,
        )
        state["incumbent_id"] = incumbent["id"]
        return state

    def test_a_window_inside_the_buffer_is_refused(self, api):
        """A start twenty minutes after the incumbent's end is still inside the buffer.

        PRD 3.7: "Finally the exclusivity check runs against other windows on the same circuit whose `state` is `APPROVED` or `IN_PROGRESS`, using a buffer of 30 minutes on both sides: approval is refused when the candidate window starts before an existing window's `window_end` plus 30 minutes *and* that existing window starts before the candidate's `window_end` plus 30 minutes."

        Design: Difficulty/resource_temporal_overlap/maintenance_windows_buffered_closed_intervals_per_circuit
        """
        state = self._isolated_circuit_with_approved_window(api)
        candidate = propose_window(
            api,
            state["circuit_id"],
            "2026-08-13T03:20:00Z",
            "2026-08-13T04:00:00Z",
            suppresses_monitoring=True,
        )

        validate_error(
            _approve(api, candidate["id"], False), ApiErrorId.ERR_WINDOW_OVERLAP
        )

        stored = read_window(api, candidate["id"])
        assert stored["state"] == "PROPOSED", (
            f"the conflicting window is not approved, got {stored['state']}"
        )
        assert stored["approved_by_user_id"] is None, "no approval was stamped"
        assert read_window(api, state["incumbent_id"])["state"] == "APPROVED", (
            "the incumbent window is unaffected"
        )

    def test_a_window_that_merely_touches_the_incumbent_is_refused(self, api):
        """Starting at the exact instant the incumbent ends is a conflict by design.

        PRD 3.7: "Two consequences follow from that arithmetic and both are intended: windows separated by exactly 30 minutes of quiet do **not** conflict, while windows that merely touch — one starting at the instant the other ends — **do** conflict."

        Design: Difficulty/resource_temporal_overlap/maintenance_windows_buffered_closed_intervals_per_circuit
        """
        state = self._isolated_circuit_with_approved_window(api)
        touching = propose_window(
            api,
            state["circuit_id"],
            "2026-08-13T03:00:00Z",
            "2026-08-13T03:40:00Z",
            suppresses_monitoring=True,
        )

        validate_error(
            _approve(api, touching["id"], False), ApiErrorId.ERR_WINDOW_OVERLAP
        )

        stored = read_window(api, touching["id"])
        assert stored["state"] == "PROPOSED", (
            f"a touching window stays proposed, got {stored['state']}"
        )
        assert stored["window_start"].startswith("2026-08-13T03:00:00"), (
            "the refused window keeps the bounds it was proposed with"
        )

    def test_a_gap_of_exactly_thirty_minutes_clears_the_buffer(self, api):
        """Exactly thirty minutes of quiet is enough, so the approval succeeds.

        PRD 3.7: "Approving moves the window `PROPOSED → APPROVED`, stamps `approved_by_user_id` and persists the supplied `risk_acknowledged`; rejecting moves it `PROPOSED → REJECTED`, which is terminal, has no effect on any schedule, and still records the reviewer of record in `approved_by_user_id`."
        PRD 3.7: "Two consequences follow from that arithmetic and both are intended: windows separated by exactly 30 minutes of quiet do **not** conflict, while windows that merely touch — one starting at the instant the other ends — **do** conflict."

        Design: Difficulty/resource_temporal_overlap/maintenance_windows_buffered_closed_intervals_per_circuit
        """
        state = self._isolated_circuit_with_approved_window(api)
        clear_of_buffer = propose_window(
            api,
            state["circuit_id"],
            "2026-08-13T03:30:00Z",
            "2026-08-13T04:30:00Z",
            suppresses_monitoring=True,
        )

        approved = review_window(
            api,
            clear_of_buffer["id"],
            "APPROVED",
            risk_acknowledged=False,
            user_id=SHIFT_LEAD_USER_ID,
        )

        assert approved["state"] == "APPROVED", (
            f"a 30-minute gap clears the buffer, got {approved['state']}"
        )
        assert approved["approved_by_user_id"] == SHIFT_LEAD_USER_ID, (
            "the approving lead is recorded as the reviewer of record"
        )
        assert approved["risk_acknowledged"] is False, (
            "an unwired circuit needs no risk acknowledgement, and none was persisted"
        )
        assert read_window(api, state["incumbent_id"])["state"] == "APPROVED", (
            "both windows now hold approved slots on the same circuit"
        )


class TestCancelledWindowIsTerminal:
    """A cancelled window can never be reviewed back into the schedule."""

    def test_reviewing_a_cancelled_window_is_refused_on_state(self, api):
        """The state check fires before the redundancy and exclusivity checks.

        PRD 3.7: "Cancellation is available from `PROPOSED` or from `APPROVED`, is terminal, and if the window had already suppressed monitoring that suppression is reversed; any other originating state is `ERR_WINDOW_STATE_INVALID`."
        PRD 3.7: "The window must be in `PROPOSED`, otherwise `ERR_WINDOW_STATE_INVALID`."

        Design: Corner/state_machines/corner_window_review_after_cancellation_rejected
        """
        advance_clock(api, "2026-08-16T00:00:00Z")
        carrier = create_carrier(api, name="Plainfield Telecom", carrier_code="PFT")
        circuit = create_circuit(
            api,
            carrier["id"],
            carrier_circuit_identifier="PFT-CKT-9004",
            site_a_code="CHI01",
            site_z_code="IND01",
            bandwidth_mbps=500,
            mrc_cents=275000,
            monitoring_state="MONITORED",
        )
        window = propose_window(
            api,
            circuit["id"],
            "2026-08-16T02:00:00Z",
            "2026-08-16T03:00:00Z",
            suppresses_monitoring=True,
        )

        cancelled = set_window_state(api, window["id"], "CANCELLED")
        assert cancelled["state"] == "CANCELLED", (
            f"the window is cancelled before any review, got {cancelled['state']}"
        )

        validate_error(
            _approve(api, window["id"], True), ApiErrorId.ERR_WINDOW_STATE_INVALID
        )

        stored = read_window(api, window["id"])
        assert stored["state"] == "CANCELLED", (
            f"cancellation is terminal, got {stored['state']}"
        )
        assert stored["approved_by_user_id"] is None, (
            "the refused review records no reviewer"
        )
        assert stored["risk_acknowledged"] is False, (
            "the refused review persisted nothing from its body"
        )
        assert_circuit_posture(
            read_circuit(api, circuit["id"]), monitoring_state="MONITORED"
        )
