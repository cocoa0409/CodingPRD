"""Reassignment validation paths and interval conflicts (PRD §2.10, §3.5, §3.7)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_main_tariff, place_order, dispatch, register_boat,
    register_endorsed_pilot, launch, board, complete, recall, set_clock,
    get_pilot_fresh, get_assignment_fresh,
    setup_recalled_assignment, setup_two_pilots,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestExplicitPilotValidation:
    def test_error_tonnage_exceeds_endorsement_on_explicit_reassign(self, api):
        """PRD §3.5: "the explicit pilot runs a five-check validation path in
        pinned order: a `CURRENT` endorsement with `expires_at` strictly after
        the clock (`ERR_LICENSE_NOT_CURRENT`), an endorsement `tonnage_cap_gt`
        at least the order's `gt` (`ERR_TONNAGE_EXCEEDS_ENDORSEMENT`), ...".

        P2's CURRENT endorsement caps at 5000 gt while the order is 8000 gt;
        currency passes, tonnage fails.

        Design: Corner/errors/error_tonnage_exceeds_endorsement_on_explicit_reassign
        """
        ctx = setup_recalled_assignment(second_pilot_cap=5000,
                                        second_pilot_class="HARBOR",
                                        order_gt=8000)
        res = api.reassign_assignment(ctx["a2"]["id"], {"pilot_id": ctx["p2"]["id"]},
                                      DISPATCHER)
        validate_error(res, ApiErrorId.ERR_TONNAGE_EXCEEDS_ENDORSEMENT)
        assert get_assignment_fresh(ctx["a2"]["id"])["service_status"] == "RECALLED"

    def test_error_license_not_current_on_explicit_reassign(self, api):
        """PRD §3.5: "a `CURRENT` endorsement with `expires_at` strictly after
        the clock (`ERR_LICENSE_NOT_CURRENT`)" — the first of the five checks.

        P2's only endorsement expired before the default clock.

        Design: Corner/errors/error_license_not_current_on_explicit_reassign
        """
        create_main_tariff()
        p1 = register_endorsed_pilot("Pilot One", "LIC-1")
        p2 = register_endorsed_pilot("Pilot Two", "LIC-2",
                                     expires_at="2026-06-01T00:00:00Z")
        register_boat("Boat A")
        register_boat("Boat B")
        o1 = place_order(vessel_name="MV Big", gt=8000)
        a1 = dispatch(o1["id"], "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")
        # P2 cannot be selector-picked (expired endorsement); force A2 onto P1's
        # calendar is unnecessary — dispatch a second order and recall whoever
        # the selector picked (P1 again: P2 is ineligible).
        o2 = place_order(vessel_name="MV Two", gt=4000, order_type="DEPARTURE",
                         eta="2026-08-11T00:00:00Z")
        a2 = dispatch(o2["id"], "2026-08-11T10:00:00Z", "2026-08-11T11:00:00Z")
        recall(a2["id"])

        res = api.reassign_assignment(a2["id"], {"pilot_id": p2["id"]}, DISPATCHER)
        validate_error(res, ApiErrorId.ERR_LICENSE_NOT_CURRENT)


class TestRestBeatsIntervalConflict:
    def _setup_rest_active_with_overlap(self):
        """P1: UNLIMITED cap 100000; P2: HARBOR cap 5000; one boat.

        A_hist (gt 4000) and A1 (gt 8000) are both dispatched to P1 while
        everyone is rested. A_hist then completes in zero elapsed clock time,
        so P1's rest_until (default clock + 600 min) is still in the future —
        rest ACTIVE. A2 (gt 4000) goes to P2 (P1 ineligible: resting) and is
        recalled. Reassigning A2 to P1 over a window overlapping A1's
        [08-10 10:00, 12:00] violates both rest and interval rules.
        """
        create_main_tariff()
        p1 = register_endorsed_pilot("Pilot One", "LIC-1", tonnage_cap_gt=100000)
        p2 = register_endorsed_pilot("Pilot Two", "LIC-2",
                                     endorsement_class="HARBOR", tonnage_cap_gt=5000)
        boat = register_boat("Boat A")
        oh = place_order(vessel_name="MV Hist", gt=4000, order_type="SHIFT",
                         eta="2026-08-09T00:00:00Z")
        a_hist = dispatch(oh["id"], "2026-08-09T08:00:00Z", "2026-08-09T09:00:00Z")
        o1 = place_order(vessel_name="MV One", gt=8000)
        a1 = dispatch(o1["id"], "2026-08-10T10:00:00Z", "2026-08-10T12:00:00Z")
        assert a_hist["pilot_id"] == p1["id"] and a1["pilot_id"] == p1["id"]
        complete(board(launch(a_hist)), 0, 0)  # zero-minute job -> short rest
        o2 = place_order(vessel_name="MV Two", gt=4000, order_type="DEPARTURE",
                         eta="2026-08-11T00:00:00Z")
        a2 = dispatch(o2["id"], "2026-08-11T10:00:00Z", "2026-08-11T11:00:00Z")
        assert a2["pilot_id"] == p2["id"]
        a2 = recall(a2["id"])
        return p1, p2, boat, a2

    def test_reassign_rest_active_pilot_returns_fatigue_rest_active(self, api):
        """PRD §3.5: "the explicit pilot runs a five-check validation path in
        pinned order: a `CURRENT` endorsement with `expires_at` strictly after
        the clock (`ERR_LICENSE_NOT_CURRENT`), an endorsement `tonnage_cap_gt`
        at least the order's `gt` (`ERR_TONNAGE_EXCEEDS_ENDORSEMENT`), a
        `rest_until` that is null or no later than the clock
        (`ERR_FATIGUE_REST_ACTIVE`), a rolling-duty-plus-new-minutes projection
        within the seven-day ceiling with equality passing
        (`ERR_FATIGUE_DUTY_LIMIT`), and a closed-interval overlap check against
        the pilot's committed assignments (`ERR_PILOT_TIME_CONFLICT`, HTTP 409)."
        PRD §2.8: "Business-safety checks on an explicit reassign pilot are
        evaluated in a pinned order" ahead of the remaining business rules:
        "selector pool emptiness (`ERR_NO_ELIGIBLE_PILOT`, `ERR_NO_ELIGIBLE_BOAT`),
        apprentice gating (`ERR_READINESS_NOT_MET`, `ERR_EXAM_NOT_PASSED`,
        `ERR_APPRENTICE_NOT_ENROLLED`), temporal rules (`ERR_ETA_IN_PAST`,
        `ERR_PILOT_TIME_CONFLICT`, `ERR_BOAT_TIME_CONFLICT`, `ERR_PERIOD_OVERLAP`)".

        The named pilot is simultaneously rest-active and interval-overlapping;
        the rest error surfaces.

        Design: Difficulty/priority_pair_validation_conflict/reassign_fatigue_rest_beats_pilot_time_conflict
        """
        p1, _p2, boat, a2 = self._setup_rest_active_with_overlap()
        res = api.reassign_assignment(a2["id"], {
            "pilot_id": p1["id"], "boat_id": boat["id"],
            "scheduled_start": "2026-08-10T11:00:00Z",
            "scheduled_end": "2026-08-10T13:00:00Z",
        }, DISPATCHER)
        validate_error(res, ApiErrorId.ERR_FATIGUE_REST_ACTIVE)

    def test_rejected_reassign_leaves_assignment_recalled(self, api):
        """PRD §3.5: "Reassignment returns a `RECALLED` assignment to
        `ASSIGNED`." — a rejected reassignment performs no return.

        Design: Difficulty/priority_pair_validation_conflict/reassign_fatigue_rest_beats_pilot_time_conflict
        """
        p1, _p2, boat, a2 = self._setup_rest_active_with_overlap()
        api.reassign_assignment(a2["id"], {
            "pilot_id": p1["id"], "boat_id": boat["id"],
            "scheduled_start": "2026-08-10T11:00:00Z",
            "scheduled_end": "2026-08-10T13:00:00Z",
        }, DISPATCHER)
        after = get_assignment_fresh(a2["id"])
        assert after["service_status"] == "RECALLED"
        assert after["pilot_id"] != p1["id"]


class TestDutyLimitBoundary:
    def _setup_duty_4260_and_recalled(self):
        """P1 accumulates exactly 4260 rolling duty minutes (actual
        2026-08-02T00:00Z -> 2026-08-04T23:00Z); long rest expires at
        2026-08-05T15:00Z and the clock is then set to 2026-08-05T16:00Z so the
        completion sits inside the inclusive 7-day window. A2 (gt 4000, 60-min
        window) is selector-dispatched to P2 and recalled."""
        create_main_tariff()
        p1 = register_endorsed_pilot("Pilot One", "LIC-1", tonnage_cap_gt=100000)
        p2 = register_endorsed_pilot("Pilot Two", "LIC-2",
                                     endorsement_class="HARBOR", tonnage_cap_gt=5000)
        register_boat("Boat A")
        o1 = place_order(vessel_name="MV Long", gt=8000, eta="2026-08-02T00:00:00Z")
        a1 = dispatch(o1["id"], "2026-08-02T00:00:00Z", "2026-08-04T23:00:00Z")
        assert a1["pilot_id"] == p1["id"]
        set_clock("2026-08-02T00:00:00Z")
        board(launch(a1))
        set_clock("2026-08-04T23:00:00Z")
        complete(get_assignment_fresh(a1["id"]), 0, 0)
        assert get_pilot_fresh(p1["id"])["duty_minutes_rolling_7d"] == 4260

        set_clock("2026-08-05T16:00:00Z")
        o2 = place_order(vessel_name="MV Two", gt=4000, order_type="DEPARTURE",
                         eta="2026-08-10T00:00:00Z")
        a2 = dispatch(o2["id"], "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")
        assert a2["pilot_id"] == p2["id"]
        a2 = recall(a2["id"])
        return p1, p2, a2

    def test_duty_projection_exactly_4320_passes(self, api):
        """PRD §3.7: "the pilot is eligible when the projection is at most 4320
        minutes, the association's seven-day ceiling. Equality passes; only a
        strictly-greater projection fails with `ERR_FATIGUE_DUTY_LIMIT` on the
        explicit path".

        4260 accumulated + 60 planned == 4320 exactly: the reassignment is
        accepted.

        Design: Difficulty/boundary_precision_check/fatigue_duty_limit_equality_passes_plus_one_fails
        """
        p1, _p2, a2 = self._setup_duty_4260_and_recalled()
        res = api.reassign_assignment(a2["id"], {"pilot_id": p1["id"]}, DISPATCHER)
        reassigned = validate_success(res, 200)
        assert reassigned["service_status"] == "ASSIGNED"
        assert reassigned["pilot_id"] == p1["id"]
        assert get_pilot_fresh(p1["id"])["duty_minutes_rolling_7d"] == 4260

    def test_duty_projection_4321_rejected(self, api):
        """PRD §3.7: "the pilot is eligible when the projection is at most 4320
        minutes, the association's seven-day ceiling. Equality passes; only a
        strictly-greater projection fails with `ERR_FATIGUE_DUTY_LIMIT` on the
        explicit path".

        4260 accumulated + 61 planned == 4321: strictly greater, rejected.

        Design: Difficulty/boundary_precision_check/fatigue_duty_limit_equality_passes_plus_one_fails
        """
        p1, _p2, a2 = self._setup_duty_4260_and_recalled()
        res = api.reassign_assignment(a2["id"], {
            "pilot_id": p1["id"],
            "scheduled_start": "2026-08-10T10:00:00Z",
            "scheduled_end": "2026-08-10T11:01:00Z",
        }, DISPATCHER)
        validate_error(res, ApiErrorId.ERR_FATIGUE_DUTY_LIMIT)
        assert get_pilot_fresh(p1["id"])["duty_minutes_rolling_7d"] == 4260


class TestPilotClosedInterval:
    def test_pilot_reassign_touching_endpoint_conflicts(self, api):
        """PRD §2.10: "A pilot's committed intervals are **closed** intervals
        with no buffer: a new assignment touching an existing one at an
        endpoint — the new `scheduled_start` equal to an existing
        `scheduled_end` — is a conflict."
        PRD §3.5: "a closed-interval overlap check against the pilot's
        committed assignments (`ERR_PILOT_TIME_CONFLICT`, HTTP 409)".

        P1 already holds [10:00, 12:00]; starting the reassigned window at
        exactly 12:00 collides.

        Design: Difficulty/resource_temporal_overlap/pilot_closed_interval_touching_collides
        """
        ctx = setup_recalled_assignment(second_pilot_cap=100000,
                                        second_pilot_class="UNLIMITED",
                                        order_gt=8000)
        res = api.reassign_assignment(ctx["a2"]["id"], {
            "pilot_id": ctx["p1"]["id"],
            "scheduled_start": "2026-08-10T12:00:00Z",
            "scheduled_end": "2026-08-10T13:00:00Z",
        }, DISPATCHER)
        validate_error(res, ApiErrorId.ERR_PILOT_TIME_CONFLICT)

    def test_pilot_reassign_one_minute_after_accepted(self, api):
        """PRD §2.10: "A pilot's committed intervals are **closed** intervals
        with no buffer: a new assignment touching an existing one at an
        endpoint — the new `scheduled_start` equal to an existing
        `scheduled_end` — is a conflict." One minute past the endpoint is
        outside the closed interval.
        PRD §3.5: "In both interval checks the assignment undergoing
        reassignment is excluded from its own conflict set."

        Design: Difficulty/resource_temporal_overlap/pilot_closed_interval_touching_collides
        """
        ctx = setup_recalled_assignment(second_pilot_cap=100000,
                                        second_pilot_class="UNLIMITED",
                                        order_gt=8000)
        res = api.reassign_assignment(ctx["a2"]["id"], {
            "pilot_id": ctx["p1"]["id"],
            "scheduled_start": "2026-08-10T12:01:00Z",
            "scheduled_end": "2026-08-10T13:00:00Z",
        }, DISPATCHER)
        reassigned = validate_success(res, 200)
        assert reassigned["pilot_id"] == ctx["p1"]["id"]
        assert reassigned["service_status"] == "ASSIGNED"


class TestExplicitBoatConflict:
    def test_error_boat_time_conflict_on_explicit_reassign_inside_buffer(self, api):
        """PRD §3.5: "When `boat_id` is present, the explicit boat runs the
        half-open-plus-buffer overlap check, conflicting with
        `ERR_BOAT_TIME_CONFLICT` (HTTP 409)."
        PRD §2.10: "the boat remains occupied for 45 minutes beyond each
        booking's end".

        Boat A is occupied over [10:00, 12:45); the 12:30 start lands inside
        the buffer.

        Design: Corner/errors/error_boat_time_conflict_on_explicit_reassign_inside_buffer
        """
        ctx = setup_recalled_assignment(second_pilot_cap=100000,
                                        second_pilot_class="UNLIMITED",
                                        order_gt=8000)
        res = api.reassign_assignment(ctx["a2"]["id"], {
            "boat_id": ctx["boat_a"]["id"],
            "scheduled_start": "2026-08-10T12:30:00Z",
            "scheduled_end": "2026-08-10T14:00:00Z",
        }, DISPATCHER)
        validate_error(res, ApiErrorId.ERR_BOAT_TIME_CONFLICT)
        assert get_assignment_fresh(ctx["a2"]["id"])["service_status"] == "RECALLED"
