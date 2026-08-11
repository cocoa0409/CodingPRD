"""Install appointment windows, overlap rules, terminal lockdown, ownership,
kit-state gating, and completion side effects."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    confirm_and_complete_appointment,
    create_installer,
    create_senior,
    create_subscription,
    create_plan,
    deliver_kit,
    factories,
    get_success_data,
    make_installer_headers,
    order_kit,
    schedule_appointment,
    set_clock,
    setup_active_senior,
    setup_installed_senior,
    setup_senior_with_subscription,
    ship_kit,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def _senior_with_kit(senior_name="Ws Senior", plan_overrides=None):
    """Senior + subscription + ORDERED kit + one installer. No shipping."""
    ctx = setup_senior_with_subscription(plan_overrides=plan_overrides)
    kit = order_kit(ctx["senior"]["id"])
    installer = create_installer()
    ctx.update({"kit": kit, "installer": installer})
    return ctx


def _senior_with_delivered_kit(plan_overrides=None):
    ctx = _senior_with_kit(plan_overrides=plan_overrides)
    ship_kit(ctx["kit"]["id"])
    deliver_kit(ctx["kit"]["id"])
    return ctx


def _senior_with_completed_appointment():
    """Kit INSTALLED via a COMPLETED appointment at clock 2026-05-01T09:30Z."""
    return setup_installed_senior()


class TestWindowValidation:
    def test_appointment_window_duration_out_of_range(self, api):
        """PRD 3.3: "The window itself is heavily constrained, and the checks
        run in a deliberate order: the window's duration must fall between 60
        and 240 minutes inclusive (else `ERR_WINDOW_TOO_SHORT`); then the
        installer-overlap rule; then the senior-overlap rule; then the
        requirement that `window_start` lie strictly after the current clock
        (else `ERR_WINDOW_IN_PAST`); and only then the kit-ownership check."

        Design: Corner/validations/appointment_window_duration_out_of_range
        """
        ctx = _senior_with_kit()
        resp = api.create_install_appointment(
            factories.create_install_appointment_payload(
                ctx["senior"]["id"],
                ctx["kit"]["id"],
                ctx["installer"]["id"],
                window_start="2026-05-02T09:00:00Z",
                window_end="2026-05-02T09:30:00Z",
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_TOO_SHORT)
        listed, _meta = validate_paginated(
            api.list_install_appointments(ADMIN, params={"senior_id": ctx["senior"]["id"]})
        )
        assert listed == [], "no appointment may be created for a 30-minute window"


class TestTerminalLockdown:
    def test_appointment_cancel_from_completed_returns_terminal_error(self, api):
        """PRD 3.3: "Because `COMPLETED`, `CANCELLED`, and `NO_SHOW` are
        terminal, any confirm, complete, cancel, or reschedule attempted
        against a terminal appointment is rejected with
        `ERR_APPOINTMENT_TERMINAL` — and that terminal check outranks the
        generic state check, so a terminal appointment never surfaces
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/appointment_cancel_from_completed_returns_terminal_error
        """
        ctx = _senior_with_completed_appointment()
        resp = api.cancel_install_appointment(ctx["appointment"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_TERMINAL)
        appt = get_success_data(
            api.get_install_appointment(ctx["appointment"]["id"], ADMIN)
        )
        assert appt["status"] == "COMPLETED"

    def test_reschedule_completed_appointment_returns_terminal_error(self, api):
        """PRD 3.3: "Because `COMPLETED`, `CANCELLED`, and `NO_SHOW` are
        terminal, any confirm, complete, cancel, or reschedule attempted
        against a terminal appointment is rejected with
        `ERR_APPOINTMENT_TERMINAL` — and that terminal check outranks the
        generic state check, so a terminal appointment never surfaces
        `ERR_INVALID_STATE`."

        Design: Difficulty/priority_pair_validation_conflict/reschedule_completed_appointment_with_past_window_returns_terminal_error
        """
        ctx = _senior_with_completed_appointment()
        resp = api.reschedule_install_appointment(
            ctx["appointment"]["id"],
            {
                "window_start": "2026-05-01T08:00:00Z",
                "window_end": "2026-05-01T09:00:00Z",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_TERMINAL)

    def test_reschedule_terminal_beats_past_window_and_leaves_state(self, api):
        """PRD 3.3: "Because `COMPLETED`, `CANCELLED`, and `NO_SHOW` are
        terminal, any confirm, complete, cancel, or reschedule attempted
        against a terminal appointment is rejected with
        `ERR_APPOINTMENT_TERMINAL` — and that terminal check outranks the
        generic state check, so a terminal appointment never surfaces
        `ERR_INVALID_STATE`."
        (The requested replacement window is entirely in the past, yet the
        terminal rejection still surfaces and the appointment is untouched.)

        Design: Difficulty/priority_pair_validation_conflict/reschedule_completed_appointment_with_past_window_returns_terminal_error
        """
        ctx = _senior_with_completed_appointment()
        resp = api.reschedule_install_appointment(
            ctx["appointment"]["id"],
            {
                "window_start": "2026-05-01T08:00:00Z",
                "window_end": "2026-05-01T09:00:00Z",
            },
            ADMIN,
        )
        error_data = validate_error(resp, ApiErrorId.ERR_APPOINTMENT_TERMINAL)
        assert error_data["error_id"] != "ERR_WINDOW_IN_PAST"
        appt = get_success_data(
            api.get_install_appointment(ctx["appointment"]["id"], ADMIN)
        )
        assert appt["status"] == "COMPLETED"


class TestKitStateGate:
    def test_complete_with_shipped_kit_rejected(self, api):
        """PRD 3.3: "Completing the install is likewise restricted to the
        assigned installer and requires three conditions beyond identity,
        evaluated after the state check: the appointment must be `CONFIRMED`
        (a `SCHEDULED` appointment yields `ERR_INVALID_STATE`), the kit must be
        `DELIVERED` (else `ERR_KIT_NOT_DELIVERED`), and the current clock must
        lie within the window inclusive of both endpoints (else
        `ERR_OUTSIDE_APPOINTMENT_WINDOW`)."

        Design: Difficulty/cross_entity_state_dependency/complete_appointment_requires_kit_delivered_rejected
        """
        ctx = _senior_with_kit()
        ship_kit(ctx["kit"]["id"])  # SHIPPED, never DELIVERED
        appt = schedule_appointment(
            ctx["senior"]["id"], ctx["kit"]["id"], ctx["installer"]["id"]
        )
        get_success_data(
            api.confirm_install_appointment(
                appt["id"], make_installer_headers(ctx["installer"]["id"])
            )
        )
        set_clock("2026-05-01T09:30:00Z")
        resp = api.complete_install_appointment(
            appt["id"], make_installer_headers(ctx["installer"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_KIT_NOT_DELIVERED)

    def test_complete_rejection_leaves_appointment_and_kit_unchanged(self, api):
        """PRD 3.3: "Completing the install is likewise restricted to the
        assigned installer and requires three conditions beyond identity,
        evaluated after the state check: the appointment must be `CONFIRMED`
        (a `SCHEDULED` appointment yields `ERR_INVALID_STATE`), the kit must be
        `DELIVERED` (else `ERR_KIT_NOT_DELIVERED`), and the current clock must
        lie within the window inclusive of both endpoints (else
        `ERR_OUTSIDE_APPOINTMENT_WINDOW`)."

        Design: Difficulty/cross_entity_state_dependency/complete_appointment_requires_kit_delivered_rejected
        """
        ctx = _senior_with_kit()
        ship_kit(ctx["kit"]["id"])
        appt = schedule_appointment(
            ctx["senior"]["id"], ctx["kit"]["id"], ctx["installer"]["id"]
        )
        get_success_data(
            api.confirm_install_appointment(
                appt["id"], make_installer_headers(ctx["installer"]["id"])
            )
        )
        set_clock("2026-05-01T09:30:00Z")
        validate_error(
            api.complete_install_appointment(
                appt["id"], make_installer_headers(ctx["installer"]["id"])
            ),
            ApiErrorId.ERR_KIT_NOT_DELIVERED,
        )
        appt_after = get_success_data(api.get_install_appointment(appt["id"], ADMIN))
        kit_after = get_success_data(api.get_sensor_kit(ctx["kit"]["id"], ADMIN))
        assert appt_after["status"] == "CONFIRMED"
        assert kit_after["status"] == "SHIPPED"


class TestInstallerOverlap:
    """Half-open windows expanded by a 30-minute travel buffer (PRD 3.3)."""

    def _setup(self):
        ctx1 = _senior_with_kit()
        ctx2 = _senior_with_kit()
        installer = ctx1["installer"]
        existing = schedule_appointment(
            ctx1["senior"]["id"],
            ctx1["kit"]["id"],
            installer["id"],
            "2026-05-02T09:00:00Z",
            "2026-05-02T10:00:00Z",
        )
        return ctx1, ctx2, installer, existing

    def test_installer_window_inside_travel_buffer_conflicts(self, api):
        """PRD 3.3: "The installer-overlap rule treats the new window as a
        half-open interval and rejects it with `ERR_INSTALLER_WINDOW_CONFLICT`
        when it intersects any of that installer's non-terminal appointments
        expanded by a 30-minute travel buffer on each side — adjacency at
        exactly 30 minutes is permitted."

        Design: Difficulty/resource_temporal_overlap/installer_overlap_half_open_with_travel_buffer
        """
        _ctx1, ctx2, installer, _existing = self._setup()
        resp = api.create_install_appointment(
            factories.create_install_appointment_payload(
                ctx2["senior"]["id"],
                ctx2["kit"]["id"],
                installer["id"],
                window_start="2026-05-02T10:20:00Z",
                window_end="2026-05-02T11:20:00Z",
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INSTALLER_WINDOW_CONFLICT)

    def test_installer_window_exactly_30_minutes_after_allowed(self, api):
        """PRD 3.3: "The installer-overlap rule treats the new window as a
        half-open interval and rejects it with `ERR_INSTALLER_WINDOW_CONFLICT`
        when it intersects any of that installer's non-terminal appointments
        expanded by a 30-minute travel buffer on each side — adjacency at
        exactly 30 minutes is permitted."

        Design: Difficulty/resource_temporal_overlap/installer_overlap_half_open_with_travel_buffer
        """
        _ctx1, ctx2, installer, _existing = self._setup()
        data = validate_success(
            api.create_install_appointment(
                factories.create_install_appointment_payload(
                    ctx2["senior"]["id"],
                    ctx2["kit"]["id"],
                    installer["id"],
                    window_start="2026-05-02T10:30:00Z",
                    window_end="2026-05-02T11:30:00Z",
                ),
                ADMIN,
            ),
            201,
        )
        assert data["status"] == "SCHEDULED", (
            "a window starting exactly 30 minutes after the previous window's "
            "end only touches the buffer boundary and must be accepted"
        )


class TestSeniorOverlap:
    """Closed-interval semantics on the senior's calendar (PRD 3.3)."""

    def _setup(self):
        ctx = _senior_with_kit()
        second_installer = create_installer(full_name="Inst C2", region="R2")
        existing = schedule_appointment(
            ctx["senior"]["id"],
            ctx["kit"]["id"],
            ctx["installer"]["id"],
            "2026-05-02T09:00:00Z",
            "2026-05-02T10:00:00Z",
        )
        return ctx, second_installer, existing

    def test_senior_window_touching_endpoint_conflicts(self, api):
        """PRD 3.3: "The senior-overlap rule uses closed-interval semantics:
        the new window conflicts with any non-terminal appointment of the same
        senior whenever the new start is at or before the existing window's end
        and the existing window's start is at or before the new end, so windows
        that merely touch still conflict and are rejected with
        `ERR_SENIOR_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/senior_overlap_closed_interval_touching_endpoints
        """
        ctx, second_installer, _existing = self._setup()
        resp = api.create_install_appointment(
            factories.create_install_appointment_payload(
                ctx["senior"]["id"],
                ctx["kit"]["id"],
                second_installer["id"],
                window_start="2026-05-02T10:00:00Z",
                window_end="2026-05-02T11:00:00Z",
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_SENIOR_WINDOW_CONFLICT)

    def test_senior_window_conflict_creates_no_appointment(self, api):
        """PRD 3.3: "The senior-overlap rule uses closed-interval semantics:
        the new window conflicts with any non-terminal appointment of the same
        senior whenever the new start is at or before the existing window's end
        and the existing window's start is at or before the new end, so windows
        that merely touch still conflict and are rejected with
        `ERR_SENIOR_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/senior_overlap_closed_interval_touching_endpoints
        """
        ctx, second_installer, _existing = self._setup()
        validate_error(
            api.create_install_appointment(
                factories.create_install_appointment_payload(
                    ctx["senior"]["id"],
                    ctx["kit"]["id"],
                    second_installer["id"],
                    window_start="2026-05-02T10:00:00Z",
                    window_end="2026-05-02T11:00:00Z",
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_SENIOR_WINDOW_CONFLICT,
        )
        listed, _meta = validate_paginated(
            api.list_install_appointments(
                ADMIN, params={"senior_id": ctx["senior"]["id"]}
            )
        )
        assert len(listed) == 1, (
            f"the conflicting appointment must not be created; got {len(listed)}"
        )


class TestInstallerOwnership:
    def test_installer_cannot_complete_others_appointment(self, api):
        """PRD 2.1: "When `X-User-Role` is `Installer`, `X-User-ID` is the `id`
        of the acting `Installer`, and the installer may act only on
        appointments whose `installer_id` matches. A violation of any of these
        ownership rules is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403)."
        PRD 3.3: "Completing the install is likewise restricted to the
        assigned installer and requires three conditions beyond identity,
        evaluated after the state check: the appointment must be `CONFIRMED`
        (a `SCHEDULED` appointment yields `ERR_INVALID_STATE`), the kit must be
        `DELIVERED` (else `ERR_KIT_NOT_DELIVERED`), and the current clock must
        lie within the window inclusive of both endpoints (else
        `ERR_OUTSIDE_APPOINTMENT_WINDOW`)."

        Design: Corner/rbac/installer_cannot_complete_others_appointment
        """
        ctx = _senior_with_delivered_kit()
        other_installer = create_installer(full_name="Inst R2", region="R2")
        appt = schedule_appointment(
            ctx["senior"]["id"], ctx["kit"]["id"], ctx["installer"]["id"]
        )
        get_success_data(
            api.confirm_install_appointment(
                appt["id"], make_installer_headers(ctx["installer"]["id"])
            )
        )
        set_clock("2026-05-01T09:30:00Z")
        resp = api.complete_install_appointment(
            appt["id"], make_installer_headers(other_installer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)
        appt_after = get_success_data(api.get_install_appointment(appt["id"], ADMIN))
        assert appt_after["status"] == "CONFIRMED"


class TestCompletionSideEffects:
    def test_appointment_completion_side_effects_kit_and_devices(self, api):
        """PRD 3.3: "Completion is a cascade: the kit becomes `INSTALLED`, and
        every `PROVISIONED` device in it becomes `INSTALLED` with its `version`
        incremented."

        Design: Corner/state_machines/appointment_completion_side_effects_kit_and_devices
        """
        ctx = _senior_with_delivered_kit(
            plan_overrides={"included_motion_sensors": 1}
        )
        appt = schedule_appointment(
            ctx["senior"]["id"], ctx["kit"]["id"], ctx["installer"]["id"]
        )
        confirm_and_complete_appointment(appt["id"], ctx["installer"]["id"])
        kit = get_success_data(api.get_sensor_kit(ctx["kit"]["id"], ADMIN))
        assert kit["status"] == "INSTALLED", (
            f"kit must be INSTALLED after completion, got {kit['status']}"
        )
        devices, _meta = validate_paginated(
            api.list_devices(ADMIN, params={"kit_id": ctx["kit"]["id"]})
        )
        assert len(devices) == 3
        for device in devices:
            assert device["status"] == "INSTALLED", (
                f"every PROVISIONED device must become INSTALLED, got "
                f"{device['status']} for {device['device_type']}"
            )
