"""Labor planning: harvest cost projection, weekly hour caps, overlap, headcount,
certification, ownership, and shift OCC (PRD §3.7, §2.9)."""
import pytest

from test_helpers import (
    TEST_USERS, ApiErrorId,
    validate_success, validate_error,
    create_crop_with_active_recipe, create_loop_rack, create_growing_batch,
    set_clock, create_worker, create_published_shift, assign_worker, assign_worker_ok,
    confirm_assignment, create_assignment_payload,
    make_worker_headers,
)

LP = TEST_USERS["labor_planner_headers"]


class TestHarvestLaborCost:
    def _harvest_shift_scenario(self, api):
        """Two GROWING batches (8 towers each, 100.00 lb projected, harvest date
        2026-08-24) plus a HARVEST_CREW shift on that date (rate 2200 cents/h)."""
        crop, _ = create_crop_with_active_recipe()
        _, _, towers_a = create_loop_rack(loop_code="WL-A", rack_code="R-01", tower_count=8)
        _, _, towers_b = create_loop_rack(loop_code="WL-B", rack_code="R-02", tower_count=8)
        create_growing_batch(crop["id"], [t["id"] for t in towers_a], seed_clock="2026-08-03T06:00:00Z")
        create_growing_batch(crop["id"], [t["id"] for t in towers_b], seed_clock="2026-08-03T06:00:00Z")
        shift = create_published_shift(
            shift_date="2026-08-24", role_type="HARVEST_CREW",
            start_at="2026-08-24T07:00:00Z", end_at="2026-08-24T15:00:00Z",
            headcount_required=2, planned_hourly_rate_cents=2200)
        worker = create_worker(certifications=["HARVEST_CREW"], full_name="W One")
        return shift, worker

    def test_projected_cost_at_publish_is_all_overtime(self, api):
        """PRD §3.7: "The required crew hours are that sum rounded up to the next whole
        hour. An 8-hour shift times the `headcount_assigned` gives the regular-hours
        capacity: regular hours are the smaller of required crew hours and that
        capacity, and overtime hours are whatever required hours exceed it, floored at
        zero. `projected_labor_cost_cents` is then regular hours times
        `planned_hourly_rate_cents` plus overtime hours times
        `planned_hourly_rate_cents` times 1.5, rounded half-up to whole cents."

        Design: Difficulty/combinatorial_formula/harvest_labor_cost_nested_min_max
        """
        shift, _ = self._harvest_shift_scenario(api)
        # required = ceil(100/60 + 100/60) = 4; capacity at 0 assigned = 0
        assert shift["headcount_assigned"] == 0
        assert shift["projected_labor_cost_cents"] == 13200, "4 OT hours x 2200 x 1.5"

    def test_projected_cost_drops_after_assignment(self, api):
        """PRD §3.7: "An 8-hour shift times the `headcount_assigned` gives the
        regular-hours capacity" — with one assigned worker the same formula prices
        4 regular hours and no overtime.

        Design: Difficulty/combinatorial_formula/harvest_labor_cost_nested_min_max
        """
        shift, worker = self._harvest_shift_scenario(api)
        assign_worker_ok(shift["id"], worker["id"])
        after = validate_success(api.get_labor_shift(shift["id"], LP))
        assert after["headcount_assigned"] == 1
        assert after["projected_labor_cost_cents"] == 8800, "4 regular hours x 2200"


class TestWeeklyHoursBoundaries:
    def _worker_with_six_assignments(self, api):
        """Worker W1 assigned to six 8h PACK_CREW shifts Mon 2026-08-03 .. Sat
        2026-08-08, plus a seventh 2h Sunday shift left unassigned."""
        set_clock("2026-08-03T00:00:00Z")
        worker = create_worker(certifications=["PACK_CREW"], full_name="W One")
        shifts = []
        for day in ("03", "04", "05", "06", "07", "08"):
            shifts.append(create_published_shift(
                shift_date=f"2026-08-{day}", role_type="PACK_CREW",
                start_at=f"2026-08-{day}T07:00:00Z", end_at=f"2026-08-{day}T15:00:00Z"))
        sunday = create_published_shift(
            shift_date="2026-08-09", role_type="PACK_CREW",
            start_at="2026-08-09T07:00:00Z", end_at="2026-08-09T09:00:00Z")
        for shift in shifts:
            assign_worker_ok(shift["id"], worker["id"])
        return worker, shifts, sunday

    def test_exactly_40_hours_is_not_overtime(self, api):
        """PRD §3.7: "Hours beyond 40.0 in a week count as overtime; exactly 40.00 hours
        is not overtime."

        Design: Difficulty/boundary_precision_check/weekly_hours_exactly_40_no_overtime_and_48_hard_cap
        """
        worker, shifts, _ = self._worker_with_six_assignments(api)
        # The Friday (5th) assignment brought the worker to exactly 40.00 weekly
        # hours; that shift's overtime was computed at its own assignment.
        friday = validate_success(api.get_labor_shift(shifts[4]["id"], LP))
        assert friday["overtime_hours"] == pytest.approx(0.00), \
            "reaching exactly 40.00 weekly hours accrues no overtime"
        w = validate_success(api.get_worker(worker["id"], LP))
        assert w["scheduled_hours_current_week"] == pytest.approx(48.00)

    def test_exactly_48_allowed_50_rejected(self, api):
        """PRD §3.7: "a total strictly above 48.00 hours is rejected with
        `ERR_WEEKLY_HOURS_EXCEEDED`, while exactly 48.00 is allowed."

        Design: Difficulty/boundary_precision_check/weekly_hours_exactly_40_no_overtime_and_48_hard_cap
        """
        worker, shifts, sunday = self._worker_with_six_assignments(api)
        saturday = validate_success(api.get_labor_shift(shifts[5]["id"], LP))
        assert saturday["overtime_hours"] == pytest.approx(8.00), \
            "48.00 weekly hours is 8.00 beyond the 40.0 regular band"
        w = validate_success(api.get_worker(worker["id"], LP))
        assert w["scheduled_hours_current_week"] == pytest.approx(48.00)

        resp, _ = assign_worker(sunday["id"], worker["id"])  # would make 50.00
        validate_error(resp, ApiErrorId.ERR_WEEKLY_HOURS_EXCEEDED)


class TestAssignmentConservation:
    def test_assign_accrues_hours_and_headcount(self, api):
        """PRD §3.7: "A successful assignment is born with `assignment_status`
        `ASSIGNED`, bound to its `shift_id`, raises `headcount_assigned` by one,
        recomputes the worker's weekly hours".

        Design: Difficulty/compensating_invariant/worker_hours_conserved_under_assign_release
        """
        set_clock("2026-08-03T00:00:00Z")
        worker = create_worker(certifications=["PACK_CREW"])
        shift = create_published_shift()
        assignment = assign_worker_ok(shift["id"], worker["id"])
        assert assignment["assignment_status"] == "ASSIGNED"

        w = validate_success(api.get_worker(worker["id"], LP))
        assert w["scheduled_hours_current_week"] == pytest.approx(8.00)
        s = validate_success(api.get_labor_shift(shift["id"], LP))
        assert s["headcount_assigned"] == 1

    def test_release_restores_hours_and_headcount(self, api):
        """PRD §3.7: "Releasing — the compensating action available to the
        `LaborPlanner` from `ASSIGNED` or `CONFIRMED` — moves the assignment to
        `RELEASED`, decrements `headcount_assigned` by one, and recomputes the worker's
        hours and the shift's overtime."

        Design: Difficulty/compensating_invariant/worker_hours_conserved_under_assign_release
        """
        set_clock("2026-08-03T00:00:00Z")
        worker = create_worker(certifications=["PACK_CREW"])
        shift = create_published_shift()
        assignment = assign_worker_ok(shift["id"], worker["id"])

        released = validate_success(
            api.release_shift_assignment(shift["id"], assignment["id"], LP))
        assert released["assignment_status"] == "RELEASED"
        w = validate_success(api.get_worker(worker["id"], LP))
        assert w["scheduled_hours_current_week"] == pytest.approx(0.00)
        s = validate_success(api.get_labor_shift(shift["id"], LP))
        assert s["headcount_assigned"] == 0


class TestAssignmentShiftGate:
    def test_assignment_on_draft_shift_rejected(self, api):
        """PRD §3.7: "The shift must be `PUBLISHED` (`ERR_SHIFT_NOT_PUBLISHED`)".

        Design: Difficulty/cross_entity_state_dependency/assignment_requires_shift_published
        """
        set_clock("2026-08-03T00:00:00Z")
        worker = create_worker(certifications=["HARVEST_CREW"])
        draft = validate_success(api.create_labor_shift(
            {"shift_date": "2026-08-24", "role_type": "HARVEST_CREW",
             "start_at": "2026-08-24T07:00:00Z", "end_at": "2026-08-24T15:00:00Z",
             "headcount_required": 2, "planned_hourly_rate_cents": 2200}, LP),
            expected_status=201)
        resp = api.create_shift_assignment(
            draft["id"], create_assignment_payload(worker["id"], draft["version"]), LP)
        validate_error(resp, ApiErrorId.ERR_SHIFT_NOT_PUBLISHED)

    def test_assignment_after_publish_succeeds(self, api):
        """PRD §3.7: "Staffing a published shift creates a **ShiftAssignment**" born
        "with `assignment_status` `ASSIGNED`".

        Design: Difficulty/cross_entity_state_dependency/assignment_requires_shift_published
        """
        set_clock("2026-08-03T00:00:00Z")
        worker = create_worker(certifications=["HARVEST_CREW"])
        shift = create_published_shift(
            shift_date="2026-08-24", role_type="HARVEST_CREW",
            start_at="2026-08-24T07:00:00Z", end_at="2026-08-24T15:00:00Z",
            headcount_required=2)
        assignment = assign_worker_ok(shift["id"], worker["id"])
        assert assignment["assignment_status"] == "ASSIGNED"
        assert assignment["shift_id"] == shift["id"]


class TestShiftCompletion:
    def test_shift_complete_requires_confirmed_assignments(self, api):
        """PRD §3.7: "A shift can be completed only after its `end_at` has been reached,
        and only when no assignment remains merely `ASSIGNED` — unconfirmed stragglers
        block completion with `ERR_UNCONFIRMED_ASSIGNMENTS`."

        Design: Corner/state_machines/shift_complete_requires_confirmed_assignments
        """
        set_clock("2026-08-03T00:00:00Z")
        worker = create_worker(certifications=["PACK_CREW"], full_name="W One")
        shift = create_published_shift()  # 2026-08-05 07:00-15:00
        assignment = assign_worker_ok(shift["id"], worker["id"])

        set_clock("2026-08-05T15:00:00Z")  # end_at reached
        resp = api.complete_labor_shift(shift["id"], LP)
        validate_error(resp, ApiErrorId.ERR_UNCONFIRMED_ASSIGNMENTS)

        confirm_assignment(shift["id"], assignment["id"], worker["id"])
        completed = validate_success(api.complete_labor_shift(shift["id"], LP))
        assert completed["shift_status"] == "COMPLETED"


class TestAssignmentOwnership:
    def test_worker_cannot_confirm_others_assignment(self, api):
        """PRD §3.7: "a `Worker` confirms only their own assignment, meaning `X-User-ID`
        must equal the assignment's `worker_id`" — a mismatch is
        `ERR_SEGREGATION_OF_DUTIES` (PRD §2.10 tier 3).

        Design: Corner/errors/worker_cannot_confirm_others_assignment
        """
        set_clock("2026-08-03T00:00:00Z")
        w1 = create_worker(certifications=["PACK_CREW"], full_name="W One")
        w2 = create_worker(certifications=["PACK_CREW"], full_name="W Two")
        shift = create_published_shift(headcount_required=2)
        assignment = assign_worker_ok(shift["id"], w1["id"])

        resp = api.confirm_shift_assignment(shift["id"], assignment["id"],
                                            make_worker_headers(w2["id"]))
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        confirmed = confirm_assignment(shift["id"], assignment["id"], w1["id"])
        assert confirmed["assignment_status"] == "CONFIRMED"


class TestAssignmentConstraints:
    def test_shift_overlap_strict_but_adjacent_allowed(self, api):
        """PRD §3.7: "the worker must have no existing assignment whose half-open window
        overlaps the shift's (`ERR_SHIFT_OVERLAP`)". PRD §2.6: "labor shift assignments
        occupy the half-open interval from `start_at` (inclusive) to `end_at`
        (exclusive) ... two intervals that merely touch ... do not overlap; adjacency is
        always allowed."

        Design: Corner/errors/shift_overlap_strict_but_adjacent_allowed
        """
        set_clock("2026-08-03T00:00:00Z")
        worker = create_worker(certifications=["PACK_CREW"], full_name="W One")
        s1 = create_published_shift(start_at="2026-08-05T07:00:00Z", end_at="2026-08-05T15:00:00Z")
        s2 = create_published_shift(start_at="2026-08-05T12:00:00Z", end_at="2026-08-05T20:00:00Z")
        s3 = create_published_shift(start_at="2026-08-05T15:00:00Z", end_at="2026-08-05T23:00:00Z")
        assign_worker_ok(s1["id"], worker["id"])

        resp, _ = assign_worker(s2["id"], worker["id"])  # 12:00 < 15:00: interior overlap
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)

        adjacent = assign_worker_ok(s3["id"], worker["id"])  # starts exactly at 15:00
        assert adjacent["assignment_status"] == "ASSIGNED"
        w = validate_success(api.get_worker(worker["id"], LP))
        assert w["scheduled_hours_current_week"] == pytest.approx(16.00)

    def test_certification_missing_rejected(self, api):
        """PRD §3.7: "the worker's `certifications` must include the shift's `role_type`
        (`ERR_CERTIFICATION_MISSING`)".

        Design: Corner/errors/certification_missing_rejected
        """
        set_clock("2026-08-03T00:00:00Z")
        worker = create_worker(certifications=["PACK_CREW"], full_name="W One")
        shift = create_published_shift(
            role_type="HARVEST_CREW",
            start_at="2026-08-05T07:00:00Z", end_at="2026-08-05T15:00:00Z")
        resp, _ = assign_worker(shift["id"], worker["id"])
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_MISSING)

    def test_headcount_exceeded_rejected(self, api):
        """PRD §3.7: "the assignment may not push `headcount_assigned` past
        `headcount_required` (`ERR_HEADCOUNT_EXCEEDED`)".

        Design: Corner/errors/headcount_exceeded_rejected
        """
        set_clock("2026-08-03T00:00:00Z")
        w1 = create_worker(certifications=["PACK_CREW"], full_name="W One")
        w2 = create_worker(certifications=["PACK_CREW"], full_name="W Two")
        shift = create_published_shift(headcount_required=1)
        assign_worker_ok(shift["id"], w1["id"])

        resp, _ = assign_worker(shift["id"], w2["id"])
        validate_error(resp, ApiErrorId.ERR_HEADCOUNT_EXCEEDED)
        s = validate_success(api.get_labor_shift(shift["id"], LP))
        assert s["headcount_assigned"] == 1


class TestAssignmentOcc:
    def test_occ_assignment_create_stale_shift_version(self, api):
        """PRD §2.9: "Adding an assignment to a labor shift requires
        `expected_labor_shift_version`, the client-observed `version` of the parent
        `LaborShift`" and "If the supplied value does not equal the parent entity's
        current `version` ... the request is rejected with `ERR_STALE_VERSION`
        (HTTP 412), and the client must re-read the parent and retry." PRD §3.7: a
        successful assignment "increments the shift's `version` by one."

        Design: Corner/cross_cutting_layers/occ_assignment_create_stale_shift_version
        """
        set_clock("2026-08-03T00:00:00Z")
        w1 = create_worker(certifications=["PACK_CREW"], full_name="W One")
        w2 = create_worker(certifications=["PACK_CREW"], full_name="W Two")
        shift = create_published_shift(headcount_required=2)
        v_pub = shift["version"]

        a1 = validate_success(api.create_shift_assignment(
            shift["id"], create_assignment_payload(w1["id"], v_pub), LP), expected_status=201)
        assert a1["assignment_status"] == "ASSIGNED"

        stale = api.create_shift_assignment(
            shift["id"], create_assignment_payload(w2["id"], v_pub), LP)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh = validate_success(api.get_labor_shift(shift["id"], LP))["version"]
        assert fresh == v_pub + 1, "assignment increments the shift version by one"
        a2 = validate_success(api.create_shift_assignment(
            shift["id"], create_assignment_payload(w2["id"], fresh), LP), expected_status=201)
        assert a2["assignment_status"] == "ASSIGNED"
        s = validate_success(api.get_labor_shift(shift["id"], LP))
        assert s["headcount_assigned"] == 2
