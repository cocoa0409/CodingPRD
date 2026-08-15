"""Community projects (review loop, cap, segregation, close cascade) and
demonstration-garden rotation weeks."""
import pytest

from test_helpers import (ApiErrorId, approve_project, close_cycle,
                          create_active_volunteer, create_and_open_cycle,
                          create_approved_project, create_project,
                          create_project_payload,
                          create_rotation_assignment,
                          create_rotation_assignment_payload, get_record_for,
                          get_success_data, log_and_approve_service_entry,
                          log_service_entry, make_coordinator_headers,
                          make_volunteer_headers, move_cycle_to_recertification,
                          set_clock, setup_cycle_with_active_volunteer,
                          setup_cycle_with_two_active_volunteers,
                          submit_project, validate_error, validate_paginated,
                          validate_success)
from test_helpers import TEST_USERS

COORD = TEST_USERS["coordinator_headers"]
COORD_A = TEST_USERS["coordinator_a_headers"]
COORD_B = TEST_USERS["coordinator_b_headers"]


class TestProjectReviewLoop:
    def test_project_revision_resubmission_loop_states_and_cap(self, api):
        """PRD §3.6: "Submission moves `DRAFT → UNDER_REVIEW` on first
        submission and `REVISION_REQUESTED → UNDER_REVIEW` on resubmission"
        PRD §3.6: "A request for revision carries `feedback` and moves the
        project to `REVISION_REQUESTED`, opening the resubmission loop back
        through amendment and submission."
        PRD §3.6: "Approval records the approving coordinator's `X-User-ID`
        in `approved_by_user_id` and computes the per-volunteer credit cap:
        `max_creditable_hours_per_volunteer` becomes the lesser of 20.0 and
        the project's `estimated_hours_per_volunteer` multiplied by 1.25 and
        rounded half-up to two decimal places"

        Design: Difficulty/non_linear_state_machine/project_revision_resubmission_loop
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        proj = create_project(cycle["id"], vol["id"],
                              title="Pollinator Garden",
                              description="v1 scope",
                              estimated_hours_per_volunteer=10.0)
        submit_project(proj["id"], vol["id"])
        get_success_data(api.request_revision(
            proj["id"], {"feedback": "tighten scope"}, COORD))
        cur = get_success_data(api.get_project(proj["id"], COORD))
        assert cur["status"] == "REVISION_REQUESTED"
        get_success_data(api.amend_project(
            proj["id"],
            {"expected_project_version": cur["version"],
             "title": "Pollinator Garden (revised)",
             "description": "v2 scope"},
            make_volunteer_headers(vol["id"])))
        submit_project(proj["id"], vol["id"])
        approved = approve_project(proj["id"], COORD_A)
        assert approved["status"] == "APPROVED"
        assert approved["title"] == "Pollinator Garden (revised)"
        assert approved["max_creditable_hours_per_volunteer"] == \
            pytest.approx(12.5, abs=0.001)
        assert approved["approved_by_user_id"] == "coord-a"

    def test_project_revision_resubmission_loop_version_counts(self, api):
        """PRD §2.4: "`version` (integer): a system-managed integer that
        starts at 1 on creation and increments by one on every mutation,
        including mutations driven by system cascades and recomputed derived
        fields."

        Design: Difficulty/non_linear_state_machine/project_revision_resubmission_loop
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        proj = create_project(cycle["id"], vol["id"],
                              title="Pollinator Garden",
                              description="v1 scope",
                              estimated_hours_per_volunteer=10.0)
        submit_project(proj["id"], vol["id"])                    # v2
        get_success_data(api.request_revision(
            proj["id"], {"feedback": "tighten scope"}, COORD))   # v3
        cur = get_success_data(api.get_project(proj["id"], COORD))
        get_success_data(api.amend_project(
            proj["id"],
            {"expected_project_version": cur["version"],
             "title": "Pollinator Garden (revised)",
             "description": "v2 scope"},
            make_volunteer_headers(vol["id"])))                  # v4
        submit_project(proj["id"], vol["id"])                    # v5
        approved = approve_project(proj["id"], COORD_A)          # v6
        # create 1, submit 2, revision 3, amend 4, resubmit 5, approve 6
        assert approved["version"] == 6

    def test_project_wrong_state_errors(self, api):
        """PRD §3.6: "Review is a coordinator decision on an `UNDER_REVIEW`
        project; any other state fails with `ERR_PROJECT_NOT_UNDER_REVIEW`."
        PRD §3.6: "Closing an `APPROVED` project (otherwise
        `ERR_PROJECT_NOT_APPROVED`)"
        PRD §3.6: "While the project is `DRAFT` or `REVISION_REQUESTED` — in
        any other state the attempt fails with `ERR_PROJECT_NOT_EDITABLE`"

        Design: Corner/state_machines/project_wrong_state_errors
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        proj = create_project(cycle["id"], vol["id"], title="Seed Library",
                              description="v1",
                              estimated_hours_per_volunteer=8.0)
        resp = api.approve_project(proj["id"], COORD_A)
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_UNDER_REVIEW)

        submit_project(proj["id"], vol["id"])
        resp = api.close_project(proj["id"], COORD_A)
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_APPROVED)

        approve_project(proj["id"], COORD_A)
        cur = get_success_data(api.get_project(proj["id"], COORD))
        resp = api.amend_project(
            proj["id"],
            {"expected_project_version": cur["version"],
             "title": "too late"},
            make_volunteer_headers(vol["id"]))
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_EDITABLE)
        after = get_success_data(api.get_project(proj["id"], COORD))
        assert after["status"] == "APPROVED"
        assert after["title"] == "Seed Library"


class TestProjectClose:
    def test_project_close_segregation_of_duties(self, api):
        """PRD §3.6: "Closing an `APPROVED` project (otherwise
        `ERR_PROJECT_NOT_APPROVED`) is coordinator work under a
        segregation-of-duties rule: the caller's `X-User-ID` must differ from
        the project's `approved_by_user_id`, and a close attempted by the
        approving coordinator fails with `ERR_SEGREGATION_OF_DUTIES` (HTTP
        403)."

        Design: Corner/rbac/project_close_segregation_of_duties
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        proj = create_approved_project(cycle["id"], vol["id"],
                                       approver_headers=COORD_A,
                                       title="Seed Library",
                                       description="catalog seeds",
                                       estimated_hours_per_volunteer=8.0)
        resp = api.close_project(proj["id"], COORD_A)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        resp = api.close_project(proj["id"], COORD_B)
        closed = validate_success(resp)
        assert closed["status"] == "CLOSED"
        after = get_success_data(api.get_project(proj["id"], COORD))
        assert after["approved_by_user_id"] == "coord-a"

    def test_project_close_voids_pending_entries(self, api):
        """PRD §3.6: "Closing cascades through the credit ledger in two
        links: first, every `PENDING` `CreditEntry` whose `source_type` is
        `PROJECT` and whose `source_id` is this project is voided; second,
        the `RecertificationRecord` totals of every volunteer whose entry was
        voided are recomputed."

        Design: Difficulty/transitive_cascade/project_close_voids_pending_entries
        """
        cycle, vol, rec = setup_cycle_with_active_volunteer()
        proj = create_approved_project(cycle["id"], vol["id"],
                                       approver_headers=COORD_A,
                                       title="Tool Library",
                                       description="Shed inventory",
                                       estimated_hours_per_volunteer=10.0)
        e1 = log_and_approve_service_entry(
            vol["id"], cycle["id"], 6.0, "2026-08-06",
            activity_type="PROJECT", source_type="PROJECT",
            source_id=proj["id"])
        e2 = log_service_entry(vol["id"], cycle["id"], 4.0, "2026-08-07",
                               activity_type="PROJECT", source_type="PROJECT",
                               source_id=proj["id"])
        pre = validate_success(api.evaluate_record(rec["id"], COORD))
        assert pre["provisional_service_hours"] == pytest.approx(10.0,
                                                                 abs=0.01)

        close_resp = api.close_project(proj["id"], COORD_B)
        closed = validate_success(close_resp)
        assert closed["status"] == "CLOSED"

        e1_after = get_success_data(api.get_credit_entry(e1["id"], COORD))
        e2_after = get_success_data(api.get_credit_entry(e2["id"], COORD))
        assert e2_after["status"] == "VOIDED"
        assert e1_after["status"] == "APPROVED"

        rec_after = get_success_data(
            api.get_recertification_record(rec["id"], COORD))
        assert rec_after["provisional_service_hours"] == pytest.approx(
            6.0, abs=0.01)
        assert rec_after["official_service_hours"] == pytest.approx(
            6.0, abs=0.01)

    def test_project_close_cascade_requires_different_coordinator(self, api):
        """PRD §3.6: "Closing cascades through the credit ledger in two
        links: first, every `PENDING` `CreditEntry` whose `source_type` is
        `PROJECT` and whose `source_id` is this project is voided"
        PRD §3.6: "the caller's `X-User-ID` must differ from the project's
        `approved_by_user_id`, and a close attempted by the approving
        coordinator fails with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Difficulty/transitive_cascade/project_close_voids_pending_entries
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        proj = create_approved_project(cycle["id"], vol["id"],
                                       approver_headers=COORD_A,
                                       estimated_hours_per_volunteer=10.0)
        e2 = log_service_entry(vol["id"], cycle["id"], 4.0, "2026-08-07",
                               activity_type="PROJECT", source_type="PROJECT",
                               source_id=proj["id"])
        # The approving coordinator cannot close; the entry stays PENDING.
        resp = api.close_project(proj["id"], COORD_A)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        e2_mid = get_success_data(api.get_credit_entry(e2["id"], COORD))
        assert e2_mid["status"] == "PENDING"

    def test_project_source_entry_not_creditable_returns_409(self, api):
        """PRD §3.3: "A `PROJECT`-sourced entry must reference a project in
        `APPROVED` or `CLOSED` status, otherwise
        `ERR_PROJECT_NOT_CREDITABLE`."

        Design: Corner/errors/project_source_entry_not_creditable_returns_409
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        proj = create_project(cycle["id"], vol["id"], title="Seed Library",
                              description="catalog seeds",
                              estimated_hours_per_volunteer=8.0)
        submit_project(proj["id"], vol["id"])  # UNDER_REVIEW, not APPROVED
        resp = api.create_credit_entry(
            vol["id"],
            {"cycle_id": cycle["id"], "entry_kind": "SERVICE",
             "activity_type": "PROJECT", "activity_date": "2026-08-05",
             "hours": 3.0, "source_type": "PROJECT",
             "source_id": proj["id"]},
            make_volunteer_headers(vol["id"]))
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_CREDITABLE)


class TestRotation:
    def test_garden_bed_closed_week_overlap(self, api):
        """PRD §3.7: "Two assignments on the same `bed_code` with status
        `ASSIGNED` or `COMPLETED` conflict when their closed week ranges
        intersect — the new week starting on or before the existing week ends
        while the existing week starts on or before the new week ends — and
        the conflict is rejected with `ERR_BED_WEEK_CONFLICT`; adjacent
        weeks, where the next Monday falls exactly one day after the prior
        week's Sunday, are disjoint and allowed."
        PRD §3.7: "The `week_end` is computed as six days after `week_start`
        — the Sunday"
        PRD §3.7: "The assignment's `cycle_id` is derived, not supplied: it
        is the unique `OPEN` cycle whose inclusive `start_date`-to-`end_date`
        window contains `week_start`"

        Design: Difficulty/resource_temporal_overlap/garden_bed_closed_week_overlap
        """
        cycle, vol1, vol2, _r1, _r2 = setup_cycle_with_two_active_volunteers()
        r1 = create_rotation_assignment("BED-1", vol1["id"], "2026-09-07")
        assert r1["week_end"] == "2026-09-13"
        assert r1["cycle_id"] == cycle["id"]
        # Identical week on the same bed: closed-range conflict.
        resp = api.create_rotation_assignment(
            create_rotation_assignment_payload("BED-1", vol2["id"],
                                               "2026-09-07"), COORD)
        validate_error(resp, ApiErrorId.ERR_BED_WEEK_CONFLICT)
        # Adjacent week (next Monday == prior Sunday + 1 day): disjoint.
        r2 = create_rotation_assignment("BED-1", vol2["id"], "2026-09-14")
        assert r2["status"] == "ASSIGNED"

    def test_garden_bed_consecutive_week_limit(self, api):
        """PRD §3.7: "The new assignment is rejected with
        `ERR_CONSECUTIVE_WEEK_LIMIT` when the chain has reached two: a
        volunteer may hold at most two consecutive weeks on the same bed, and
        the third consecutive week fails."

        Design: Difficulty/resource_temporal_overlap/garden_bed_closed_week_overlap
        """
        cycle, vol1, _vol2, _r1, _r2 = setup_cycle_with_two_active_volunteers()
        create_rotation_assignment("BED-2", vol1["id"], "2026-09-07")
        create_rotation_assignment("BED-2", vol1["id"], "2026-09-14")
        resp = api.create_rotation_assignment(
            create_rotation_assignment_payload("BED-2", vol1["id"],
                                               "2026-09-21"), COORD)
        validate_error(resp, ApiErrorId.ERR_CONSECUTIVE_WEEK_LIMIT)

    def test_rotation_week_start_not_monday_returns_422(self, api):
        """PRD §3.7: "a `week_start` date that must be a Monday (otherwise
        `ERR_INVALID_FIELD_VALUE`)"

        Design: Corner/errors/rotation_week_start_not_monday_returns_422
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        resp = api.create_rotation_assignment(
            create_rotation_assignment_payload("BED-1", vol["id"],
                                               "2026-09-08"), COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_FIELD_VALUE)

    def test_rotation_complete_before_week_ends_returns_409(self, api):
        """PRD §3.7: "both outcomes require the assignment to be `ASSIGNED`
        (otherwise `ERR_ASSIGNMENT_NOT_ASSIGNED`) and the logical clock to
        have reached the instant exactly seven days after `week_start` at
        00:00:00 UTC (otherwise `ERR_WEEK_NOT_ENDED`)."

        Design: Corner/errors/rotation_complete_before_week_ends_returns_409
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        ra = create_rotation_assignment("BED-1", vol["id"], "2026-09-07")
        set_clock("2026-09-13T12:00:00Z")  # Sunday inside the week
        resp = api.complete_rotation_assignment(ra["id"],
                                                {"actual_hours": 3.0}, COORD)
        validate_error(resp, ApiErrorId.ERR_WEEK_NOT_ENDED)
        after = get_success_data(api.get_rotation_assignment(ra["id"], COORD))
        assert after["status"] == "ASSIGNED"

    def test_rotation_week_outside_open_cycle_returns_409(self, api):
        """PRD §3.7: "The assignment's `cycle_id` is derived, not supplied:
        it is the unique `OPEN` cycle whose inclusive
        `start_date`-to-`end_date` window contains `week_start`, and when no
        such cycle exists the creation fails with `ERR_NO_OPEN_CYCLE`."

        Design: Corner/errors/rotation_week_outside_open_cycle_returns_409
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        # 2027-01-04 is a Monday but the only OPEN cycle ends 2026-12-31.
        resp = api.create_rotation_assignment(
            create_rotation_assignment_payload("BED-1", vol["id"],
                                               "2027-01-04"), COORD)
        validate_error(resp, ApiErrorId.ERR_NO_OPEN_CYCLE)

    def test_rotation_complete_mints_pending_garden_entry(self, api):
        """PRD §3.7: "Completion additionally takes the `actual_hours`
        worked, which must lie between 0.5 and 8.0 inclusive in steps of 0.25
        (otherwise `ERR_INVALID_FIELD_VALUE`), moves the assignment to
        `COMPLETED`, and mints a `PENDING` `CreditEntry`: the volunteer and
        cycle taken from the assignment, `entry_kind` `SERVICE`,
        `activity_type` `GARDEN`, `activity_date` set to `week_end`, `hours`
        equal to the reported `actual_hours`, `source_type` `ROTATION`, and
        `source_id` the assignment's id."

        Design: Corner/state_machines/rotation_complete_mints_pending_garden_entry
        """
        cycle, vol, _rec = setup_cycle_with_active_volunteer()
        ra = create_rotation_assignment("BED-1", vol["id"], "2026-09-07")
        set_clock("2026-09-14T00:00:00Z")
        resp = api.complete_rotation_assignment(ra["id"],
                                                {"actual_hours": 3.5}, COORD)
        done = validate_success(resp)
        assert done["status"] == "COMPLETED"
        entries, _meta = validate_paginated(api.list_credit_entries(
            COORD, params={"volunteer_id": vol["id"],
                           "source_type": "ROTATION"}))
        assert len(entries) == 1
        minted = entries[0]
        assert minted["hours"] == pytest.approx(3.5, abs=0.001)
        assert minted["activity_type"] == "GARDEN"
        assert minted["status"] == "PENDING"
        assert minted["cycle_id"] == cycle["id"]
        assert minted["activity_date"] == "2026-09-13"

    def test_rotation_state_errors(self, api):
        """PRD §3.7: "Before the week ends, a coordinator may swap the
        assignment to another volunteer: the assignment must be `ASSIGNED`,
        the logical clock must be strictly earlier than the
        seven-days-after-`week_start` instant (otherwise
        `ERR_SWAP_WINDOW_CLOSED`)"
        PRD §3.7: "both outcomes require the assignment to be `ASSIGNED`
        (otherwise `ERR_ASSIGNMENT_NOT_ASSIGNED`)"
        PRD §3.7: "A successful swap moves the original to `SWAPPED` and
        creates the replacement in `ASSIGNED` with the same `bed_code`,
        `week_start`, `week_end`, and derived `cycle_id`, its `volunteer_id`
        set to `new_volunteer_id`; the original's `swapped_to_id` points at
        the replacement."

        Design: Corner/state_machines/rotation_state_errors
        """
        cycle, vol1, vol2, _r1, _r2 = setup_cycle_with_two_active_volunteers()
        ra_a = create_rotation_assignment("BED-1", vol1["id"], "2026-09-07")
        ra_b = create_rotation_assignment("BED-2", vol1["id"], "2026-09-07")
        set_clock("2026-09-02T00:00:00Z")  # mid-week: swap allowed

        resp = api.swap_rotation_assignment(
            ra_a["id"], {"new_volunteer_id": vol2["id"]}, COORD)
        replacement = validate_success(resp)
        assert replacement["status"] == "ASSIGNED"
        assert replacement["volunteer_id"] == vol2["id"]
        assert replacement["week_start"] == "2026-09-07"
        original = get_success_data(
            api.get_rotation_assignment(ra_a["id"], COORD))
        assert original["status"] == "SWAPPED"
        assert original["swapped_to_id"] == replacement["id"]

        set_clock("2026-09-15T00:00:00Z")  # past week end
        resp = api.swap_rotation_assignment(
            ra_b["id"], {"new_volunteer_id": vol2["id"]}, COORD)
        validate_error(resp, ApiErrorId.ERR_SWAP_WINDOW_CLOSED)
        resp = api.complete_rotation_assignment(ra_a["id"],
                                                {"actual_hours": 3.0}, COORD)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_NOT_ASSIGNED)
