"""Dredge-event creation gates: reach state, posture (SUSPENDED/RESTRICTED),
plan-window coverage, and turbidity-driven posture legs (PRD §2.6, §3.5, §3.6).
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_dredge_event_payload,
    set_clock, record_reading, get_project, get_event,
    create_project, add_permit,
    setup_pre_surveyed_reach, setup_dredging_reach, open_event,
)


class TestReachStateGate:
    def test_event_creation_rejected_when_reach_not_dredging(self, api,
                                                             contractor_headers):
        """PRD §3.5: "The reach must be `DREDGING`, else
        `ERR_REACH_NOT_DREDGABLE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/event_creation_gated_on_reach_state
        """
        # Reach PRE_SURVEYED (pre-dredge survey accepted, begin-dredging never
        # called); project ACTIVE, plan APPROVED, posture CLEAR.
        ctx = setup_pre_surveyed_reach(activate=True)
        res = api.create_dredge_event(
            create_dredge_event_payload(ctx["reach"]["id"], ctx["plant"]["id"],
                                        started_utc="2026-05-10T00:00:00Z"),
            contractor_headers,
        )
        validate_error(res, ApiErrorId.ERR_REACH_NOT_DREDGABLE,
                       expected_status=409)

    def test_event_creation_succeeds_after_begin_dredging(self, api,
                                                          contractor_headers):
        """PRD §3.5: "A new event starts `ACTIVE` with
        `shutdown_accumulated_hours` at zero."
        PRD §3.5: "With a reach `DREDGING`, a `ContractorOps` manager opens a
        dredge event by supplying `reach_id`, `plant_id`, the `started_utc`
        work-start instant, and optionally `reduced_rate`, which defaults to
        false."

        Design: Difficulty/cross_entity_state_dependency/event_creation_gated_on_reach_state
        """
        ctx = setup_pre_surveyed_reach(activate=True)
        validate_success(api.begin_dredging(ctx["reach"]["id"],
                                            contractor_headers), 200)
        # Identical payload now succeeds.
        res = api.create_dredge_event(
            create_dredge_event_payload(ctx["reach"]["id"], ctx["plant"]["id"],
                                        started_utc="2026-05-10T00:00:00Z"),
            contractor_headers,
        )
        event = validate_success(res, 201)
        assert event["status"] == "ACTIVE"
        assert event["shutdown_accumulated_hours"] == pytest.approx(0, abs=1e-6)


class TestPostureGates:
    def test_event_create_while_suspended_rejected(self, api, contractor_headers):
        """PRD §3.5: "While the project's posture is `SUSPENDED`, creation is
        rejected outright with `ERR_POSTURE_SUSPENDED` (HTTP 409)."
        PRD §2.6: "If no permit governs — including the case of a project with
        no `ISSUED` permit at all — the posture is `SUSPENDED`."

        Design: Corner/validations/event_create_while_suspended_rejected
        """
        ctx = setup_dredging_reach(
            permit_overrides={"window_end_utc": "2026-06-30T23:59:59Z"}
        )
        # Clock leaves the permit window: permit EXPIRED, posture SUSPENDED.
        set_clock("2026-09-15T00:00:00Z")
        res = api.create_dredge_event(
            create_dredge_event_payload(ctx["reach"]["id"], ctx["plant"]["id"],
                                        started_utc="2026-05-15T00:00:00Z"),
            contractor_headers,
        )
        validate_error(res, ApiErrorId.ERR_POSTURE_SUSPENDED, expected_status=409)

    def test_event_create_outside_plan_window_rejected(self, api,
                                                       contractor_headers):
        """PRD §3.5: "Finally, an `APPROVED` plan must exist for the event's
        project and plant whose half-open assignment window covers `started_utc`
        — at or after `planned_start_utc` and strictly before `planned_end_utc`
        — else `ERR_PLAN_NOT_APPROVED` (HTTP 409)."

        Design: Corner/endpoints/event_create_outside_plan_window_rejected
        """
        ctx = setup_dredging_reach()
        # Approved window is [2026-05-10, 2026-06-30); 2026-07-15 is outside.
        res = api.create_dredge_event(
            create_dredge_event_payload(ctx["reach"]["id"], ctx["plant"]["id"],
                                        started_utc="2026-07-15T00:00:00Z"),
            contractor_headers,
        )
        validate_error(res, ApiErrorId.ERR_PLAN_NOT_APPROVED, expected_status=409)


class TestTurbidityPostureLegs:
    def test_turbidity_reading_below_limit_keeps_clear(self, api, owner_headers,
                                                       monitor_headers):
        """PRD §2.6: "Fourth, if the window is non-empty and the arithmetic mean
        of `value_ntu` over the window, carried at full precision with no
        rounding, is at or above the permit's `turbidity_limit_ntu` — equality
        restricts — the posture is `RESTRICTED`."
        PRD §2.6: "Otherwise the posture is `CLEAR`."

        Design: Difficulty/boundary_precision_check/turbidity_limit_equality_restricts
        """
        ctx = setup_dredging_reach(
            plant_overrides={"plant_type": "CUTTER_SUCTION"}
        )
        set_clock("2026-05-10T12:00:00Z")
        record_reading(ctx["project"]["id"], 49, "2026-05-10T11:00:00Z")
        project = get_project(ctx["project"]["id"])
        # Single reading 49 < limit 50: average below the limit never restricts.
        assert project["compliance_posture"] == "CLEAR"

    def test_turbidity_limit_equality_restricts_and_gates_events(
        self, api, contractor_headers, monitor_headers
    ):
        """PRD §2.6: "if the window is non-empty and the arithmetic mean of
        `value_ntu` over the window, carried at full precision with no rounding,
        is at or above the permit's `turbidity_limit_ntu` — equality restricts —
        the posture is `RESTRICTED`."
        PRD §3.5: "Under `RESTRICTED`, creation is allowed only with
        `reduced_rate` set to true — the contractor's attestation of half
        production — and without it the rejection is `ERR_POSTURE_RESTRICTED`
        (HTTP 409)."

        Design: Difficulty/boundary_precision_check/turbidity_limit_equality_restricts
        """
        ctx = setup_dredging_reach(
            plant_overrides={"plant_type": "CUTTER_SUCTION"}
        )
        set_clock("2026-05-11T12:00:00Z")
        record_reading(ctx["project"]["id"], 50, "2026-05-11T12:00:00Z")
        project = get_project(ctx["project"]["id"])
        # Average exactly 50 >= limit 50: equality restricts.
        assert project["compliance_posture"] == "RESTRICTED"
        res = api.create_dredge_event(
            create_dredge_event_payload(ctx["reach"]["id"], ctx["plant"]["id"],
                                        started_utc="2026-05-11T12:00:00Z"),
            contractor_headers,
        )
        validate_error(res, ApiErrorId.ERR_POSTURE_RESTRICTED, expected_status=409)
        res_ok = api.create_dredge_event(
            create_dredge_event_payload(ctx["reach"]["id"], ctx["plant"]["id"],
                                        started_utc="2026-05-11T12:00:00Z",
                                        reduced_rate=True),
            contractor_headers,
        )
        event = validate_success(res_ok, 201)
        assert event["status"] == "ACTIVE"

    def test_ceiling_reading_suspends_and_shuts_events(self, api, owner_headers,
                                                       monitor_headers):
        """PRD §2.6: "If any reading in that window has `value_ntu` at or above
        the permit's `turbidity_ceiling_ntu` — equality suspends — the posture is
        `SUSPENDED`."
        PRD §3.6: "Recording a sample triggers an immediate posture recompute,
        and a sample at or above the governing permit's `turbidity_ceiling_ntu`
        suspends the project on the spot, driving every `ACTIVE` dredge event
        into `SHUTDOWN` with reason `TURBIDITY` as described in §3.5."

        Design: Corner/calculations/ceiling_reading_suspends_and_shuts_events
        """
        ctx = setup_dredging_reach(
            plant_overrides={"plant_type": "CUTTER_SUCTION"}
        )
        event = open_event(ctx["reach"]["id"], ctx["plant"]["id"],
                           "2026-05-10T00:00:00Z")
        set_clock("2026-05-10T06:00:00Z")
        record_reading(ctx["project"]["id"], 100, "2026-05-10T06:00:00Z")
        project = get_project(ctx["project"]["id"])
        assert project["compliance_posture"] == "SUSPENDED"
        event_after = get_event(event["id"])
        assert event_after["status"] == "SHUTDOWN"
        assert event_after["shutdown_reason"] == "TURBIDITY"

    def test_turbidity_trailing_window_excludes_aged_reading(self, api,
                                                             owner_headers,
                                                             monitor_headers):
        """PRD §2.6: "the project's TurbidityReadings whose `taken_utc` is
        strictly later than the current logical time minus the governing
        permit's `turbidity_averaging_hours` hours, and at or before the current
        logical time."
        PRD §2.6: "An empty trailing window never restricts, no matter what
        thresholds the permit declares."

        Design: Corner/calculations/turbidity_trailing_window_excludes_aged_reading
        """
        set_clock("2026-05-10T00:00:00Z")
        project = create_project(name="P-TW")
        add_permit(project["id"])
        # Reading taken at exactly now-24h is OUTSIDE the left-open window.
        record_reading(project["id"], 80, "2026-05-10T12:00:00Z")
        set_clock("2026-05-11T12:00:00Z")
        posture_edge = get_project(project["id"])["compliance_posture"]
        assert posture_edge == "CLEAR"
        # One second inside the window the same value restricts (avg 80 >= 50).
        record_reading(project["id"], 80, "2026-05-10T12:00:01Z")
        posture_in = get_project(project["id"])["compliance_posture"]
        assert posture_in == "RESTRICTED"
