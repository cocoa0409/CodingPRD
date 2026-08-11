"""Homes, bed assignments, shifts: gates, capacity, overlap semantics.

PRD 3.1 (homes), 3.4 (shifts/staffing), 3.5 (beds).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    admit_resident,
    create_bed_assignment_payload,
    create_evv_visit_payload,
    create_shift_payload,
    get_success_data,
    make_case_manager_headers,
    make_dsp_headers,
    make_qidp_headers,
    set_clock,
    setup_agency,
    setup_agency_with_clinical_staff,
    setup_agency_with_core_staff,
    setup_billable_pipeline,
    setup_enrolled_individual,
    setup_home,
    setup_staff,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["agency_admin_headers"]
ANY = TEST_USERS["any_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
BILL1 = TEST_USERS["billing_headers"]


class TestHomeCapacityExactFill:
    """Admission capacity gate: exact fill allowed, overflow rejected (PRD 3.5)."""

    def _setup_one_bed_home_with_pending(self, api):
        base = setup_agency_with_core_staff()
        agency, cm, q = base["agency"], base["cm"], base["q"]
        home = setup_home(agency, certified_bed_count=1)
        ind1 = setup_enrolled_individual(agency, cm, q, legal_name="Ind One")
        ind2 = setup_enrolled_individual(agency, cm, q, legal_name="Ind Two")
        set_clock("2026-06-01T00:00:00Z")
        ba1 = get_success_data(api_client.create_bed_assignment(
            create_bed_assignment_payload(home["id"], "R1-A", ind1["id"], move_in_date="2026-06-01"),
            make_case_manager_headers(cm["id"]),
        ))
        return home, cm, ind2, ba1

    def test_exact_fill_of_last_bed_allowed(self, api):
        """PRD 3.5: "the projected census at `move_in_date`, plus one for the
        new admission, must be no greater than the home's `certified_bed_count`;
        filling the last bed exactly is permitted."

        Design: Difficulty/boundary_precision_check/home_capacity_exact_fill_allowed
        """
        home, _cm, _ind2, ba1 = self._setup_one_bed_home_with_pending(api)
        assert ba1["status"] == "PENDING"

    def test_one_beyond_capacity_rejected(self, api):
        """PRD 3.5: "A failure here rejects with `ERR_HOME_CAPACITY_EXCEEDED`
        (HTTP 409)."

        Design: Difficulty/boundary_precision_check/home_capacity_exact_fill_allowed
        """
        home, cm, ind2, _ba1 = self._setup_one_bed_home_with_pending(api)
        resp = api_client.create_bed_assignment(
            create_bed_assignment_payload(home["id"], "R1-B", ind2["id"], move_in_date="2026-06-02"),
            make_case_manager_headers(cm["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_HOME_CAPACITY_EXCEEDED)


class TestBedAssignmentHalfOpenAdjacency:
    """Bed overlap half-open interval semantics (PRD 3.5)."""

    def _setup_vacated_bed(self, api):
        base = setup_agency_with_core_staff()
        agency, cm, q = base["agency"], base["cm"], base["q"]
        home = setup_home(agency, certified_bed_count=3)
        inds = [
            setup_enrolled_individual(agency, cm, q, legal_name=f"Ind {n}")
            for n in ("One", "Two", "Three")
        ]
        set_clock("2026-06-01T00:00:00Z")
        ba1 = admit_resident(home, inds[0], cm, q, bed_label="R1-A", move_in_date="2026-06-01")
        get_success_data(api_client.move_out_bed_assignment(
            ba1["id"], make_qidp_headers(q["id"]),
            payload={"move_out_date": "2026-06-16"},
        ))
        return home, cm, inds

    def test_adjacent_assignment_at_move_out_date_accepted(self, api):
        """PRD 3.5: "adjacency — one assignment's `move_out_date` exactly equal
        to the next's `move_in_date` — is permitted".

        Design: Difficulty/resource_temporal_overlap/bed_assignment_half_open_adjacency_allowed
        """
        home, cm, inds = self._setup_vacated_bed(api)
        ba2 = get_success_data(api_client.create_bed_assignment(
            create_bed_assignment_payload(home["id"], "R1-A", inds[1]["id"], move_in_date="2026-06-16"),
            make_case_manager_headers(cm["id"]),
        ))
        assert ba2["status"] == "PENDING"

    def test_one_day_earlier_move_in_rejected_overlap(self, api):
        """PRD 3.5: "The bed-overlap rule is also enforced at assignment
        creation against assignments in `PENDING` or `ACTIVE` status" — a new
        interval intersecting an existing one rejects with `ERR_BED_OVERLAP`.

        Design: Difficulty/resource_temporal_overlap/bed_assignment_half_open_adjacency_allowed
        """
        home, cm, inds = self._setup_vacated_bed(api)
        # First, take the adjacent slot (06-16) so the bed's PENDING interval
        # [2026-06-16, open) exists alongside the ENDED [06-01, 06-16).
        get_success_data(api_client.create_bed_assignment(
            create_bed_assignment_payload(home["id"], "R1-A", inds[1]["id"], move_in_date="2026-06-16"),
            make_case_manager_headers(cm["id"]),
        ))
        # 2026-06-15 intersects the ENDED interval? No — ENDED rows are excluded
        # from the check; intersect the PENDING [06-16, ...) from before it.
        # The overlap rule covers PENDING+ACTIVE; 06-15 start overlaps [06-16, inf)?
        # No: [06-15, ...) intersects [06-16, ...) since both are open-ended.
        resp = api_client.create_bed_assignment(
            create_bed_assignment_payload(home["id"], "R1-A", inds[2]["id"], move_in_date="2026-06-15"),
            make_case_manager_headers(cm["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BED_OVERLAP)


class TestShiftRestBuffer:
    """Shift 8-hour rest buffer: inclusive boundary (PRD 3.4)."""

    def _setup_dsp_with_day_shift(self, api):
        base = setup_agency_with_clinical_staff()
        agency, d1 = base["agency"], base["d1"]
        home = setup_home(agency, certified_bed_count=2)
        set_clock("2026-06-01T00:00:00Z")
        sh1 = get_success_data(api_client.create_shift(
            create_shift_payload(
                home["id"], d1["id"],
                window_start="2026-06-02T07:00:00Z", window_end="2026-06-02T15:00:00Z",
            ), ADMIN,
        ))
        return home, d1, sh1

    def test_exactly_eight_hour_gap_accepted(self, api):
        """PRD 3.4: "the new window's start must be no earlier than eight hours
        after the prior shift's `window_end`". A start exactly 8h after
        satisfies "no earlier than".

        Design: Difficulty/resource_temporal_overlap/shift_rest_buffer_closed_interval
        """
        home, d1, _sh1 = self._setup_dsp_with_day_shift(api)
        sh2 = get_success_data(api_client.create_shift(
            create_shift_payload(
                home["id"], d1["id"],
                window_start="2026-06-02T23:00:00Z", window_end="2026-06-03T07:00:00Z",
                shift_type="NIGHT",
            ), ADMIN,
        ))
        assert sh2["status"] == "SCHEDULED"

    def test_gap_under_eight_hours_rejected(self, api):
        """PRD 3.4: "A violation rejects with `ERR_SHIFT_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/shift_rest_buffer_closed_interval
        """
        home, d1, _sh1 = self._setup_dsp_with_day_shift(api)
        # Accept the exactly-8h NIGHT shift first (07:00 next-day end).
        get_success_data(api_client.create_shift(
            create_shift_payload(
                home["id"], d1["id"],
                window_start="2026-06-02T23:00:00Z", window_end="2026-06-03T07:00:00Z",
                shift_type="NIGHT",
            ), ADMIN,
        ))
        # 7h59m after the night shift's 07:00 end -> 14:59 start.
        resp = api_client.create_shift(
            create_shift_payload(
                home["id"], d1["id"],
                window_start="2026-06-03T14:59:00Z", window_end="2026-06-03T20:00:00Z",
            ), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)
        data, meta = validate_paginated(api_client.list_shifts(
            ANY, params={"staff_member_id": d1["id"]},
        ))
        assert meta["total_count"] == 2


class TestHomeSuspendCascade:
    """Suspend cancels only PENDING assignments; non-ACTIVE home gates (PRD 3.1)."""

    def _setup_home_with_active_and_pending(self, api):
        base = setup_agency_with_clinical_staff()
        agency, cm, q, d1 = base["agency"], base["cm"], base["q"], base["d1"]
        home = setup_home(agency, certified_bed_count=3)
        ind1 = setup_enrolled_individual(agency, cm, q, legal_name="Ind One")
        ind2 = setup_enrolled_individual(agency, cm, q, legal_name="Ind Two")
        set_clock("2026-06-01T00:00:00Z")
        ba1 = admit_resident(home, ind1, cm, q, bed_label="R1", move_in_date="2026-06-01")
        ba2 = get_success_data(api_client.create_bed_assignment(
            create_bed_assignment_payload(home["id"], "R2", ind2["id"], move_in_date="2026-06-10"),
            make_case_manager_headers(cm["id"]),
        ))
        return base, home, ba1, ba2

    def test_suspend_cancels_only_pending_assignments(self, api):
        """PRD 3.1: "the suspension cascades to cancel every `PENDING` bed
        assignment at that home (active assignments are not affected by
        suspension)".

        Design: Corner/state_machines/home_suspend_cancels_only_pending_assignments
        """
        _base, home, ba1, ba2 = self._setup_home_with_active_and_pending(api)
        suspended = get_success_data(api_client.suspend_home(home["id"], COMPLIANCE))
        assert suspended["status"] == "SUSPENDED"
        cancelled, meta_c = validate_paginated(api_client.list_bed_assignments(
            ANY, params={"home_id": home["id"], "status": "CANCELLED"},
        ))
        assert meta_c["total_count"] == 1
        assert cancelled[0]["id"] == ba2["id"]
        active, meta_a = validate_paginated(api_client.list_bed_assignments(
            ANY, params={"home_id": home["id"], "status": "ACTIVE"},
        ))
        assert meta_a["total_count"] == 1
        assert active[0]["id"] == ba1["id"]

    def test_suspended_home_rejects_new_shift(self, api):
        """PRD 3.1: "While a home is not `ACTIVE` (that is, `SUSPENDED` or
        `CLOSED`), five operations are rejected with `ERR_HOME_NOT_ACTIVE`
        (HTTP 409): creating a shift at the home, ...".

        Design: Corner/state_machines/home_suspend_cancels_only_pending_assignments
        """
        base, home, _ba1, _ba2 = self._setup_home_with_active_and_pending(api)
        get_success_data(api_client.suspend_home(home["id"], COMPLIANCE))
        resp = api_client.create_shift(
            create_shift_payload(
                home["id"], base["d1"]["id"],
                window_start="2026-06-03T07:00:00Z", window_end="2026-06-03T15:00:00Z",
            ), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_HOME_NOT_ACTIVE)


class TestHomeCloseGate:
    """Home close blocked until empty (PRD 3.1)."""

    def _setup_occupied_home(self, api):
        base = setup_agency_with_core_staff()
        agency, cm, q = base["agency"], base["cm"], base["q"]
        home = setup_home(agency, certified_bed_count=2)
        ind1 = setup_enrolled_individual(agency, cm, q, legal_name="Ind One")
        ind2 = setup_enrolled_individual(agency, cm, q, legal_name="Ind Two")
        set_clock("2026-06-01T00:00:00Z")
        ba1 = admit_resident(home, ind1, cm, q, bed_label="R1", move_in_date="2026-06-01")
        ba2 = get_success_data(api_client.create_bed_assignment(
            create_bed_assignment_payload(home["id"], "R2", ind2["id"], move_in_date="2026-06-05"),
            make_case_manager_headers(cm["id"]),
        ))
        return home, cm, q, ba1, ba2

    def test_close_with_residents_rejected(self, api):
        """PRD 3.1: "closure is permitted only when `current_occupancy` is zero
        and the home has no `PENDING` bed assignments, and is otherwise rejected
        with `ERR_HOME_OCCUPIED` (HTTP 409)."

        Design: Corner/validations/home_close_blocked_until_last_resident_leaves
        """
        home, _cm, _q, _ba1, _ba2 = self._setup_occupied_home(api)
        resp = api_client.close_home(home["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_HOME_OCCUPIED)

    def test_close_succeeds_after_home_emptied(self, api):
        """PRD 3.1: "From `ACTIVE`, an `AgencyAdmin` may close the home,
        transitioning it to the terminal state `CLOSED`; closure is permitted
        only when `current_occupancy` is zero and the home has no `PENDING` bed
        assignments".

        Design: Corner/validations/home_close_blocked_until_last_resident_leaves
        """
        home, cm, q, ba1, ba2 = self._setup_occupied_home(api)
        validate_error(api_client.close_home(home["id"], ADMIN), ApiErrorId.ERR_HOME_OCCUPIED)
        get_success_data(api_client.cancel_bed_assignment(ba2["id"], make_case_manager_headers(cm["id"])))
        get_success_data(api_client.move_out_bed_assignment(
            ba1["id"], make_qidp_headers(q["id"]), payload={"move_out_date": "2026-06-02"},
        ))
        closed = get_success_data(api_client.close_home(home["id"], ADMIN))
        assert closed["status"] == "CLOSED"


class TestOccupancyReconciliation:
    """current_occupancy tracks source rows (PRD 2.10, 3.5)."""

    def test_occupancy_zero_while_assignment_pending(self, api):
        """PRD 3.5: move-in "transitions a `PENDING` assignment to `ACTIVE`" and
        "On successful move-in the home's `current_occupancy` is recomputed."
        Before move-in the assignment is not a resident.

        Design: Corner/cross_cutting_layers/occupancy_reconciled_after_move_out
        """
        base = setup_agency_with_core_staff()
        agency, cm, q = base["agency"], base["cm"], base["q"]
        home = setup_home(agency, certified_bed_count=2)
        ind = setup_enrolled_individual(agency, cm, q)
        set_clock("2026-06-01T00:00:00Z")
        get_success_data(api_client.create_bed_assignment(
            create_bed_assignment_payload(home["id"], "R1", ind["id"], move_in_date="2026-06-01"),
            make_case_manager_headers(cm["id"]),
        ))
        home_now = get_success_data(api_client.get_home(home["id"], ANY))
        assert home_now["current_occupancy"] == 0

    def test_occupancy_increments_on_move_in_and_decrements_on_move_out(self, api):
        """PRD 2.10: "`GroupHome.current_occupancy` is recomputed whenever a
        `BedAssignment` enters or leaves the `ACTIVE` state".

        Design: Corner/cross_cutting_layers/occupancy_reconciled_after_move_out
        """
        base = setup_agency_with_core_staff()
        agency, cm, q = base["agency"], base["cm"], base["q"]
        home = setup_home(agency, certified_bed_count=2)
        ind = setup_enrolled_individual(agency, cm, q)
        set_clock("2026-06-01T00:00:00Z")
        ba = admit_resident(home, ind, cm, q, bed_label="R1", move_in_date="2026-06-01")
        assert get_success_data(api_client.get_home(home["id"], ANY))["current_occupancy"] == 1
        get_success_data(api_client.move_out_bed_assignment(
            ba["id"], make_qidp_headers(q["id"]), payload={"move_out_date": "2026-06-10"},
        ))
        assert get_success_data(api_client.get_home(home["id"], ANY))["current_occupancy"] == 0


class TestMoveInFutureGate:
    """move_in_date must not be in the future at move-in (PRD 3.5)."""

    def _setup_future_pending_assignment(self, api):
        base = setup_agency_with_core_staff()
        agency, cm, q = base["agency"], base["cm"], base["q"]
        home = setup_home(agency, certified_bed_count=2)
        ind = setup_enrolled_individual(agency, cm, q)
        set_clock("2026-06-01T00:00:00Z")
        ba = get_success_data(api_client.create_bed_assignment(
            create_bed_assignment_payload(home["id"], "R1", ind["id"], move_in_date="2026-06-10"),
            make_case_manager_headers(cm["id"]),
        ))
        return q, ba

    def test_move_in_before_date_rejected(self, api):
        """PRD 3.5: "Move-in requires that `move_in_date` be on or before today
        (a future move-in rejects with `ERR_MOVE_IN_FUTURE`, HTTP 422)".

        Design: Corner/validations/move_in_before_move_in_date_rejected
        """
        q, ba = self._setup_future_pending_assignment(api)
        resp = api_client.move_in_bed_assignment(ba["id"], make_qidp_headers(q["id"]))
        validate_error(resp, ApiErrorId.ERR_MOVE_IN_FUTURE)

    def test_move_in_on_the_date_itself_accepted(self, api):
        """PRD 3.5: "Move-in requires that `move_in_date` be on or before
        today" — the date itself satisfies "on or before".

        Design: Corner/validations/move_in_before_move_in_date_rejected
        """
        q, ba = self._setup_future_pending_assignment(api)
        set_clock("2026-06-10T00:00:00Z")
        moved = get_success_data(api_client.move_in_bed_assignment(
            ba["id"], make_qidp_headers(q["id"]),
        ))
        assert moved["status"] == "ACTIVE"


class TestShiftConfirmOwnershipAndCompletion:
    """Shift confirm ownership + EVV-driven completion (PRD 3.4, 3.8)."""

    def _setup_shift_scenario(self, api):
        ctx = setup_billable_pipeline()
        home = setup_home(ctx["agency"], certified_bed_count=2)
        d2 = setup_staff(ctx["agency"]["id"], "DSP", full_name="Dee Sptwo")
        shift = get_success_data(api_client.create_shift(
            create_shift_payload(home["id"], ctx["d1"]["id"]),
            ADMIN,
        ))
        return ctx, home, d2, shift

    def test_confirm_by_other_dsp_rejected_ownership(self, api):
        """PRD 3.4: "the confirmation enforces ownership by requiring that the
        caller's `X-User-ID` equal the shift's `staff_member_id`, rejecting
        with `ERR_OWNERSHIP_MISMATCH` (HTTP 403) otherwise."

        Design: Corner/state_machines/shift_confirm_ownership_and_completion_side_effect
        """
        ctx, home, d2, shift = self._setup_shift_scenario(api)
        resp = api_client.confirm_shift(shift["id"], make_dsp_headers(d2["id"]))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

    def test_confirm_then_linked_verified_visit_completes_shift(self, api):
        """PRD 3.4: "The terminal `COMPLETED` state is reached automatically:
        when an EVV visit carrying a `shift_id` pointing at a `CONFIRMED` shift
        is verified (or its exception is resolved), the linked shift transitions
        to `COMPLETED`."

        Design: Corner/state_machines/shift_confirm_ownership_and_completion_side_effect
        """
        ctx, home, _d2, shift = self._setup_shift_scenario(api)
        confirmed = get_success_data(api_client.confirm_shift(shift["id"], ctx["d1_headers"]))
        assert confirmed["status"] == "CONFIRMED"
        visit = get_success_data(api_client.create_evv_visit(
            create_evv_visit_payload(
                ctx["individual"]["id"], ctx["auth"]["id"],
                check_in_at="2026-06-02T08:00:00Z", check_out_at="2026-06-02T09:00:00Z",
                shift_id=shift["id"],
            ), ctx["d1_headers"],
        ))
        get_success_data(api_client.verify_evv_visit(visit["id"], ctx["q_headers"]))
        shift_after = get_success_data(api_client.get_shift(shift["id"], ANY))
        assert shift_after["status"] == "COMPLETED"


class TestStaffingCheckExcludesCancelledShifts:
    """Cancelled shifts excluded from scheduled count (PRD 3.4)."""

    def _setup_two_shifts_one_cancelled(self, api):
        base = setup_agency_with_clinical_staff()
        agency, cm, q, d1 = base["agency"], base["cm"], base["q"], base["d1"]
        d2 = setup_staff(agency["id"], "DSP", full_name="Dee Sptwo")
        home = setup_home(agency, certified_bed_count=2)
        r1 = setup_enrolled_individual(agency, cm, q, legal_name="Res One")
        r2 = setup_enrolled_individual(agency, cm, q, legal_name="Res Two")
        set_clock("2026-06-01T00:00:00Z")
        admit_resident(home, r1, cm, q, bed_label="R1")
        admit_resident(home, r2, cm, q, bed_label="R2")
        get_success_data(api_client.create_shift(
            create_shift_payload(home["id"], d1["id"]), ADMIN,
        ))
        sh2 = get_success_data(api_client.create_shift(
            create_shift_payload(home["id"], d2["id"]), ADMIN,
        ))
        get_success_data(api_client.cancel_shift(sh2["id"], ADMIN))
        return home

    def test_cancelled_shift_excluded_from_scheduled_count(self, api):
        """PRD 3.4: "The scheduled DSP count is the number of shift assignments
        at the home on `shift_date` with matching `shift_type` and status in
        `SCHEDULED`, `CONFIRMED`, or `COMPLETED` (cancelled shifts are
        excluded)."

        Design: Corner/calculations/staffing_check_excludes_cancelled_shifts
        """
        home = self._setup_two_shifts_one_cancelled(api)
        data = validate_success(api.get_home_staffing_check(home["id"], ANY, "2026-06-02", "DAY"))
        assert data["weighted_census"] == 2
        assert data["required_dsps"] == 1  # ceil(2/4)
        assert data["scheduled_dsps"] == 1
        assert data["compliant_scheduled"] is True

    def test_uncancelled_pair_would_count_two(self, api):
        """PRD 3.4: "status in `SCHEDULED`, `CONFIRMED`, or `COMPLETED`" — the
        count reflects only live shifts; a second live shift would raise the
        count to 2, demonstrating the filter's effect.

        Design: Corner/calculations/staffing_check_excludes_cancelled_shifts
        """
        base = setup_agency_with_clinical_staff()
        agency, cm, q, d1 = base["agency"], base["cm"], base["q"], base["d1"]
        d2 = setup_staff(agency["id"], "DSP", full_name="Dee Sptwo")
        home = setup_home(agency, certified_bed_count=2)
        r1 = setup_enrolled_individual(agency, cm, q, legal_name="Res One")
        r2 = setup_enrolled_individual(agency, cm, q, legal_name="Res Two")
        set_clock("2026-06-01T00:00:00Z")
        admit_resident(home, r1, cm, q, bed_label="R1")
        admit_resident(home, r2, cm, q, bed_label="R2")
        get_success_data(api_client.create_shift(create_shift_payload(home["id"], d1["id"]), ADMIN))
        get_success_data(api_client.create_shift(create_shift_payload(home["id"], d2["id"]), ADMIN))
        data = validate_success(api.get_home_staffing_check(home["id"], ANY, "2026-06-02", "DAY"))
        assert data["scheduled_dsps"] == 2
