"""Flight execution: launch windows, pilot identity, wind boundaries, and
capture/cancel rules (PRD sections 3.3 and 3.4)."""
from test_helpers import (
    ApiErrorId,
    FC,
    api_client,
    capture,
    complete,
    create_authorization,
    create_mission,
    create_mission_authorized,
    create_mission_completed,
    create_mission_in_flight,
    create_pilot,
    launch_at,
    make_pilot_headers,
    set_clock,
    setup_ops,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestLaunchWindow:

    def test_launch_outside_window_rejected(self):
        """PRD section 3.4: "the current time must fall within the planned
        window — at or after the planned takeoff and strictly before the
        planned landing — or the attempt is `ERR_OUTSIDE_WINDOW`, and
        where an authorization was nominated it must still be `ACTIVE`
        at launch, else `ERR_AUTH_NOT_ACTIVE`."

        Design: Corner/validations/launch_outside_window_rejected
        """
        ctx = setup_ops()
        mission = create_mission_authorized(
            ctx["field"]["id"], ctx["pilot"]["id"], acres_planned=10)
        set_clock("2026-06-02T06:00:00Z")  # before the 08:00 planned takeoff
        resp = api_client.launch_mission(
            mission["id"], make_pilot_headers(ctx["pilot"]["id"]))
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_WINDOW)

    def test_launch_at_planned_landing_instant_rejected(self):
        """PRD section 3.4: "the current time must fall within the planned
        window — at or after the planned takeoff and strictly before the
        planned landing — or the attempt is `ERR_OUTSIDE_WINDOW`, and
        where an authorization was nominated it must still be `ACTIVE`
        at launch, else `ERR_AUTH_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_temporal_on_launch
        """
        ctx = setup_ops(field_overrides={"airspace_class": "B"})
        auth = create_authorization(
            ctx["field"]["id"],
            effective_from="2026-06-02T08:00:00Z",
            effective_until="2026-06-02T11:00:00Z")
        mission = create_mission_authorized(
            ctx["field"]["id"], ctx["pilot"]["id"],
            authorization_id=auth["id"],
            scheduled_start="2026-06-02T08:30:00Z",
            scheduled_end="2026-06-02T10:30:00Z", acres_planned=50)
        # Clock exactly at scheduled_end: outside (strict), authorization
        # still ACTIVE — only the temporal rule is violated.
        set_clock("2026-06-02T10:30:00Z")
        resp = api_client.launch_mission(
            mission["id"], make_pilot_headers(ctx["pilot"]["id"]))
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_WINDOW)


class TestLaunchPilotIdentity:

    def test_error_not_assigned_pilot_on_launch(self):
        """PRD section 3.4: "launching, capturing, or aborting a mission all
        require the caller's identity to equal the mission's assigned
        `pilot_id`, and any other pilot — or any other role — is refused with
        `ERR_NOT_ASSIGNED_PILOT` (HTTP 403)."

        Design: Corner/errors/error_not_assigned_pilot_on_launch
        """
        ctx = setup_ops()
        other_pilot = create_pilot()
        mission = create_mission_authorized(
            ctx["field"]["id"], ctx["pilot"]["id"], acres_planned=10)
        set_clock("2026-06-02T08:30:00Z")
        resp = api_client.launch_mission(
            mission["id"], make_pilot_headers(other_pilot["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_ASSIGNED_PILOT)


class TestLaunchAuthorizationDependency:

    def test_launch_with_expired_authorization_outside_window_reports_auth_error(self):
        """PRD section 3.4: "the current time must fall within the planned
        window — at or after the planned takeoff and strictly before the
        planned landing — or the attempt is `ERR_OUTSIDE_WINDOW`, and
        where an authorization was nominated it must still be `ACTIVE`
        at launch, else `ERR_AUTH_NOT_ACTIVE`."

        Both violations are armed here. The PRD names both errors at launch
        but never pins their relative precedence: section 2.6's business-rule
        priority list names only the authorize-time airspace errors
        (`ERR_AUTH_WINDOW_INSUFFICIENT` / `ERR_AUTH_NOT_PERMITTED`) under
        "airspace authorization sufficiency" and never places
        `ERR_AUTH_NOT_ACTIVE`, while section 3.4's launch sentence lists the
        window check before the authorization-active check. A faithful
        PRD-only reader may therefore report either error, so the assertion
        accepts exactly the two PRD-named outcomes.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_temporal_on_launch
        """
        ctx = setup_ops(field_overrides={"airspace_class": "B"})
        auth = create_authorization(
            ctx["field"]["id"],
            effective_from="2026-06-02T08:00:00Z",
            effective_until="2026-06-02T11:00:00Z")
        mission = create_mission_authorized(
            ctx["field"]["id"], ctx["pilot"]["id"],
            authorization_id=auth["id"],
            scheduled_start="2026-06-02T08:30:00Z",
            scheduled_end="2026-06-02T10:30:00Z", acres_planned=50)
        # Move the clock past both the authorization end and the mission
        # window: authorization sweeps to EXPIRED (safety violation) and the
        # launch is outside the window (temporal violation).
        set_clock("2026-06-02T12:00:00Z")
        resp = api_client.launch_mission(
            mission["id"], make_pilot_headers(ctx["pilot"]["id"]))
        validate_error_is_one_of(resp, [
            ApiErrorId.ERR_AUTH_NOT_ACTIVE,
            ApiErrorId.ERR_OUTSIDE_WINDOW,
        ])

    def test_expiry_sweep_leaves_past_started_mission_authorized(self):
        """PRD section 2.5: "as a cascade, every `AUTHORIZED` mission
        referencing that authorization whose `scheduled_start` is at or after
        the current time is moved to `CANCELLED`."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_temporal_on_launch
        """
        ctx = setup_ops(field_overrides={"airspace_class": "B"})
        auth = create_authorization(
            ctx["field"]["id"],
            effective_from="2026-06-02T08:00:00Z",
            effective_until="2026-06-02T11:00:00Z")
        mission = create_mission_authorized(
            ctx["field"]["id"], ctx["pilot"]["id"],
            authorization_id=auth["id"],
            scheduled_start="2026-06-02T08:30:00Z",
            scheduled_end="2026-06-02T10:30:00Z", acres_planned=50)
        # At 12:00 the authorization expires; the mission's scheduled_start
        # (08:30) is before the current time, so the cascade must NOT cancel it.
        set_clock("2026-06-02T12:00:00Z")
        after = validate_success(api_client.get_mission(mission["id"], FC))
        assert after["status"] == "AUTHORIZED", \
            f"mission whose scheduled_start predates the sweep must stay " \
            f"AUTHORIZED, got {after['status']}"


class TestCaptureWindBoundary:

    def test_capture_at_wind_20_succeeds(self):
        """PRD section 3.4: "Capture demands a mission genuinely in flight
        (else `ERR_MISSION_NOT_IN_FLIGHT`), a peak observed wind of at most
        20 knots (anything stronger is rejected as
        `ERR_WEATHER_LIMIT_EXCEEDED`)".

        Design: Difficulty/boundary_precision_check/wind_threshold_exactly_20_vs_21_on_capture
        """
        ctx = setup_ops()
        mission = create_mission_in_flight(
            ctx["field"]["id"], ctx["pilot"]["id"], acres_planned=50)
        captured = capture(mission["id"], ctx["pilot"]["id"],
                           acres_flown=50, wind_kt=20)
        assert captured["status"] == "CAPTURED", \
            f"wind of exactly 20 knots must admit capture, got {captured['status']}"
        assert captured["wind_kt_max_observed"] == 20
        assert captured["acres_flown"] == 50

    def test_capture_at_wind_21_rejected(self):
        """PRD section 3.4: "Capture demands a mission genuinely in flight
        (else `ERR_MISSION_NOT_IN_FLIGHT`), a peak observed wind of at most
        20 knots (anything stronger is rejected as
        `ERR_WEATHER_LIMIT_EXCEEDED`)".

        Design: Difficulty/boundary_precision_check/wind_threshold_exactly_20_vs_21_on_capture
        """
        ctx = setup_ops()
        mission = create_mission_in_flight(
            ctx["field"]["id"], ctx["pilot"]["id"], acres_planned=50)
        resp = api_client.capture_mission(
            mission["id"], {"acres_flown": 50, "wind_kt_max_observed": 21},
            make_pilot_headers(ctx["pilot"]["id"]))
        validate_error(resp, ApiErrorId.ERR_WEATHER_LIMIT_EXCEEDED)
        after = validate_success(api_client.get_mission(mission["id"], FC))
        assert after["status"] == "IN_FLIGHT", \
            f"rejected capture must leave the mission IN_FLIGHT, got {after['status']}"


class TestCaptureAcresRange:

    def test_error_acres_out_of_range_on_capture(self):
        """PRD section 3.4: "a flown acreage greater than zero and no more
        than the planned acreage (violations are `ERR_ACRES_OUT_OF_RANGE`)".

        Design: Corner/errors/error_acres_out_of_range_on_capture
        """
        ctx = setup_ops()
        mission = create_mission_in_flight(
            ctx["field"]["id"], ctx["pilot"]["id"], acres_planned=10)
        resp = api_client.capture_mission(
            mission["id"], {"acres_flown": 11, "wind_kt_max_observed": 5},
            make_pilot_headers(ctx["pilot"]["id"]))
        validate_error(resp, ApiErrorId.ERR_ACRES_OUT_OF_RANGE)


class TestCancelStateGate:

    def test_mission_cancel_from_completed_returns_invalid_state(self):
        """PRD section 3.3: "a mission in `PLANNED` or `AUTHORIZED` may be
        cancelled into `CANCELLED` with a version increment, while a mission
        in any other state refuses with `ERR_MISSION_NOT_CANCELLABLE`."

        Design: Corner/state_machines/mission_cancel_from_completed_returns_invalid_state
        """
        ctx = setup_ops()
        mission = create_mission_completed(
            ctx["field"]["id"], ctx["pilot"]["id"], acres_flown=50,
            acres_planned=50)
        assert mission["status"] == "COMPLETED"
        resp = api_client.cancel_mission(mission["id"], FC)
        validate_error(resp, ApiErrorId.ERR_MISSION_NOT_CANCELLABLE)
