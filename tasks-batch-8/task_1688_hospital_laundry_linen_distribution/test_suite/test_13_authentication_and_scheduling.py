"""Authentication, scheduling window rules, and run-separation buffers
(PRD 2.1, 3.2)."""
from test_helpers import (
    ApiErrorId,
    base_scenario,
    create_cart_run_payload,
    create_facility,
    create_unit,
    make_unit_clerk_headers,
    schedule_run,
    validate_error,
    validate_success,
)


def test_unauthenticated_missing_headers_returns_401(api):
    """PRD 2.1: "A request with missing headers, or whose role is not one of
    these declared roles, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/unauthenticated_missing_headers_returns_401
    """
    facility = create_facility()
    res = api.get_facility(facility["id"], headers={})
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED)


def test_clerk_cannot_create_cart_run(api):
    """PRD 2.1: "Access to each operation is restricted by role as enumerated
    in §4; an attempt to perform an operation outside the caller's role is
    rejected with `ERR_UNAUTHORIZED_ROLE`."

    Design: Corner/rbac/clerk_cannot_create_cart_run
    """
    ctx = base_scenario()
    res = api.create_cart_run(
        create_cart_run_payload(
            ctx["unit"]["id"],
            scheduled_start="2026-08-02T08:00:00Z",
            scheduled_end="2026-08-02T09:00:00Z",
        ),
        make_unit_clerk_headers(ctx["unit"]["id"]),
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE)


def test_window_end_not_after_start_returns_invalid_window(
    api, evs_operator_headers
):
    """PRD 3.2: "The window end must be after its start, or the request is
    rejected with `ERR_INVALID_WINDOW`."

    Design: Corner/validations/window_end_not_after_start_returns_invalid_window
    """
    ctx = base_scenario()
    res = api.create_cart_run(
        create_cart_run_payload(
            ctx["unit"]["id"],
            scheduled_start="2026-08-02T09:00:00Z",
            scheduled_end="2026-08-02T09:00:00Z",
        ),
        evs_operator_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_WINDOW)


def test_cart_run_without_par_level_returns_no_par_level(
    api, evs_operator_headers
):
    """PRD 3.2: "A unit with no par levels configured cannot have a run
    scheduled at all — the attempt is rejected with `ERR_NO_PAR_LEVEL`."

    Design: Corner/validations/cart_run_without_par_level_returns_no_par_level
    """
    facility = create_facility()
    unit = create_unit(facility["id"], name="ICU", unit_tier="CRITICAL")
    res = api.create_cart_run(
        create_cart_run_payload(
            unit["id"],
            scheduled_start="2026-08-02T08:00:00Z",
            scheduled_end="2026-08-02T09:00:00Z",
        ),
        evs_operator_headers,
    )
    validate_error(res, ApiErrorId.ERR_NO_PAR_LEVEL)


class TestRunWindowBuffer:
    """Two-hour clearance between a unit's non-terminal run windows."""

    def test_ninety_minute_gap_conflicts(self, api, evs_operator_headers):
        """PRD 3.2: "Scheduling also enforces separation between a unit's
        runs: the new window must not overlap, and must leave at least two
        hours clear against, the window of any other run of the same unit
        that has not yet reached `RECONCILED`; violations are rejected with
        `ERR_RUN_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/cart_run_buffer_gap_conflict
        """
        ctx = base_scenario()
        schedule_run(
            ctx["unit"]["id"], "2026-08-02T08:00:00Z", "2026-08-02T09:00:00Z"
        )
        res = api.create_cart_run(
            create_cart_run_payload(
                ctx["unit"]["id"],
                scheduled_start="2026-08-02T10:30:00Z",
                scheduled_end="2026-08-02T11:00:00Z",
            ),
            evs_operator_headers,
        )
        validate_error(res, ApiErrorId.ERR_RUN_WINDOW_CONFLICT)

    def test_exactly_two_hour_gap_accepted(self, api, evs_operator_headers):
        """PRD 3.2: "Scheduling also enforces separation between a unit's
        runs: the new window must not overlap, and must leave at least two
        hours clear against, the window of any other run of the same unit
        that has not yet reached `RECONCILED`; violations are rejected with
        `ERR_RUN_WINDOW_CONFLICT`."
        PRD 3.2: "A newly scheduled run starts in `SCHEDULED` status with
        `manifest_id` null, `shortage_flag` false, `completed_at` null, and
        `late_delivery` false."

        Design: Difficulty/resource_temporal_overlap/cart_run_buffer_gap_conflict
        """
        ctx = base_scenario()
        schedule_run(
            ctx["unit"]["id"], "2026-08-02T08:00:00Z", "2026-08-02T09:00:00Z"
        )
        created = validate_success(
            api.create_cart_run(
                create_cart_run_payload(
                    ctx["unit"]["id"],
                    scheduled_start="2026-08-02T11:00:00Z",
                    scheduled_end="2026-08-02T12:00:00Z",
                ),
                evs_operator_headers,
            ),
            201,
        )
        assert created["status"] == "SCHEDULED"
        assert created["manifest_id"] is None
        assert created["shortage_flag"] is False
        assert created["late_delivery"] is False
