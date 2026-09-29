"""Deliberate failover verification: reservations, start guards and attestation.

A failover test is a controlled outage, so it is reserved against the whole
carrier rather than the leg, it refuses to start while any planned work touches
the topology, and a failure is recorded against the legs that survived.
"""

from test_helpers import (
    ANALYST_HEADERS,
    SHIFT_LEAD_HEADERS,
    SHIFT_LEAD_USER_ID,
    ApiErrorId,
    advance_clock,
    assert_circuit_posture,
    assert_page,
    assert_path_posture,
    build_approved_carrier_window,
    build_ewt_two_leg,
    failover_test_payload,
    read_circuit,
    read_path,
    read_window,
    record_failover_result,
    schedule_failover_test,
    set_window_state,
    start_failover_test,
    validate_error,
    validate_paginated,
    validate_success,
)


def _read_test(api, path_id: str, test_id: str) -> dict:
    """Read one reservation back through the path's failover-test collection."""
    rows, _ = validate_paginated(
        api.list_path_failover_tests(path_id, SHIFT_LEAD_HEADERS)
    )
    matches = [row for row in rows if row["id"] == test_id]
    assert matches, f"failover test {test_id} is missing from the path's collection"
    return matches[0]


def _blocked_start_scenario(api) -> dict:
    """A LEG_A test and an approved, never-started window on the LEG_B circuit."""
    state = build_ewt_two_leg(api, "2026-08-11T05:00:00Z")
    window = build_approved_carrier_window(
        api,
        state["circuit_b_id"],
        state["carrier_id"],
        "2026-08-11T06:00:00Z",
        "2026-08-11T07:00:00Z",
        suppresses_monitoring=False,
        risk_acknowledged=True,
    )
    test = schedule_failover_test(
        api,
        state["path_id"],
        "LEG_A",
        "2026-08-11T06:00:00Z",
        "2026-08-11T07:00:00Z",
        user_id=SHIFT_LEAD_USER_ID,
    )
    advance_clock(api, "2026-08-11T06:30:00Z")
    state["window_id"] = window["window_id"]
    state["test_id"] = test["id"]
    return state


class TestStartBlockedByWorkOnTheSiblingLeg:
    """The blocking window is on a leg the test never intended to touch."""

    def test_an_approved_window_on_the_untested_leg_refuses_the_start(self, api):
        """The posture guard passes and the topology sweep still refuses the start.

        PRD 3.7: "Starting a test is guarded four times, in this order: the test must be in `SCHEDULED`, otherwise `ERR_TEST_STATE_INVALID`; the path's `posture` must be exactly `PROTECTED`, since deliberately failing a leg of an already-degraded path is how a test becomes an outage, otherwise `ERR_PATH_NOT_PROTECTED`; no maintenance window in `APPROVED` or `IN_PROGRESS` may cover the current instant on any circuit reachable from the path's `ACTIVE` hops, otherwise `ERR_MAINTENANCE_IN_EFFECT`; and the current clock instant must be at or after `scheduled_start` and strictly before `scheduled_end`, otherwise `ERR_TEST_WINDOW_NOT_IN_EFFECT`."

        Design: Difficulty/cross_entity_state_dependency/failover_start_blocked_by_approved_window_on_the_sibling_leg
        """
        state = _blocked_start_scenario(api)

        assert_path_posture(
            read_path(api, state["path_id"]),
            posture="PROTECTED",
            active_leg_count=2,
            healthy_leg_count=2,
        )

        validate_error(
            api.start_failover_test(state["test_id"], {}, ANALYST_HEADERS),
            ApiErrorId.ERR_MAINTENANCE_IN_EFFECT,
        )

        stored = _read_test(api, state["path_id"], state["test_id"])
        assert stored["state"] == "SCHEDULED", (
            f"the refused start leaves the reservation scheduled, got {stored['state']}"
        )
        assert stored["surviving_leg_count"] is None, (
            "nothing was observed, so no leg count is recorded"
        )
        assert stored["attested_by_user_id"] is None, (
            "a refused start attests nothing"
        )
        assert_path_posture(
            read_path(api, state["path_id"]),
            posture="PROTECTED",
            healthy_leg_count=2,
        )

    def test_cancelling_the_window_lets_the_identical_start_through(self, api):
        """With the planned work withdrawn the test runs and the path loses redundancy.

        PRD 3.7: "Cancellation is available from `PROPOSED` or from `APPROVED`, is terminal, and if the window had already suppressed monitoring that suppression is reversed; any other originating state is `ERR_WINDOW_STATE_INVALID`."
        PRD 3.7: "A started test moves `SCHEDULED → IN_PROGRESS`, and for its duration the circuits of the tested leg are treated as unavailable so that the path's `posture` re-derives against the surviving legs; the test's `version` and each affected path's `version` advance by 1."

        Design: Difficulty/cross_entity_state_dependency/failover_start_blocked_by_approved_window_on_the_sibling_leg
        """
        state = _blocked_start_scenario(api)
        validate_error(
            api.start_failover_test(state["test_id"], {}, ANALYST_HEADERS),
            ApiErrorId.ERR_MAINTENANCE_IN_EFFECT,
        )

        cancelled = set_window_state(api, state["window_id"], "CANCELLED")
        assert cancelled["state"] == "CANCELLED", (
            f"the planned work is withdrawn, got {cancelled['state']}"
        )
        assert read_window(api, state["window_id"])["state"] == "CANCELLED", (
            "cancellation is terminal"
        )
        assert_circuit_posture(
            read_circuit(api, state["circuit_b_id"]), monitoring_state="MONITORED"
        )

        running = start_failover_test(api, state["test_id"])
        assert running["state"] == "IN_PROGRESS", (
            f"the same start now succeeds, got {running['state']}"
        )
        assert set(running["carrier_id_set"]) == {state["carrier_id"]}, (
            "both legs ride the same carrier, so the blast radius is one carrier"
        )
        assert_path_posture(
            read_path(api, state["path_id"]),
            posture="DEGRADED_NO_REDUNDANCY",
            active_leg_count=2,
            healthy_leg_count=1,
        )


class TestPerCarrierReservationCeiling:
    """One in-flight reservation per carrier, on unbuffered half-open intervals."""

    def _first_reservation(self, api) -> dict:
        """A LEG_A reservation from 01:00 to 02:00, with the clock still at 00:30."""
        state = build_ewt_two_leg(api, "2026-08-14T00:30:00Z")
        state["first_test"] = schedule_failover_test(
            api,
            state["path_id"],
            "LEG_A",
            "2026-08-14T01:00:00Z",
            "2026-08-14T02:00:00Z",
            user_id=SHIFT_LEAD_USER_ID,
        )
        return state

    def test_a_straddling_reservation_on_the_other_leg_is_refused(self, api):
        """A different leg is no defence: the carrier already has a test reserved.

        PRD 3.7: "The server derives `carrier_id_set`, the distinct carrier identifiers of the circuits reachable from the path's `ACTIVE` hops, and uses it to limit blast radius: at most **one** test may be reserved per carrier at a time, so scheduling is refused with `ERR_FAILOVER_TEST_CONFLICT` when at least one existing test in `SCHEDULED` or `IN_PROGRESS` both strictly overlaps the requested interval — each interval including its start and excluding its end — and shares at least one carrier with the requested path's `carrier_id_set`."

        Design: Difficulty/resource_temporal_overlap/failover_tests_unbuffered_half_open_ceiling_per_carrier
        """
        state = self._first_reservation(api)

        validate_error(
            api.create_failover_test(
                failover_test_payload(
                    state["path_id"],
                    "LEG_B",
                    "2026-08-14T01:30:00Z",
                    "2026-08-14T02:30:00Z",
                ),
                SHIFT_LEAD_HEADERS,
            ),
            ApiErrorId.ERR_FAILOVER_TEST_CONFLICT,
        )

        _, meta = validate_paginated(
            api.list_path_failover_tests(state["path_id"], SHIFT_LEAD_HEADERS)
        )
        assert_page(meta, total_count=1)
        surviving = _read_test(api, state["path_id"], state["first_test"]["id"])
        assert surviving["state"] == "SCHEDULED", (
            f"the incumbent reservation is untouched, got {surviving['state']}"
        )
        assert surviving["tested_leg_group"] == "LEG_A", (
            "the refused request did not rewrite the incumbent's leg"
        )

    def test_a_reservation_starting_when_the_first_ends_is_accepted(self, api):
        """Adjacency is deliberately legal here, unlike the buffered window rule.

        PRD 3.7: "Adjacency never conflicts here: an existing test ending exactly when the new one starts is fine, in deliberate contrast to the buffered maintenance rule above."
        PRD 3.7: "A scheduled test starts in `SCHEDULED` with `scheduled_by_user_id` recording the acting `X-User-ID`, `surviving_leg_count` null and `attested_by_user_id` null."

        Design: Difficulty/resource_temporal_overlap/failover_tests_unbuffered_half_open_ceiling_per_carrier
        """
        state = self._first_reservation(api)
        validate_error(
            api.create_failover_test(
                failover_test_payload(
                    state["path_id"],
                    "LEG_B",
                    "2026-08-14T01:30:00Z",
                    "2026-08-14T02:30:00Z",
                ),
                SHIFT_LEAD_HEADERS,
            ),
            ApiErrorId.ERR_FAILOVER_TEST_CONFLICT,
        )

        adjacent = validate_success(
            api.create_failover_test(
                failover_test_payload(
                    state["path_id"],
                    "LEG_B",
                    "2026-08-14T02:00:00Z",
                    "2026-08-14T03:00:00Z",
                ),
                SHIFT_LEAD_HEADERS,
            ),
            201,
        )["data"]

        assert adjacent["state"] == "SCHEDULED", (
            f"the adjacent reservation is accepted, got {adjacent['state']}"
        )
        assert adjacent["scheduled_by_user_id"] == SHIFT_LEAD_USER_ID, (
            "the scheduling shift lead is recorded on the reservation"
        )
        assert adjacent["surviving_leg_count"] is None, (
            "a reservation observes nothing yet"
        )
        assert adjacent["attested_by_user_id"] is None, (
            "a reservation carries no attestation yet"
        )
        assert set(adjacent["carrier_id_set"]) == {state["carrier_id"]}, (
            "the derived blast radius is the single carrier behind both legs"
        )

        _, meta = validate_paginated(
            api.list_path_failover_tests(state["path_id"], SHIFT_LEAD_HEADERS)
        )
        assert_page(meta, total_count=2)
        assert (
            _read_test(api, state["path_id"], state["first_test"]["id"])["state"]
            == "SCHEDULED"
        ), "neither attempt disturbed the first reservation"


class TestFailedResultNamesTheSurvivingLeg:
    """A failure is a fact about the legs that were carrying the path alone."""

    def test_a_failed_result_flags_the_untested_leg_as_a_single_point_of_failure(
        self, api
    ):
        """LEG_B becomes the single point of failure and the tested leg is handed back.

        PRD 3.7: "A `FAILED` result additionally marks `spof_flag` true on every circuit reachable from the path's `ACTIVE` hops in legs other than the `tested_leg_group` — the test just proved those legs are carrying the path alone — and leaves the path's declared `protection_scheme` unchanged, because the design on paper did not change, only the truth about it."
        PRD 3.7: "Recording any result restores the tested leg to its pre-test availability and re-derives the path's `posture` from live health."
        PRD 3.7: "All three outcomes stamp `attested_by_user_id`."

        Design: Corner/state_machines/corner_failover_failure_marks_surviving_leg_as_spof
        """
        state = build_ewt_two_leg(api, "2026-08-20T00:30:00Z")
        test = schedule_failover_test(
            api,
            state["path_id"],
            "LEG_A",
            "2026-08-20T01:00:00Z",
            "2026-08-20T02:00:00Z",
            user_id=SHIFT_LEAD_USER_ID,
        )

        advance_clock(api, "2026-08-20T01:10:00Z")
        running = start_failover_test(api, test["id"])
        assert running["state"] == "IN_PROGRESS", (
            f"the verification is under way, got {running['state']}"
        )

        failed = record_failover_result(
            api, test["id"], "FAILED", surviving_leg_count=0,
            user_id=SHIFT_LEAD_USER_ID,
        )

        assert failed["state"] == "FAILED", (
            f"the verification is attested as failed, got {failed['state']}"
        )
        assert failed["surviving_leg_count"] == 0, (
            f"the observed count is recorded, got {failed['surviving_leg_count']}"
        )
        assert failed["attested_by_user_id"] == SHIFT_LEAD_USER_ID, (
            "the attesting shift lead is stamped on the result"
        )

        assert_circuit_posture(
            read_circuit(api, state["circuit_b_id"]),
            operational_state="UP",
            spof_flag=True,
        )
        assert_circuit_posture(
            read_circuit(api, state["circuit_a_id"]),
            operational_state="UP",
            spof_flag=False,
        )

        path = read_path(api, state["path_id"])
        assert_path_posture(
            path, posture="PROTECTED", active_leg_count=2, healthy_leg_count=2
        )
        assert path["protection_scheme"] == "ACTIVE_ACTIVE", (
            "the declared design on paper is unchanged by the failure"
        )
