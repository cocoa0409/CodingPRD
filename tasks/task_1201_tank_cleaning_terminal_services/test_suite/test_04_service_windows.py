"""Service window calendar rules: overlap, 24h buffer, lifecycle (PRD §2.8, §3.3)."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_service_window_payload,
    new_ctx, create_job, schedule_job, set_clock, fresh_tank_version,
    get_job,
)

OPERATOR = TEST_USERS["operator_headers"]


def _booked_window_ctx(api):
    """One tank with an existing PLANNED window [2026-05-02, 2026-05-10)."""
    ctx = new_ctx()
    window = validate_success(api.create_service_window(
        create_service_window_payload(
            ctx["tank"]["id"], ctx["tank"]["version"],
            planned_start="2026-05-02T00:00:00Z",
            planned_end="2026-05-10T00:00:00Z"),
        OPERATOR), 201)
    ctx["window"] = window
    return ctx


class TestTankWindowBufferSemantics:
    def test_intersecting_window_rejected_as_overlap(self, api):
        """PRD §2.8: "True intersection — the new start falling before the existing end while the existing start falls before the new end — is rejected with `ERR_WINDOW_OVERLAP` (HTTP 409)."
        PRD §2.8: "When both rules could fire, the overlap error is reported first."

        Design: Difficulty/resource_temporal_overlap/tank_window_buffer_gap_semantics
        """
        ctx = _booked_window_ctx(api)
        res = api.create_service_window(
            create_service_window_payload(
                ctx["tank"]["id"], fresh_tank_version(ctx["tank"]["id"]),
                planned_start="2026-05-05T00:00:00Z",
                planned_end="2026-05-06T00:00:00Z"),
            OPERATOR)
        validate_error(res, ApiErrorId.ERR_WINDOW_OVERLAP)

    def test_window_twelve_hours_after_existing_end_rejected_as_buffer(self, api):
        """PRD §2.8: "Even without intersection, a mandatory 24-hour gas-free buffer surrounds each existing window: a new window that starts or ends within 24 hours of an existing window's far edge is rejected with `ERR_WINDOW_BUFFER_VIOLATION` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/tank_window_buffer_gap_semantics
        """
        ctx = _booked_window_ctx(api)
        res = api.create_service_window(
            create_service_window_payload(
                ctx["tank"]["id"], fresh_tank_version(ctx["tank"]["id"]),
                planned_start="2026-05-10T12:00:00Z",
                planned_end="2026-05-12T00:00:00Z"),
            OPERATOR)
        validate_error(res, ApiErrorId.ERR_WINDOW_BUFFER_VIOLATION)

    def test_window_exactly_24h_after_existing_end_accepted(self, api):
        """PRD §2.8: "a new window that starts or ends within 24 hours of an existing window's far edge is rejected with `ERR_WINDOW_BUFFER_VIOLATION` (HTTP 409). Touching adjacency is not exempt — because the buffer makes a zero-hour gap a violation, a new window starting exactly at an existing window's end is rejected as a buffer violation."

        Design: Difficulty/resource_temporal_overlap/tank_window_buffer_gap_semantics
        """
        ctx = _booked_window_ctx(api)
        # Exactly 24h after the existing end: outside "within 24 hours", so it
        # is the first gap that passes the buffer rule.
        res = api.create_service_window(
            create_service_window_payload(
                ctx["tank"]["id"], fresh_tank_version(ctx["tank"]["id"]),
                planned_start="2026-05-11T00:00:00Z",
                planned_end="2026-05-12T00:00:00Z"),
            OPERATOR)
        window = validate_success(res, 201)
        assert window["status"] == "PLANNED"
        assert window["job_id"] is None


class TestWindowLifecycle:
    def test_planned_window_becomes_overrun_on_clock_advance(self, api):
        """PRD §2.5: "every service window whose `planned_end` has been reached transitions to `OVERRUN` — a `PLANNED` window unconditionally, an `ACTIVE` window only when its linked job has not yet reached `RETURNED_TO_SERVICE`."

        Design: Corner/state_machines/window_overrun_on_clock_advance
        """
        ctx = new_ctx()
        window = validate_success(api.create_service_window(
            create_service_window_payload(
                ctx["tank"]["id"], ctx["tank"]["version"],
                planned_start="2026-05-02T00:00:00Z",
                planned_end="2026-05-03T00:00:00Z"),
            OPERATOR), 201)
        set_clock("2026-05-04T00:00:00Z")
        after = validate_success(
            api.get_service_window(window["id"], OPERATOR), 200)
        assert after["status"] == "OVERRUN"

    def test_window_activation_before_planned_start_rejected(self, api):
        """PRD §3.3: "Activation — `PLANNED` to `ACTIVE` — is permitted only while the logical clock has reached `planned_start` and has not yet reached `planned_end`; outside that interval the attempt fails with `ERR_WINDOW_NOT_ACTIVE` (HTTP 409)."

        Design: Corner/validations/window_activate_before_start_rejected
        """
        ctx = new_ctx()
        window = validate_success(api.create_service_window(
            create_service_window_payload(
                ctx["tank"]["id"], ctx["tank"]["version"],
                planned_start="2026-05-03T00:00:00Z",
                planned_end="2026-05-04T00:00:00Z"),
            OPERATOR), 201)
        set_clock("2026-05-02T23:00:00Z")
        validate_error(api.activate_window(window["id"], OPERATOR),
                       ApiErrorId.ERR_WINDOW_NOT_ACTIVE)
        # At exactly planned_start the half-open interval includes the instant.
        set_clock("2026-05-03T00:00:00Z")
        activated = validate_success(api.activate_window(window["id"], OPERATOR), 200)
        assert activated["status"] == "ACTIVE"

    def test_window_cancel_blocked_while_linked_to_live_job(self, api):
        """PRD §3.3: "Cancelling is allowed only from `PLANNED`, and only while the window is unlinked or its linked job is already `CANCELLED` — a live job holding the window rejects the cancel with `ERR_WINDOW_LINKED` (HTTP 409)."

        Design: Corner/validations/window_cancel_while_linked_rejected
        """
        ctx = new_ctx()
        create_job(ctx, heel_volume_liters_sounding=100,
                   base_service_fee_cents=1000)
        schedule_job(ctx)
        res = api.cancel_window(ctx["window"]["id"], OPERATOR)
        validate_error(res, ApiErrorId.ERR_WINDOW_LINKED)
        after = validate_success(
            api.get_service_window(ctx["window"]["id"], OPERATOR), 200)
        assert after["status"] == "PLANNED"

    def test_schedule_with_already_linked_window_rejected(self, api):
        """PRD §3.4: "Last, the named `window_id` must identify a `PLANNED` service window on the same tank that is not already linked to another job, failing which the rejection is `ERR_WINDOW_UNAVAILABLE` (HTTP 409)."

        Design: Corner/validations/schedule_with_already_linked_window_rejected
        """
        ctx = new_ctx()
        create_job(ctx, heel_volume_liters_sounding=100,
                   base_service_fee_cents=1000)
        schedule_job(ctx)
        window_id = ctx["window"]["id"]
        job_b = create_job(ctx, heel_volume_liters_sounding=100,
                           base_service_fee_cents=1000)
        res = api.schedule_job(job_b["id"], {"window_id": window_id}, OPERATOR)
        validate_error(res, ApiErrorId.ERR_WINDOW_UNAVAILABLE)
        after = validate_success(api.get_cleaning_job(job_b["id"], OPERATOR), 200)
        assert after["status"] == "DRAFT"
