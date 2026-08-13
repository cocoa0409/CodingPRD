"""Occupant relocation (capacity, unit availability with the cleaning
buffer), the re-occupancy gate on returns, and project closeout including
terminal lockdown."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    add_supervisor,
    api_client,
    complete_work,
    create_relocation_entity,
    create_relocation_payload,
    create_unit_entity,
    get_project,
    get_unit,
    record_clearance_result,
    return_relocation,
    set_clock,
    setup_assessed_project,
    setup_closed_project,
    setup_in_progress_project,
    setup_start_ready_project,
    start_project,
    supervisor_headers,
    validate_error,
    validate_success,
)


class TestRelocationCreation:
    def test_relocation_over_capacity_rejected(self):
        """PRD section 3.8: "Capacity is a separate check: `persons` may not
        exceed the unit's `capacity_persons`, failing with
        `ERR_UNIT_CAPACITY_EXCEEDED` (422)."

        Design: Corner/validations/relocation_over_capacity_rejected
        """
        ctx = setup_assessed_project(name="P-V5", base_abatement_cost_cents=1_000)
        unit = create_unit_entity(unit_label="U-CAP", capacity_persons=4)
        resp = api_client.create_relocation(
            create_relocation_payload(
                ctx["project"]["id"], unit["id"],
                household_name="Big Household", persons=5,
                move_out_at="2026-08-10T00:00:00Z"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_UNIT_CAPACITY_EXCEEDED)


class TestUnitCleaningBuffer:
    def _setup_unit_in_cleaning(self):
        """Drive P1 to reoccupancy OPEN with a HOUSED household in U1 (the
        relocation is created while P1 is still ASSESSED, before work
        starts), return it at 2026-08-12T10:00:00Z (unit CLEANING until
        2026-08-13T10:00:00Z), and stand up a second ASSESSED project P2."""
        ctx1 = setup_start_ready_project(name="P-OV2a")
        unit = create_unit_entity(unit_label="U-BUF", capacity_persons=4)
        relocation = create_relocation_entity(
            ctx1["project"]["id"], unit["id"], household_name="Household H",
            persons=3, move_out_at="2026-08-10T00:00:00Z")
        start_project(ctx1)
        complete_work(ctx1)
        record_clearance_result(ctx1, "2026-08-12T08:00:00Z", 0.008)
        record_clearance_result(ctx1, "2026-08-12T09:00:00Z", 0.009)
        assert get_project(ctx1["project"]["id"])["reoccupancy_status"] == "OPEN"
        set_clock("2026-08-12T10:00:00Z")
        returned = return_relocation(relocation["id"])
        assert returned["returned_at"].startswith("2026-08-12T10:00:00")
        unit_after = get_unit(unit["id"])
        assert unit_after["status"] == "CLEANING"
        assert unit_after["cleaning_until"].startswith("2026-08-13T10:00:00")
        ctx2 = setup_assessed_project(name="P-OV2b",
                                      base_abatement_cost_cents=1_000)
        return ctx2, unit

    def test_booking_before_cleaning_until_rejected(self):
        """PRD section 3.8: "Unit availability is checked two ways, both
        failing with `ERR_UNIT_NOT_AVAILABLE` (409): the unit must be
        `AVAILABLE`, or `CLEANING` with the requested `move_out_at` at or
        after its `cleaning_until`; and no other relocation record for that
        unit may be in `HOUSED` or `EXTENDED` status."

        Design: Difficulty/resource_temporal_overlap/relocation_unit_cleaning_buffer_semantics
        """
        ctx2, unit = self._setup_unit_in_cleaning()
        # One hour before cleaning_until: still blocked.
        resp = api_client.create_relocation(
            create_relocation_payload(
                ctx2["project"]["id"], unit["id"],
                household_name="Household X", persons=2,
                move_out_at="2026-08-13T09:00:00Z"),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_AVAILABLE)

    def test_booking_at_cleaning_until_allowed(self):
        """PRD section 3.8: "the unit must be `AVAILABLE`, or `CLEANING` with
        the requested `move_out_at` at or after its `cleaning_until`"
        PRD section 3.8: "A created record is `HOUSED` with `extension_count`
        at zero and `returned_at` unset, and the unit automatically
        transitions from `AVAILABLE` to `OCCUPIED`."

        Design: Difficulty/resource_temporal_overlap/relocation_unit_cleaning_buffer_semantics
        """
        ctx2, unit = self._setup_unit_in_cleaning()
        # Exactly at cleaning_until: at-or-after semantics allow the booking.
        resp = api_client.create_relocation(
            create_relocation_payload(
                ctx2["project"]["id"], unit["id"],
                household_name="Household X", persons=2,
                move_out_at="2026-08-13T10:00:00Z"),
            ADMIN)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "HOUSED", \
            "move_out_at exactly at cleaning_until must be allowed"
        assert data["extension_count"] == 0


class TestRelocationReturnGate:
    def test_return_blocked_without_two_clearance_passes(self):
        """PRD section 3.8: "Return requires the project's
        `reoccupancy_status` to be `OPEN` and otherwise fails with
        `ERR_REOCCUPANCY_BLOCKED` (409)."
        PRD section 3.6: "The `reoccupancy_status` is `OPEN` exactly when
        there are zero fails and at least 2 passes in that window; otherwise
        it is `BLOCKED`."

        Design: Difficulty/cross_entity_state_dependency/relocation_return_requires_clearance_pass
        """
        ctx = setup_in_progress_project(name="P-XD2")
        unit = create_unit_entity(unit_label="U1", capacity_persons=4)
        relocation = create_relocation_entity(
            ctx["project"]["id"], unit["id"], household_name="Household H",
            persons=3, move_out_at="2026-08-10T00:00:00Z")
        complete_work(ctx)
        # Zero clearance passes: the gate is BLOCKED.
        resp = api_client.return_relocation(relocation["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_REOCCUPANCY_BLOCKED)

    def test_return_succeeds_after_two_passes_and_unit_enters_cleaning(self):
        """PRD section 3.8: "The return stamps `returned_at` from the logical
        clock and moves the unit from `OCCUPIED` to `CLEANING` with
        `cleaning_until` set one day after the return; the clock sweep later
        releases the unit from `CLEANING` back to `AVAILABLE` once that
        instant is reached."
        PRD section 3.8: "Return requires the project's `reoccupancy_status`
        to be `OPEN` and otherwise fails with `ERR_REOCCUPANCY_BLOCKED`
        (409)."

        Design: Difficulty/cross_entity_state_dependency/relocation_return_requires_clearance_pass
        """
        ctx = setup_in_progress_project(name="P-XD2B")
        unit = create_unit_entity(unit_label="U1", capacity_persons=4)
        relocation = create_relocation_entity(
            ctx["project"]["id"], unit["id"], household_name="Household H",
            persons=3, move_out_at="2026-08-10T00:00:00Z")
        complete_work(ctx)
        record_clearance_result(ctx, "2026-08-12T08:00:00Z", 0.008)
        record_clearance_result(ctx, "2026-08-12T09:00:00Z", 0.009)
        project = get_project(ctx["project"]["id"])
        assert project["reoccupancy_status"] == "OPEN", \
            "two passes since last verification must open the gate"
        set_clock("2026-08-12T10:00:00Z")
        returned = return_relocation(relocation["id"])
        assert returned["status"] == "RETURNED"
        assert returned["returned_at"].startswith("2026-08-12T10:00:00"), (
            f"returned_at must be stamped from the logical clock, got "
            f"{returned['returned_at']}"
        )
        unit_after = get_unit(unit["id"])
        assert unit_after["status"] == "CLEANING", \
            "the unit must enter CLEANING on return"
        assert unit_after["cleaning_until"].startswith("2026-08-13T10:00:00"), (
            f"cleaning_until = returned_at + 1 day, got "
            f"{unit_after['cleaning_until']}"
        )


class TestCloseout:
    def test_complete_work_before_start_rejected(self):
        """PRD section 3.6: "a `Supervisor` completes the work phase, moving
        the project from `IN_PROGRESS` to `AWAITING_CLEARANCE`"
        PRD section 2.10: "any attempt to act on a resource from a state that
        does not permit the transition — terminal or otherwise — is rejected
        with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/complete_work_before_start_rejected
        """
        ctx = setup_assessed_project(name="P-SM7", base_abatement_cost_cents=1_000)
        supervisor = add_supervisor()
        resp = api_client.complete_work(ctx["project"]["id"],
                                        supervisor_headers(supervisor))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_close_with_housed_relocation_rejected(self):
        """PRD section 3.8: "The transition from `AWAITING_CLEARANCE` to
        `CLOSED` evaluates its gates in order: first the re-occupancy gate —
        the project's `reoccupancy_status` must be `OPEN` and every relocation
        record of the project must be `RETURNED`, with either failure reported
        as `ERR_REOCCUPANCY_BLOCKED` (409); then the waste ledger — every
        manifest of the project must be in `CONFIRMED` or `VOIDED` status,
        with any other status reported as `ERR_MANIFESTS_OUTSTANDING` (409)."

        Design: Corner/validations/close_with_housed_relocation_rejected
        """
        # The relocation is created while the project is still ASSESSED,
        # before work starts; the project then reaches AWAITING_CLEARANCE
        # with reoccupancy OPEN while the household stays HOUSED.
        ctx = setup_start_ready_project(name="P-V12")
        unit = create_unit_entity(unit_label="U1", capacity_persons=4)
        relocation = create_relocation_entity(
            ctx["project"]["id"], unit["id"], household_name="Household H",
            persons=3, move_out_at="2026-08-10T00:00:00Z")
        assert relocation["status"] == "HOUSED"
        start_project(ctx)
        complete_work(ctx)
        record_clearance_result(ctx, "2026-08-12T08:00:00Z", 0.008)
        record_clearance_result(ctx, "2026-08-12T09:00:00Z", 0.009)
        assert get_project(ctx["project"]["id"])["reoccupancy_status"] == "OPEN"
        # Reoccupancy is OPEN and there are no manifests; the HOUSED record
        # alone must block the close.
        resp = api_client.close_project(ctx["project"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_REOCCUPANCY_BLOCKED)
        project = get_project(ctx["project"]["id"])
        assert project["status"] == "AWAITING_CLEARANCE", \
            "a rejected close must leave the project AWAITING_CLEARANCE"

    def test_closed_project_locks_all_actions(self):
        """PRD section 3.8: "A successful close increments the project's
        `version` by 1, and `CLOSED` is terminal"
        PRD section 2.10: "Terminal states are locked. A `CLOSED` project, a
        `FINALIZED` survey, a `REPORTED` sample or air test, a `COMPLETED` or
        `CANCELLED` assignment, a `SUPERSEDED` notification, a `CONFIRMED` or
        `VOIDED` manifest, a `SUSPENDED` facility, and a `RETURNED` relocation
        record admit no further transitions; any attempt to act on a resource
        from a state that does not permit the transition — terminal or
        otherwise — is rejected with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/closed_project_locks_all_actions
        """
        ctx = setup_closed_project(name="P-SM8")
        assert ctx["project"]["status"] == "CLOSED"
        resp = api_client.suspend_project(ctx["project"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
