"""Travel-lift scheduling gates, buffers, and stand-capacity management."""
from test_helpers import (
    ApiErrorId,
    approve_work_order,
    assign_stands,
    book_lift_slot,
    complete_slot_at,
    complete_work_order,
    create_refit_job,
    create_row,
    create_stand_assignment_payload,
    create_submitted_job,
    create_vessel,
    create_vessel_with_insurance,
    create_work_order,
    get_job,
    get_row,
    is_valid_uuid,
    list_lift_slots,
    post_ledger_entry,
    run_daily_close,
    set_clock,
    setup_job_on_hard,
    setup_job_ready_for_splash,
    setup_moratorium_scenario,
    setup_two_intake_jobs,
    start_work_order,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, api_client
from test_helpers.factories import create_lift_slot_payload

SW = TEST_USERS["service_writer_headers"]
YM = TEST_USERS["yard_manager_headers"]


class TestLiftSlotBufferAdjacency:

    def test_slot_starting_inside_buffer_rejected(self):
        """PRD section 3.3: "Every slot that is `BOOKED` or `COMPLETED` —
        across all jobs — competes for the lift, with a 30-minute turnaround
        buffer on each side. A new slot's window conflicts with an existing
        one when the new start falls before the existing end plus 30 minutes,
        and the existing start falls before the new end plus 30 minutes." and
        "A conflicting booking is rejected with `ERR_LIFT_SLOT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/lift_slot_buffer_adjacency_boundary
        """
        ctx_a, ctx_b = setup_two_intake_jobs(prefix="MV First")
        book_lift_slot(ctx_a["job"]["id"], kind="HAUL_OUT",
                       scheduled_start="2026-08-02T08:00:00Z",
                       scheduled_end="2026-08-02T09:00:00Z",
                       vessel_displacement_tons=10)

        resp = api_client.create_lift_slot(
            create_lift_slot_payload(
                ctx_b["job"]["id"], kind="HAUL_OUT",
                scheduled_start="2026-08-02T09:29:00Z",
                scheduled_end="2026-08-02T10:29:00Z",
                vessel_displacement_tons=10),
            YM)
        validate_error(resp, ApiErrorId.ERR_LIFT_SLOT_CONFLICT)

    def test_slot_starting_exactly_at_buffer_end_allowed(self):
        """PRD section 3.3: "Adjacency is allowed: when the existing window's
        end plus exactly 30 minutes equals the new start, there is no
        conflict, because the comparison is a strict inequality."

        Design: Difficulty/resource_temporal_overlap/lift_slot_buffer_adjacency_boundary
        """
        ctx_a, ctx_b = setup_two_intake_jobs(prefix="MV Second")
        book_lift_slot(ctx_a["job"]["id"], kind="HAUL_OUT",
                       scheduled_start="2026-08-02T08:00:00Z",
                       scheduled_end="2026-08-02T09:00:00Z",
                       vessel_displacement_tons=10)

        resp = api_client.create_lift_slot(
            create_lift_slot_payload(
                ctx_b["job"]["id"], kind="HAUL_OUT",
                scheduled_start="2026-08-02T09:30:00Z",
                scheduled_end="2026-08-02T10:30:00Z",
                vessel_displacement_tons=10),
            YM)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "BOOKED"
        assert is_valid_uuid(data["id"])


class TestStandClosedIntervals:

    def test_touching_closed_intervals_intersect(self):
        """PRD section 3.4: "Two assignments' windows intersect whenever each
        starts on or before the other's end — touching dates do intersect,
        because the intervals are closed." and "The assignment is rejected
        with `ERR_STANDS_EXHAUSTED` only when the projected occupancy plus
        the requested `stands_used` strictly exceeds `total_stands`; an
        exactly-full row — projected plus requested equal to `total_stands` —
        is allowed."

        Design: Difficulty/resource_temporal_overlap/stand_closed_interval_touching_conflict
        """
        ctx_a, ctx_b = setup_two_intake_jobs(prefix="MV Stand")
        row = create_row(code="T2", total_stands=10)
        assign_stands(row["id"], ctx_a["job"]["id"], stands_used=6,
                      start_date="2026-08-02", end_date="2026-08-10")

        row_now = get_row(row["id"])
        resp = api_client.create_stand_assignment(
            create_stand_assignment_payload(
                row["id"], ctx_b["job"]["id"], row_now["version"],
                stands_used=6, start_date="2026-08-10",
                end_date="2026-08-20"),
            YM)
        # Touching on 2026-08-10: closed intervals intersect, 6 + 6 > 10.
        validate_error(resp, ApiErrorId.ERR_STANDS_EXHAUSTED)

    def test_disjoint_windows_fit_and_rejection_preserves_row_version(self):
        """PRD section 3.4: "A new assignment is `ACTIVE`, increments the
        row's `stands_in_use` by `stands_used`, and increments the row's
        `version` by one."
        PRD section 2.4: "Most resources additionally carry `created_at` and
        `updated_at` (both ISO 8601 UTC timestamps with three fractional
        digits) and a `version` integer that increments by one on every
        mutation of the resource."

        Design: Difficulty/resource_temporal_overlap/stand_closed_interval_touching_conflict
        """
        ctx_a, ctx_b = setup_two_intake_jobs(prefix="MV Disjoint")
        row = create_row(code="T3", total_stands=10)
        assign_stands(row["id"], ctx_a["job"]["id"], stands_used=6,
                      start_date="2026-08-02", end_date="2026-08-10")
        row_after_a = get_row(row["id"])

        rejected = api_client.create_stand_assignment(
            create_stand_assignment_payload(
                row["id"], ctx_b["job"]["id"], row_after_a["version"],
                stands_used=6, start_date="2026-08-10",
                end_date="2026-08-20"),
            YM)
        validate_error(rejected, ApiErrorId.ERR_STANDS_EXHAUSTED)
        assert get_row(row["id"])["version"] == row_after_a["version"], \
            "a rejected assignment must not mutate the row"

        accepted = api_client.create_stand_assignment(
            create_stand_assignment_payload(
                row["id"], ctx_b["job"]["id"], row_after_a["version"],
                stands_used=6, start_date="2026-08-11",
                end_date="2026-08-20"),
            YM)
        data = validate_success(accepted, expected_status=201)
        assert data["status"] == "ACTIVE", \
            "a fully disjoint window fits the remaining capacity"


class TestStandCapacityBoundary:

    def _three_intake_jobs(self):
        set_clock("2026-08-01T09:00:00Z")
        ctxs = []
        for idx in range(1, 4):
            vessel, _c = create_vessel_with_insurance(
                name=f"MV Cap {idx}", owner_user_id=f"owner-{idx}",
                loa_ft=30, beam_ft=10, hull_type="POWER",
                displacement_tons=10, policy_no=f"POL-CAP-{idx}")
            job = create_submitted_job(vessel["id"])
            ctxs.append({"vessel": vessel, "job": job})
        return ctxs

    def test_exact_full_row_allowed(self):
        """PRD section 3.4: "The assignment is rejected with
        `ERR_STANDS_EXHAUSTED` only when the projected occupancy plus the
        requested `stands_used` strictly exceeds `total_stands`; an
        exactly-full row — projected plus requested equal to `total_stands` —
        is allowed."

        Design: Difficulty/boundary_precision_check/stand_exact_capacity_fit_allowed
        """
        ctxs = self._three_intake_jobs()
        row = create_row(code="F", total_stands=10)
        assign_stands(row["id"], ctxs[0]["job"]["id"], stands_used=6,
                      start_date="2026-08-02", end_date="2026-09-30")
        second = assign_stands(row["id"], ctxs[1]["job"]["id"], stands_used=4,
                               start_date="2026-08-02", end_date="2026-09-30")
        assert second["status"] == "ACTIVE", \
            "projected 6 + requested 4 == total_stands 10 must be allowed"
        assert get_row(row["id"])["stands_in_use"] == 10

    def test_one_stand_over_rejected(self):
        """PRD section 3.4: "The assignment is rejected with
        `ERR_STANDS_EXHAUSTED` only when the projected occupancy plus the
        requested `stands_used` strictly exceeds `total_stands`; an
        exactly-full row — projected plus requested equal to `total_stands` —
        is allowed."

        Design: Difficulty/boundary_precision_check/stand_exact_capacity_fit_allowed
        """
        ctxs = self._three_intake_jobs()
        row = create_row(code="F", total_stands=10)
        assign_stands(row["id"], ctxs[0]["job"]["id"], stands_used=6,
                      start_date="2026-08-02", end_date="2026-09-30")
        assign_stands(row["id"], ctxs[1]["job"]["id"], stands_used=4,
                      start_date="2026-08-02", end_date="2026-09-30")

        row_now = get_row(row["id"])
        resp = api_client.create_stand_assignment(
            create_stand_assignment_payload(
                row["id"], ctxs[2]["job"]["id"], row_now["version"],
                stands_used=1, start_date="2026-08-05",
                end_date="2026-08-20"),
            YM)
        validate_error(resp, ApiErrorId.ERR_STANDS_EXHAUSTED)


class TestStandAssignReleaseConservation:

    def test_assignment_increments_stands_in_use(self):
        """PRD section 3.4: "A row's `stands_in_use` is the running sum of
        `stands_used` over the row's `ACTIVE` assignments and starts at
        zero." and "A new assignment is `ACTIVE`, increments the row's
        `stands_in_use` by `stands_used`, and increments the row's `version`
        by one."

        Design: Difficulty/compensating_invariant/stand_assign_release_conserves_row_capacity
        """
        set_clock("2026-08-01T09:00:00Z")
        row = create_row(code="INV", total_stands=10)
        assert row["stands_in_use"] == 0
        vessel, _c = create_vessel_with_insurance(
            name="MV Inv", owner_user_id="owner-1", loa_ft=30, beam_ft=10,
            hull_type="POWER", displacement_tons=10, policy_no="POL-INV")
        job = create_submitted_job(vessel["id"])

        assign_stands(row["id"], job["id"], stands_used=4,
                      start_date="2026-08-02", end_date="2026-09-30")
        after = get_row(row["id"])
        assert after["stands_in_use"] == 4
        assert after["version"] == row["version"] + 1

    def test_release_returns_stands_in_use_to_pre_assignment_value(self):
        """PRD section 3.4: "Releasing an assignment — by a `YardManager`, or
        automatically through the splash-completion and job-cancel cascades —
        moves it from `ACTIVE` to `RELEASED`, decrements the row's
        `stands_in_use` by the assignment's `stands_used`, and increments the
        row's `version` by one. This is the compensating invariant: after
        release, `stands_in_use` returns to its pre-assignment value."

        Design: Difficulty/compensating_invariant/stand_assign_release_conserves_row_capacity
        """
        set_clock("2026-08-01T09:00:00Z")
        row = create_row(code="INV", total_stands=10)
        vessel, _c = create_vessel_with_insurance(
            name="MV Inv", owner_user_id="owner-1", loa_ft=30, beam_ft=10,
            hull_type="POWER", displacement_tons=10, policy_no="POL-INV")
        job = create_submitted_job(vessel["id"])
        assignment = assign_stands(row["id"], job["id"], stands_used=4,
                                   start_date="2026-08-02",
                                   end_date="2026-09-30")

        released = validate_success(
            api_client.release_stand_assignment(assignment["id"], YM))
        assert released["status"] == "RELEASED"
        after = get_row(row["id"])
        assert after["stands_in_use"] == 0, \
            "assign(4) + release must return stands_in_use to 0"
        assert after["version"] == row["version"] + 2


class TestStandAssignOcc:

    def test_stand_assign_occ_stale_row_version(self):
        """PRD section 2.5: "Creating a stand assignment against a yard row
        requires the request to carry `expected_yard_row_version` holding the
        row's `version` as the client last observed it. The capacity decision
        on `stands_in_use` must be based on a current view of the row; if the
        row's current `version` no longer matches — another assignment or
        release has landed since the read — the create is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/stand_assign_occ_stale_row_version
        """
        ctx_a, ctx_b = setup_two_intake_jobs(prefix="MV Occ")
        row = create_row(code="OC", total_stands=10)
        stale_version = row["version"]

        first = api_client.create_stand_assignment(
            create_stand_assignment_payload(
                row["id"], ctx_a["job"]["id"], stale_version, stands_used=3),
            YM)
        validate_success(first, expected_status=201)
        assert get_row(row["id"])["stands_in_use"] == 3

        second = api_client.create_stand_assignment(
            create_stand_assignment_payload(
                row["id"], ctx_b["job"]["id"], stale_version, stands_used=3),
            YM)
        validate_error(second, ApiErrorId.ERR_STALE_VERSION)


class TestMoratoriumGate:

    def test_moratorium_beats_slot_conflict(self):
        """PRD section 3.3: "Three safety gates guard every booking, checked
        in this order after the generic gates of §2.9. First, the
        environmental moratorium: no `HAUL_OUT` slot may have a
        `scheduled_start` whose month-and-day falls within April 1 through
        May 31, inclusive on both ends; a booking inside that window is
        rejected with `ERR_ENV_MORATORIUM`." and "Beyond the safety gates,
        the single lift imposes a temporal-conflict rule."

        Design: Difficulty/priority_pair_validation_conflict/moratorium_safety_beats_slot_conflict
        """
        ctx_a, ctx_b = setup_moratorium_scenario()
        assert ctx_a["splash_slot"]["status"] == "BOOKED"

        # 08:30 start is inside the moratorium AND inside the 30-minute
        # buffer of the BOOKED splash slot ending 09:00.
        resp = api_client.create_lift_slot(
            create_lift_slot_payload(
                ctx_b["job"]["id"], kind="HAUL_OUT",
                scheduled_start="2026-04-10T08:30:00Z",
                scheduled_end="2026-04-10T09:30:00Z",
                vessel_displacement_tons=14),
            YM)
        validate_error(resp, ApiErrorId.ERR_ENV_MORATORIUM)

    def test_moratorium_rejects_haul_booking_in_window(self):
        """PRD section 3.3: "First, the environmental moratorium: no
        `HAUL_OUT` slot may have a `scheduled_start` whose month-and-day
        falls within April 1 through May 31, inclusive on both ends; a
        booking inside that window is rejected with `ERR_ENV_MORATORIUM`."

        Design: Difficulty/priority_pair_validation_conflict/moratorium_safety_beats_slot_conflict
        """
        _ctx_a, ctx_b = setup_moratorium_scenario()

        # 2026-04-12 is inside the moratorium but conflicts with nothing.
        resp = api_client.create_lift_slot(
            create_lift_slot_payload(
                ctx_b["job"]["id"], kind="HAUL_OUT",
                scheduled_start="2026-04-12T08:00:00Z",
                scheduled_end="2026-04-12T09:00:00Z",
                vessel_displacement_tons=14),
            YM)
        validate_error(resp, ApiErrorId.ERR_ENV_MORATORIUM)


class TestLiftBookingGates:

    def test_lift_capacity_boundary_60_tons(self):
        """PRD section 3.3: "Second, the lift rating: the declared
        `vessel_displacement_tons` must be at most 60 tons, else the booking
        is rejected with `ERR_LIFT_CAPACITY_EXCEEDED`."

        Design: Corner/validations/lift_capacity_boundary_60_tons
        """
        set_clock("2026-08-01T09:00:00Z")
        vessel_a, _ca = create_vessel_with_insurance(
            name="MV Heavy", owner_user_id="owner-1", loa_ft=50, beam_ft=15,
            hull_type="POWER", displacement_tons=60, policy_no="POL-H1")
        job_a = create_submitted_job(vessel_a["id"])
        vessel_b, _cb = create_vessel_with_insurance(
            name="MV TooHeavy", owner_user_id="owner-2", loa_ft=52,
            beam_ft=16, hull_type="POWER", displacement_tons=60.5,
            policy_no="POL-H2")
        job_b = create_submitted_job(vessel_b["id"])

        ok = api_client.create_lift_slot(
            create_lift_slot_payload(
                job_a["id"], kind="HAUL_OUT",
                scheduled_start="2026-08-02T08:00:00Z",
                scheduled_end="2026-08-02T09:00:00Z",
                vessel_displacement_tons=60),
            YM)
        data = validate_success(ok, expected_status=201)
        assert data["status"] == "BOOKED", "exactly 60 tons must book"

        over = api_client.create_lift_slot(
            create_lift_slot_payload(
                job_b["id"], kind="HAUL_OUT",
                scheduled_start="2026-08-02T10:00:00Z",
                scheduled_end="2026-08-02T11:00:00Z",
                vessel_displacement_tons=60.5),
            YM)
        validate_error(over, ApiErrorId.ERR_LIFT_CAPACITY_EXCEEDED)

    def test_slot_end_not_after_start_rejected(self):
        """PRD section 3.3: "The end of the window must be strictly after
        the start."
        PRD section 2.9: "Request shape comes fifth — missing required
        fields, invalid types, invalid enum membership, `scheduled_end` not
        strictly after `scheduled_start`, `end_date` before `start_date`,
        non-positive amounts, a `CHARGE` kind submitted through the ledger
        API, or subcontractor labor without a `subcontractor_name` all yield
        `ERR_VALIDATION`."

        Design: Corner/validations/slot_end_not_after_start_rejected
        """
        set_clock("2026-08-01T09:00:00Z")
        vessel, _c = create_vessel_with_insurance(
            name="MV Win", owner_user_id="owner-1", loa_ft=30, beam_ft=10,
            hull_type="POWER", displacement_tons=10, policy_no="POL-W2")
        job = create_submitted_job(vessel["id"])

        resp = api_client.create_lift_slot(
            create_lift_slot_payload(
                job["id"], kind="HAUL_OUT",
                scheduled_start="2026-08-02T09:00:00Z",
                scheduled_end="2026-08-02T09:00:00Z",
                vessel_displacement_tons=10),
            YM)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_slot_complete_outside_window_rejected(self):
        """PRD section 3.3: "A `BOOKED` slot is completed by a `YardManager`
        only while the current logical time falls within the slot's window,
        both endpoints inclusive; completion outside the window is rejected
        with `ERR_INVALID_STATE`."
        PRD section 2.9: "Only after all seven generic gates pass do the
        business rules of Section 3 apply, in the order each workflow
        narrative states them."

        Design: Corner/state_machines/slot_complete_outside_window_rejected
        """
        set_clock("2026-08-01T09:00:00Z")
        vessel, _c = create_vessel_with_insurance(
            name="MV Late2", owner_user_id="owner-1", loa_ft=30, beam_ft=10,
            hull_type="POWER", displacement_tons=10, policy_no="POL-L2")
        job = create_submitted_job(vessel["id"])
        slot = book_lift_slot(job["id"], kind="HAUL_OUT",
                              scheduled_start="2026-08-02T08:00:00Z",
                              scheduled_end="2026-08-02T09:00:00Z",
                              vessel_displacement_tons=10)
        set_clock("2026-08-02T10:00:00Z")

        resp = api_client.complete_lift_slot(slot["id"], YM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_no_show_reverts_job_to_intake(self):
        """PRD section 3.11: "Step two sweeps stale slots: every slot still
        `BOOKED` whose `scheduled_end` is in the past becomes `NO_SHOW`, and
        a no-show haul-out returns its job from `HAUL_SCHEDULED` to
        `INTAKE`."

        Design: Corner/state_machines/no_show_reverts_job_to_intake
        """
        set_clock("2026-08-01T09:00:00Z")
        vessel, _c = create_vessel_with_insurance(
            name="MV NoShow", owner_user_id="owner-1", loa_ft=30, beam_ft=10,
            hull_type="SAIL", displacement_tons=10, policy_no="POL-N2")
        job = create_submitted_job(vessel["id"])
        slot = book_lift_slot(job["id"], kind="HAUL_OUT",
                              scheduled_start="2026-08-02T08:00:00Z",
                              scheduled_end="2026-08-02T09:00:00Z",
                              vessel_displacement_tons=10)
        assert get_job(job["id"])["status"] == "HAUL_SCHEDULED"

        set_clock("2026-08-03T08:00:00Z")
        close = run_daily_close()
        assert slot["id"] in close["no_show_slot_ids"]

        slots = list_lift_slots(job["id"])
        assert slots[0]["status"] == "NO_SHOW"
        assert get_job(job["id"])["status"] == "INTAKE", \
            "a no-show haul-out returns the job to INTAKE for rebooking"

    def test_haul_complete_without_stands_rejected(self):
        """PRD section 3.3: "Completing a `HAUL_OUT` slot additionally
        requires the job to hold an `ACTIVE` stand assignment at that moment
        — a vessel cannot be lifted with nowhere to stand — and is otherwise
        rejected with `ERR_STAND_ASSIGNMENT_MISSING`."

        Design: Corner/validations/haul_complete_without_stands_rejected
        """
        set_clock("2026-08-01T09:00:00Z")
        vessel, _c = create_vessel_with_insurance(
            name="MV NoStand", owner_user_id="owner-1", loa_ft=30, beam_ft=10,
            hull_type="POWER", displacement_tons=10, policy_no="POL-N3")
        job = create_submitted_job(vessel["id"])
        slot = book_lift_slot(job["id"], kind="HAUL_OUT",
                              scheduled_start="2026-08-02T08:00:00Z",
                              scheduled_end="2026-08-02T09:00:00Z",
                              vessel_displacement_tons=10)
        set_clock("2026-08-02T08:30:00Z")

        resp = api_client.complete_lift_slot(slot["id"], YM)
        validate_error(resp, ApiErrorId.ERR_STAND_ASSIGNMENT_MISSING)
        assert get_job(job["id"])["status"] == "HAUL_SCHEDULED", \
            "a rejected completion must not advance the job"
        slots = list_lift_slots(job["id"])
        assert slots[0]["status"] == "BOOKED"


class TestSplashCompletion:

    def test_splash_completion_releases_stand_assignment(self):
        """PRD section 3.3: "Completing a `SPLASH` slot moves the job from
        `READY_FOR_SPLASH` to `AWAITING_TRIAL`, sets `splashed_at` to the
        current calendar date, and releases the job's `ACTIVE` stand
        assignment — the row's `stands_in_use` decreases by the assignment's
        `stands_used` and the row's `version` increments by one."

        Design: Corner/state_machines/splash_completion_releases_stand_assignment
        """
        ctx = setup_job_ready_for_splash(vessel_name="MV Splash",
                                         book_splash=True)
        row_before = get_row(ctx["row"]["id"])
        assert row_before["stands_in_use"] == 4

        completed = complete_slot_at(ctx["splash_slot"]["id"],
                                     "2026-08-20T08:30:00Z")
        assert completed["status"] == "COMPLETED"
        assert get_job(ctx["job"]["id"])["status"] == "AWAITING_TRIAL"

        assignment = validate_success(api_client.get_stand_assignment(
            ctx["assignment"]["id"], YM))
        assert assignment["status"] == "RELEASED"
        assert get_row(ctx["row"]["id"])["stands_in_use"] == 0, \
            "the splash releases the job's stands back to the row"
