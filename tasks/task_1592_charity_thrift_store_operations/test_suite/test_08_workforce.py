"""Workforce: worker overlap semantics, weekly caps, program caps, seat limits."""
import pytest

from test_helpers import (
    ApiErrorId,
    COORD,
    MGR,
    TEST_USERS,
    assign_worker,
    complete_assignment,
    confirm_assignment,
    create_shift,
    create_worker,
    get_success_data,
    get_worker,
    make_volunteer_headers,
    patch_worker,
    validate_error,
    validate_success,
)


def _get_assignment(api, assignment_id):
    return validate_success(api.get_assignment(assignment_id, MGR))


def _get_shift(api, shift_id):
    return validate_success(api.get_shift(shift_id, MGR))


class TestWorkerOverlapSemantics:
    def test_worker_overlap_unbuffered_touching_allowed(self, api):
        """PRD 3.8: "Double-booking: the worker must hold no other `ASSIGNED` or
        `CONFIRMED` assignment whose interval overlaps the shift's interval —
        intervals that merely touch at an endpoint are allowed and, unlike stop
        windows, no buffer is added — else `ERR_SHIFT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/worker_overlap_unbuffered_touching_allowed
        """
        worker = create_worker("W Vol", "VOLUNTEER")
        shift_a = create_shift("SORTER", "2026-08-12T09:00:00Z",
                               "2026-08-12T12:00:00Z", required_headcount=2)
        shift_b = create_shift("FLOOR", "2026-08-12T12:00:00Z",
                               "2026-08-12T15:00:00Z", required_headcount=2)
        shift_c = create_shift("INTAKE", "2026-08-12T11:59:00Z",
                               "2026-08-12T14:00:00Z", required_headcount=2)

        as_a = assign_worker(shift_a["id"], worker["id"])
        as_b = assign_worker(shift_b["id"], worker["id"])
        assert as_a["status"] == "ASSIGNED"
        assert as_b["status"] == "ASSIGNED", "shifts touching at 12:00 coexist"

        resp = api.assign_worker(shift_c["id"], {"worker_id": worker["id"]}, COORD)
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)
        assert _get_shift(api, shift_c["id"])["assigned_count"] == 0

    def test_touching_on_either_side_containment_rejected(self, api):
        """PRD 3.8: "the worker must hold no other `ASSIGNED` or `CONFIRMED`
        assignment whose interval overlaps the shift's interval — intervals that
        merely touch at an endpoint are allowed and, unlike stop windows, no buffer
        is added — else `ERR_SHIFT_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/worker_overlap_unbuffered_touching_allowed
        """
        worker = create_worker("W Vol", "VOLUNTEER")
        mid = create_shift("SORTER", "2026-08-12T12:00:00Z", "2026-08-12T15:00:00Z",
                           required_headcount=2)
        early = create_shift("FLOOR", "2026-08-12T09:00:00Z", "2026-08-12T12:00:00Z",
                             required_headcount=2)
        inside = create_shift("INTAKE", "2026-08-12T13:00:00Z", "2026-08-12T14:00:00Z",
                              required_headcount=2)

        as_mid = assign_worker(mid["id"], worker["id"])
        as_early = assign_worker(early["id"], worker["id"])
        assert as_mid["status"] == "ASSIGNED"
        assert as_early["status"] == "ASSIGNED", "touching at 12:00 on the left is fine"

        resp = api.assign_worker(inside["id"], {"worker_id": worker["id"]}, COORD)
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)


class TestTransitionalWeeklyCap:
    def test_weekly_hours_boundary(self, api):
        """PRD 3.8: "And the transitional weekly cap: for a TRANSITIONAL worker, sum
        the durations of the worker's assignments in `ASSIGNED`, `CONFIRMED`, or
        `COMPLETED` whose shifts start in the same ISO week — the week bounded by
        Monday 00:00 UTC — as the new shift's `starts_at`, where each duration is the
        shift's length in seconds divided by 3600 and rounded half up to two decimal
        places; the running total plus the new shift's duration must stay at or under
        20.0 hours, with exactly 20.0 allowed, else `ERR_WEEKLY_HOURS_EXCEEDED`."

        Design: Corner/calculations/weekly_hours_boundary
        """
        worker = create_worker("W Trans", "TRANSITIONAL")
        # All three shifts start in ISO week 2026-W33 (Mon 2026-08-10).
        shift_a = create_shift("SORTER", "2026-08-10T08:00:00Z", "2026-08-10T20:00:00Z")
        shift_b = create_shift("SORTER", "2026-08-11T09:00:00Z", "2026-08-11T17:00:00Z")
        shift_c = create_shift("FLOOR", "2026-08-12T10:00:00Z", "2026-08-12T10:30:00Z")

        as_a = assign_worker(shift_a["id"], worker["id"])   # 12h
        as_b = assign_worker(shift_b["id"], worker["id"])   # 8h -> exactly 20.0
        assert as_a["status"] == "ASSIGNED"
        assert as_b["status"] == "ASSIGNED", "exactly 20.0 hours is allowed"

        resp = api.assign_worker(shift_c["id"], {"worker_id": worker["id"]}, COORD)
        validate_error(resp, ApiErrorId.ERR_WEEKLY_HOURS_EXCEEDED)  # 20.5 > 20.0
        assert _get_shift(api, shift_c["id"])["assigned_count"] == 0


class TestProgramCapAndExtension:
    def test_program_cap_auto_transition_and_extension(self, api):
        """PRD 3.8: "For a TRANSITIONAL worker the credit also tests the program cap:
        when `credited_hours` reaches or exceeds the effective cap — landing exactly
        on the cap flips the worker — the worker moves automatically to
        `CAP_REACHED`; VOLUNTEER and STAFF workers are never capped."
        PRD 3.8: "A worker's effective cap is `program_cap_hours` plus
        `cap_extension_hours`, and when an extension raises the effective cap above
        the worker's `credited_hours`, a `CAP_REACHED` worker automatically returns
        to `ACTIVE`."
        PRD 3.8: "assigning an `INACTIVE` worker fails with `ERR_WORKER_NOT_ACTIVE`,
        and assigning a `CAP_REACHED` one fails with `ERR_WORKER_CAP_REACHED`."

        Design: Corner/calculations/program_cap_auto_transition_and_extension
        """
        worker = create_worker("W Cap", "TRANSITIONAL", program_cap_hours=8)
        shifts = [
            create_shift("SORTER", f"2026-08-{10 + n}T09:00:00Z",
                         f"2026-08-{10 + n}T13:00:00Z")
            for n in range(3)  # Mon/Tue/Wed of ISO week 2026-W33, 4h each
        ]
        a1 = assign_worker(shifts[0]["id"], worker["id"])
        confirm_assignment(a1["id"])
        complete_assignment(a1["id"])

        a2 = assign_worker(shifts[1]["id"], worker["id"])
        confirm_assignment(a2["id"])
        completed = complete_assignment(a2["id"])
        assert completed["status"] == "COMPLETED", "the capping completion succeeds"

        worker_after = get_worker(worker["id"])
        assert worker_after["credited_hours"] == pytest.approx(8)
        assert worker_after["status"] == "CAP_REACHED", "landing exactly on the cap flips"

        resp = api.assign_worker(shifts[2]["id"], {"worker_id": worker["id"]}, COORD)
        validate_error(resp, ApiErrorId.ERR_WORKER_CAP_REACHED)

        # A manager extension to effective cap 12 (> 8 credited) reactivates.
        patch_worker(worker["id"], {"cap_extension_hours": 4},
                     headers=TEST_USERS["store_manager_headers"])
        worker_ext = get_worker(worker["id"])
        assert worker_ext["status"] == "ACTIVE"
        a3 = assign_worker(shifts[2]["id"], worker["id"])
        assert a3["status"] == "ASSIGNED"


class TestSeatCapacity:
    def test_shift_full_boundary(self, api):
        """PRD 3.8: "Seat capacity: `assigned_count` must still be below
        `required_headcount`, else `ERR_SHIFT_FULL`."
        PRD 3.8: "A shift's `assigned_count` tracks seats currently held — the number
        of its assignments in `ASSIGNED` or `CONFIRMED`."

        Design: Corner/validations/shift_full_boundary
        """
        w1 = create_worker("W A", "VOLUNTEER")
        w2 = create_worker("W B", "VOLUNTEER")
        shift = create_shift("INTAKE", "2026-08-10T09:00:00Z", "2026-08-10T12:00:00Z",
                             required_headcount=1)

        first = assign_worker(shift["id"], w1["id"])
        assert first["status"] == "ASSIGNED", "the single seat fills legally"

        resp = api.assign_worker(shift["id"], {"worker_id": w2["id"]}, COORD)
        validate_error(resp, ApiErrorId.ERR_SHIFT_FULL)
        assert _get_shift(api, shift["id"])["assigned_count"] == 1


class TestAssignmentStateGates:
    def test_assign_inactive_worker_rejected(self, api):
        """PRD 3.8: "assigning an `INACTIVE` worker fails with
        `ERR_WORKER_NOT_ACTIVE`, and assigning a `CAP_REACHED` one fails with
        `ERR_WORKER_CAP_REACHED`."

        Design: Corner/errors/assign_inactive_worker_rejected
        """
        worker = create_worker("W Ina", "VOLUNTEER")
        patch_worker(worker["id"], {"status": "INACTIVE"})
        shift = create_shift("SORTER", "2026-08-10T09:00:00Z", "2026-08-10T12:00:00Z",
                             required_headcount=2)

        resp = api.assign_worker(shift["id"], {"worker_id": worker["id"]}, COORD)
        validate_error(resp, ApiErrorId.ERR_WORKER_NOT_ACTIVE)
        assert _get_shift(api, shift["id"])["assigned_count"] == 0

    def test_assignment_terminal_lockdown(self, api):
        """PRD 3.8: "Acting on an assignment from the wrong state — confirming one
        not `ASSIGNED`, completing one not `CONFIRMED`, or no-showing or cancelling
        one already terminal — fails with `ERR_ASSIGNMENT_INVALID_STATE`."

        Design: Corner/state_machines/assignment_terminal_lockdown
        """
        worker = create_worker("W Vol", "VOLUNTEER")
        shift = create_shift("SORTER", "2026-08-10T09:00:00Z", "2026-08-10T13:00:00Z")
        assignment = assign_worker(shift["id"], worker["id"])
        get_success_data(api.no_show_assignment(assignment["id"], COORD))

        resp1 = api.complete_assignment(assignment["id"], COORD)
        validate_error(resp1, ApiErrorId.ERR_ASSIGNMENT_INVALID_STATE)
        resp2 = api.cancel_assignment(assignment["id"], COORD)
        validate_error(resp2, ApiErrorId.ERR_ASSIGNMENT_INVALID_STATE)

        after = _get_assignment(api, assignment["id"])
        assert after["status"] == "NO_SHOW"
        assert get_worker(worker["id"])["credited_hours"] == pytest.approx(0), (
            "a no-show never credits hours"
        )


class TestVolunteerOwnership:
    def test_volunteer_cannot_confirm_others_assignment(self, api):
        """PRD 3.8: "Confirming an assignment moves `ASSIGNED` → `CONFIRMED`; a
        `Volunteer` may confirm only their own assignment — the acting `X-User-ID`
        must equal the assignment's `worker_id`, else `ERR_FORBIDDEN_OWNERSHIP` —
        while a `VolunteerCoordinator` may confirm any."

        Design: Corner/rbac/volunteer_cannot_confirm_others_assignment
        """
        w1 = create_worker("W One", "VOLUNTEER")
        w2 = create_worker("W Two", "VOLUNTEER")
        shift = create_shift("SORTER", "2026-08-10T09:00:00Z", "2026-08-10T12:00:00Z",
                             required_headcount=2)
        assignment = assign_worker(shift["id"], w1["id"])

        resp = api.confirm_assignment(assignment["id"], make_volunteer_headers(w2["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP)

        confirmed = confirm_assignment(assignment["id"], make_volunteer_headers(w1["id"]))
        assert confirmed["status"] == "CONFIRMED"
