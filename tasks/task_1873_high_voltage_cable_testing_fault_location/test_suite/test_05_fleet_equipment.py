"""Fleet scheduling: capability coverage, four-hour buffer, activation gate,
maintenance guard, and committed-hours conservation (PRD §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    setup_planned_job,
    create_unit,
    create_assignment,
    confirm_assignment,
    set_clock,
    get_unit,
    get_assignment,
)

DISPATCH = TEST_USERS["dispatch_coordinator_headers"]


def _planned_ctx_with_unit(circuit_ref, capabilities=None):
    ctx = setup_planned_job(circuit_ref=circuit_ref)
    unit = create_unit(capabilities=capabilities) if capabilities else create_unit()
    return ctx, unit


class TestCapabilityAndMaintenance:
    def test_unit_without_required_capability_rejected(self, api):
        """PRD §3.5: "`VLF_TAN_DELTA` requires the `VLF` capability,
        `VLF_WITH_PD` requires both `VLF` and `PD`, and `PD_MAPPING` requires
        `PD`, and additionally the unit's `max_test_voltage_kv` must reach at
        least one and a half times the U0 of the job circuit's voltage class,
        with any shortfall rejected as `ERR_UNIT_CAPABILITY_MISMATCH`."

        Design: Corner/validations/capability_mismatch_rejected
        """
        ctx, unit = _planned_ctx_with_unit("CKT-V12", capabilities=["TDR"])
        resp = api.create_assignment(
            {
                "mobile_unit_id": unit["id"],
                "test_job_id": ctx["job"]["id"],
                "mobilize_at": "2026-08-10T07:00:00Z",
                "demobilize_at": "2026-08-10T11:00:00Z",
            },
            DISPATCH,
        )
        validate_error(resp, ApiErrorId.ERR_UNIT_CAPABILITY_MISMATCH)
        unit_after = get_unit(unit["id"])
        assert unit_after["status"] == "AVAILABLE"
        assert unit_after["committed_hours"] == 0.0

    def test_maintenance_with_open_assignment_rejected(self, api):
        """PRD §3.5: "sending a unit to maintenance while it still holds an
        assignment in `RESERVED`, `CONFIRMED`, or `ACTIVE` is rejected with
        `ERR_UNIT_HAS_ASSIGNMENTS`".

        Design: Corner/validations/maintenance_with_assignment_rejected
        """
        ctx, unit = _planned_ctx_with_unit("CKT-V13")
        create_assignment(unit["id"], ctx["job"]["id"],
                          mobilize_at="2026-08-10T07:00:00Z",
                          demobilize_at="2026-08-10T11:00:00Z")
        resp = api.unit_maintenance(unit["id"], DISPATCH)
        validate_error(resp, ApiErrorId.ERR_UNIT_HAS_ASSIGNMENTS)
        assert get_unit(unit["id"])["status"] == "ASSIGNED"


class TestActivationGate:
    def test_activate_before_mobilize_rejected_then_allowed_at_boundary(self, api):
        """PRD §3.5: "Activation requires the logical clock to have reached
        `mobilize_at` — nothing more, there is no upper bound — and an early
        activation is rejected with `ERR_WINDOW_NOT_ACTIVE`."

        Design: Corner/endpoints/assignment_activate_before_mobilize_rejected
        """
        ctx, unit = _planned_ctx_with_unit("CKT-P7")
        assignment = create_assignment(unit["id"], ctx["job"]["id"],
                                       mobilize_at="2026-08-10T07:00:00Z",
                                       demobilize_at="2026-08-10T11:00:00Z")
        confirm_assignment(assignment["id"])

        set_clock("2026-08-09T12:00:00Z")
        early = api.activate_assignment(assignment["id"], DISPATCH)
        validate_error(early, ApiErrorId.ERR_WINDOW_NOT_ACTIVE)

        set_clock("2026-08-10T07:00:00Z")
        activated = validate_success(api.activate_assignment(assignment["id"], DISPATCH))
        assert activated["status"] == "ACTIVE", "activation is permitted from mobilize_at onwards"


class TestBufferRule:
    def test_exact_four_hour_gap_allowed(self, api):
        """PRD §3.5: "then the four-hour buffer rule — the new interval
        conflicts with any non-terminal assignment of the same unit unless a
        gap of at least four hours separates them in the applicable direction,
        meaning the new `mobilize_at` is at least four hours after the
        existing assignment's `demobilize_at` or the existing assignment's
        `mobilize_at` is at least four hours after the new `demobilize_at`,
        with a gap of exactly four hours permitted and anything tighter
        rejected as `ERR_UNIT_OVERLAP_BUFFER`".

        Design: Difficulty/boundary_precision_check/equipment_buffer_exact_four_hour_gap_allowed
        """
        ctx, unit = _planned_ctx_with_unit("CKT-BP2")
        create_assignment(unit["id"], ctx["job"]["id"],
                          mobilize_at="2026-08-10T07:00:00Z",
                          demobilize_at="2026-08-10T11:00:00Z")
        second = validate_success(api.create_assignment(
            {
                "mobile_unit_id": unit["id"],
                "test_job_id": ctx["job"]["id"],
                "mobilize_at": "2026-08-10T15:00:00Z",
                "demobilize_at": "2026-08-10T19:00:00Z",
            },
            DISPATCH,
        ), 201)
        assert second["status"] == "RESERVED", "a gap of exactly 4h00m is permitted"

    def test_gap_of_3h59m_rejected(self, api):
        """PRD §3.5: "with a gap of exactly four hours permitted and anything
        tighter rejected as `ERR_UNIT_OVERLAP_BUFFER`".

        Design: Difficulty/boundary_precision_check/equipment_buffer_exact_four_hour_gap_allowed
        """
        ctx, unit = _planned_ctx_with_unit("CKT-BP2")
        create_assignment(unit["id"], ctx["job"]["id"],
                          mobilize_at="2026-08-10T07:00:00Z",
                          demobilize_at="2026-08-10T11:00:00Z")
        resp = api.create_assignment(
            {
                "mobile_unit_id": unit["id"],
                "test_job_id": ctx["job"]["id"],
                "mobilize_at": "2026-08-10T14:59:00Z",
                "demobilize_at": "2026-08-10T18:59:00Z",
            },
            DISPATCH,
        )
        validate_error(resp, ApiErrorId.ERR_UNIT_OVERLAP_BUFFER)
        assert get_unit(unit["id"])["committed_hours"] == 4.0, (
            "the rejected assignment adds nothing to committed_hours"
        )

    def test_zero_gap_back_to_back_rejected(self, api):
        """PRD §3.5: "the new interval conflicts with any non-terminal
        assignment of the same unit unless a gap of at least four hours
        separates them in the applicable direction, meaning the new
        `mobilize_at` is at least four hours after the existing assignment's
        `demobilize_at` or the existing assignment's `mobilize_at` is at least
        four hours after the new `demobilize_at`".

        Design: Difficulty/resource_temporal_overlap/unit_back_to_back_rejected_by_buffer
        """
        ctx, unit = _planned_ctx_with_unit("CKT-TO2")
        create_assignment(unit["id"], ctx["job"]["id"],
                          mobilize_at="2026-08-10T07:00:00Z",
                          demobilize_at="2026-08-10T11:00:00Z")
        resp = api.create_assignment(
            {
                "mobile_unit_id": unit["id"],
                "test_job_id": ctx["job"]["id"],
                "mobilize_at": "2026-08-10T11:00:00Z",
                "demobilize_at": "2026-08-10T15:00:00Z",
            },
            DISPATCH,
        )
        validate_error(resp, ApiErrorId.ERR_UNIT_OVERLAP_BUFFER)
        assert get_unit(unit["id"])["committed_hours"] == 4.0

    def test_reverse_direction_exact_four_hour_gap_allowed(self, api):
        """PRD §3.5: "or the existing assignment's `mobilize_at` is at least
        four hours after the new `demobilize_at`, with a gap of exactly four
        hours permitted".

        Design: Difficulty/resource_temporal_overlap/unit_back_to_back_rejected_by_buffer
        """
        ctx, unit = _planned_ctx_with_unit("CKT-TO2")
        create_assignment(unit["id"], ctx["job"]["id"],
                          mobilize_at="2026-08-10T07:00:00Z",
                          demobilize_at="2026-08-10T11:00:00Z")
        # New interval ends 03:00; existing starts 07:00 -> gap exactly 4h.
        earlier = validate_success(api.create_assignment(
            {
                "mobile_unit_id": unit["id"],
                "test_job_id": ctx["job"]["id"],
                "mobilize_at": "2026-08-10T02:00:00Z",
                "demobilize_at": "2026-08-10T03:00:00Z",
            },
            DISPATCH,
        ), 201)
        assert earlier["status"] == "RESERVED"
        assert get_unit(unit["id"])["committed_hours"] == 5.0


class TestCommittedHoursConservation:
    def test_create_adds_duration_hours(self, api):
        """PRD §3.5: "its `duration_hours` is computed as the span from
        `mobilize_at` to `demobilize_at`, converted from seconds to hours and
        rounded half-up to one decimal place; that same amount is added to the
        unit's `committed_hours`; and the unit transitions `AVAILABLE` →
        `ASSIGNED`."

        Design: Difficulty/compensating_invariant/assignment_create_cancel_conserves_committed_hours
        """
        ctx, unit = _planned_ctx_with_unit("CKT-CI1")
        assignment = create_assignment(unit["id"], ctx["job"]["id"],
                                       mobilize_at="2026-08-10T07:00:00Z",
                                       demobilize_at="2026-08-10T11:00:00Z")
        assert assignment["duration_hours"] == 4.0
        unit_after = get_unit(unit["id"])
        assert unit_after["committed_hours"] == 4.0
        assert unit_after["status"] == "ASSIGNED"

    def test_confirm_then_cancel_restores_zero(self, api):
        """PRD §3.5: "Every release and every cancellation subtracts exactly
        the assignment's stored `duration_hours` from the unit's
        `committed_hours` — the same value that was added at reservation, so
        repeated cycles cannot drift — and whenever a unit's last assignment
        in `RESERVED`, `CONFIRMED`, or `ACTIVE` leaves that set, the unit
        returns `ASSIGNED` → `AVAILABLE`."

        Design: Difficulty/compensating_invariant/assignment_create_cancel_conserves_committed_hours
        """
        ctx, unit = _planned_ctx_with_unit("CKT-CI1")
        assignment = create_assignment(unit["id"], ctx["job"]["id"],
                                       mobilize_at="2026-08-10T07:00:00Z",
                                       demobilize_at="2026-08-10T11:00:00Z")
        confirm_assignment(assignment["id"])
        cancelled = validate_success(api.cancel_assignment(assignment["id"], DISPATCH))
        assert cancelled["status"] == "CANCELLED"
        unit_after = get_unit(unit["id"])
        assert unit_after["committed_hours"] == 0.0, (
            "create (+4.0) then cancel (-4.0) conserves the pre-create value"
        )
        assert unit_after["status"] == "AVAILABLE"


class TestTerminalAssignmentLockdown:
    def test_cancel_after_release_rejected(self, api):
        """PRD §3.5: "Cancellation ends `RESERVED` or `CONFIRMED` assignments"
        — a `RELEASED` assignment is not in a from-state for cancellation.
        PRD §2.7: "6. **State legality** — the target entity must be in an
        allowed from-state for the requested transition, else
        `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/assignment_cancel_after_release_rejected
        """
        ctx, unit = _planned_ctx_with_unit("CKT-S3")
        assignment = create_assignment(unit["id"], ctx["job"]["id"],
                                       mobilize_at="2026-08-10T07:00:00Z",
                                       demobilize_at="2026-08-10T11:00:00Z")
        confirm_assignment(assignment["id"])
        set_clock("2026-08-10T08:00:00Z")
        validate_success(api.activate_assignment(assignment["id"], DISPATCH))
        validate_success(api.release_assignment(assignment["id"], DISPATCH))

        resp = api.cancel_assignment(assignment["id"], DISPATCH)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        unit_after = get_unit(unit["id"])
        assert unit_after["committed_hours"] == 0.0, "no double subtraction after release"
        assert unit_after["status"] == "AVAILABLE"
