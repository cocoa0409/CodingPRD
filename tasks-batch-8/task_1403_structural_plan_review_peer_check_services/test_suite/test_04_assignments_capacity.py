"""Assignments: OCC guard, capacity boundary and aggregate overlap, the
assign/release compensating pair, licensing gates, and lifecycle side effects
(PRD §2.9, §3.4)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assign_cycle,
    create_assignment_payload,
    get_assignment,
    get_cycle,
    get_reviewer,
    issue_comments,
    make_engagement,
    make_jurisdiction,
    make_reviewer,
    open_cycle,
    raise_comment,
    set_clock,
    setup_in_review_cycle,
    setup_registered_engagement,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]


class TestCapacityBoundary:
    def _setup_at_capacity(self, api):
        """Reviewer max 3 with three ACTIVE assignments; a fourth OPEN cycle."""
        jur = make_jurisdiction(state_code="GA", sla_mode="CALENDAR")
        rev = make_reviewer(name="R Eleven", state_code="GA",
                            max_concurrent_assignments=3)
        cycles = []
        for i in range(4):
            eng = make_engagement(jur, rev, project_name=f"Cap {i}")
            cyc = open_cycle(eng["id"], documents_ref=f"s3://c{i}")
            cycles.append(cyc)
        for cyc in cycles[:3]:
            assign_cycle(cyc, rev["id"])
        return rev, cycles

    def test_capacity_rejects_exactly_at_max(self, api):
        """PRD §3.4: "Then the capacity gate: the reviewer's
        `active_assignment_count` must be below their
        `max_concurrent_assignments` — the comparison is inclusive at the
        boundary, so a reviewer already at their maximum is rejected with
        `ERR_REVIEWER_CAPACITY_EXCEEDED`, while one slot below maximum is
        admitted."

        Design: Difficulty/boundary_precision_check/capacity_rejects_exactly_at_max
        """
        rev, cycles = self._setup_at_capacity(api)
        assert get_reviewer(rev["id"])["active_assignment_count"] == 3
        resp = api.create_assignment(
            create_assignment_payload(cycles[3]["id"], rev["id"],
                                      cycles[3]["version"]), COORD)
        validate_error(resp, ApiErrorId.ERR_REVIEWER_CAPACITY_EXCEEDED, 409)

    def test_failed_assignment_leaves_no_side_effects(self, api):
        """PRD §3.4: "Then the capacity gate: the reviewer's
        `active_assignment_count` must be below their
        `max_concurrent_assignments` — the comparison is inclusive at the
        boundary, so a reviewer already at their maximum is rejected with
        `ERR_REVIEWER_CAPACITY_EXCEEDED`, while one slot below maximum is
        admitted."

        Design: Difficulty/boundary_precision_check/capacity_rejects_exactly_at_max
        """
        rev, cycles = self._setup_at_capacity(api)
        api.create_assignment(
            create_assignment_payload(cycles[3]["id"], rev["id"],
                                      cycles[3]["version"]), COORD)
        assert get_reviewer(rev["id"])["active_assignment_count"] == 3
        assert get_cycle(cycles[3]["id"])["status"] == "OPEN"


class TestCapacityOverlapWithRelease:
    def _setup(self, api):
        jur = make_jurisdiction(state_code="SC", sla_mode="CALENDAR")
        rev = make_reviewer(name="R Sixteen", state_code="SC",
                            max_concurrent_assignments=2)
        cycles = []
        asg1 = None
        for i in range(3):
            eng = make_engagement(jur, rev, project_name=f"Overlap {i}")
            cycles.append(open_cycle(eng["id"], documents_ref=f"s3://o{i}"))
        asg1 = assign_cycle(cycles[0], rev["id"])
        assign_cycle(cycles[1], rev["id"])
        return rev, cycles, asg1

    def test_overlapping_windows_allowed_up_to_capacity_then_rejected(self, api):
        """PRD §3.4: "Then the capacity gate: the reviewer's
        `active_assignment_count` must be below their
        `max_concurrent_assignments` — the comparison is inclusive at the
        boundary, so a reviewer already at their maximum is rejected with
        `ERR_REVIEWER_CAPACITY_EXCEEDED`, while one slot below maximum is
        admitted."

        Design: Difficulty/resource_temporal_overlap/reviewer_capacity_aggregate_overlap_with_release
        """
        rev, cycles, _ = self._setup(api)
        assert get_reviewer(rev["id"])["active_assignment_count"] == 2
        resp = api.create_assignment(
            create_assignment_payload(cycles[2]["id"], rev["id"],
                                      cycles[2]["version"]), COORD)
        validate_error(resp, ApiErrorId.ERR_REVIEWER_CAPACITY_EXCEEDED, 409)

    def test_release_frees_a_window_and_retry_succeeds(self, api):
        """PRD §3.4: "A coordinator may also release an `ACTIVE` assignment
        outright as the compensating action for assignment creation — same
        effects: `ACTIVE → RELEASED`, `ended_at` stamped, count decremented."

        Design: Difficulty/resource_temporal_overlap/reviewer_capacity_aggregate_overlap_with_release
        """
        rev, cycles, asg1 = self._setup(api)
        api.create_assignment(
            create_assignment_payload(cycles[2]["id"], rev["id"],
                                      cycles[2]["version"]), COORD)
        validate_success(api.release_assignment(asg1["id"], COORD), 200)
        resp = api.create_assignment(
            create_assignment_payload(cycles[2]["id"], rev["id"],
                                      cycles[2]["version"]), COORD)
        asg3 = validate_success(resp, 201)
        assert asg3["status"] == "ACTIVE"
        assert get_reviewer(rev["id"])["active_assignment_count"] == 2


class TestAssignReleaseInvariant:
    def _setup(self, api):
        bundle = setup_registered_engagement(
            jur_overrides={"state_code": "ID", "sla_mode": "CALENDAR"})
        rev = bundle["reviewer"]
        cyc1 = open_cycle(bundle["engagement"]["id"], documents_ref="s3://inv-1")
        assign_cycle(cyc1, rev["id"])
        eng2 = make_engagement(bundle["jurisdiction"], rev,
                               project_name="Invariant Pair")
        cyc2 = open_cycle(eng2["id"], documents_ref="s3://inv-2")
        return rev, cyc2

    def test_assign_increments_count_by_exactly_one(self, api):
        """PRD §3.1: "A reviewer's `active_assignment_count` starts at 0 on
        registration and is thereafter a computed figure: the count of that
        reviewer's assignments currently in `ACTIVE` status."
        PRD §3.4: "The new assignment is born `ACTIVE` with `assigned_at`
        stamped from the logical clock and `ended_at` null; the assignee's
        `active_assignment_count` increments."

        Design: Difficulty/compensating_invariant/assign_release_conserve_reviewer_active_count
        """
        rev, cyc2 = self._setup(api)
        assert get_reviewer(rev["id"])["active_assignment_count"] == 1
        asg2 = assign_cycle(cyc2, rev["id"])
        assert asg2["status"] == "ACTIVE"
        assert asg2["ended_at"] is None
        assert get_reviewer(rev["id"])["active_assignment_count"] == 2

    def test_release_restores_pre_action_value(self, api):
        """PRD §3.4: "A coordinator may also release an `ACTIVE` assignment
        outright as the compensating action for assignment creation — same
        effects: `ACTIVE → RELEASED`, `ended_at` stamped, count decremented."

        Design: Difficulty/compensating_invariant/assign_release_conserve_reviewer_active_count
        """
        rev, cyc2 = self._setup(api)
        asg2 = assign_cycle(cyc2, rev["id"])
        assert get_reviewer(rev["id"])["active_assignment_count"] == 2
        released = validate_success(api.release_assignment(asg2["id"], COORD), 200)
        assert released["status"] == "RELEASED"
        assert released["ended_at"] is not None
        assert get_reviewer(rev["id"])["active_assignment_count"] == 1


class TestAssignmentOcc:
    def test_assignment_create_stale_cycle_version_rejected(self, api):
        """PRD §2.9: "A request to `POST /plan-review/assignments` must
        therefore carry `expected_cycle_version`, set to the value of the
        target cycle's `version` the client last observed. If that value does
        not equal the cycle's current `version` — because another writer has
        advanced it since — the creation is rejected with
        `ERR_STALE_CYCLE_VERSION` (HTTP 412)."
        PRD §3.4: "a value that no longer matches the cycle's current `version`
        is rejected with `ERR_STALE_CYCLE_VERSION` (HTTP 412), and a successful
        creation increments the cycle's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/assignment_create_stale_cycle_version_rejected
        """
        bundle = setup_registered_engagement()
        rev1 = bundle["reviewer"]
        rev2 = make_reviewer(name="OCC Two", state_code="CA",
                             expires_on="2030-01-01")
        cyc = open_cycle(bundle["engagement"]["id"], documents_ref="s3://occ-v1")
        stale_version = cyc["version"]
        asg1 = assign_cycle(cyc, rev1["id"])
        # The first assignment bumped the cycle's version by exactly 1.
        assert get_cycle(cyc["id"])["version"] == stale_version + 1
        resp = api.create_assignment(
            create_assignment_payload(cyc["id"], rev2["id"], stale_version), COORD)
        validate_error(resp, ApiErrorId.ERR_STALE_CYCLE_VERSION, 412)
        # Loser's side effects did not run.
        assert get_reviewer(rev2["id"])["active_assignment_count"] == 0
        assert get_assignment(asg1["id"])["status"] == "ACTIVE"


class TestAssignmentLicensing:
    def test_assignment_license_state_mismatch_rejected(self, api):
        """PRD §3.4: "The named reviewer must hold a license whose `state_code`
        covers the engagement's `pinned_state_code`
        (`ERR_LICENSE_STATE_MISMATCH`)."

        Design: Corner/validations/assignment_license_state_mismatch_rejected
        """
        bundle = setup_registered_engagement()
        rev_nv = make_reviewer(name="NV Only", state_code="NV")
        cyc = open_cycle(bundle["engagement"]["id"], documents_ref="s3://sm-v1")
        resp = api.create_assignment(
            create_assignment_payload(cyc["id"], rev_nv["id"], cyc["version"]),
            COORD)
        validate_error(resp, ApiErrorId.ERR_LICENSE_STATE_MISMATCH, 422)
        assert get_cycle(cyc["id"])["status"] == "OPEN"

    def test_assignment_license_window_insufficient_rejected(self, api):
        """PRD §3.4: "that license's `expires_on` must be on or after the date
        of the cycle's `due_at` (`ERR_LICENSE_WINDOW_INSUFFICIENT`)."

        Design: Corner/validations/assignment_license_window_insufficient_rejected
        """
        bundle = setup_registered_engagement(
            jur_overrides={"sla_mode": "CALENDAR", "turnaround_days": 15},
            rev_overrides={"expires_on": "2026-08-10"})
        rev = bundle["reviewer"]
        set_clock("2026-08-03T10:00:00Z")
        cyc = open_cycle(bundle["engagement"]["id"], documents_ref="s3://win-v1")
        from test_helpers import assert_timestamp_equals
        assert_timestamp_equals(cyc["due_at"], "2026-08-18T10:00:00Z")
        resp = api.create_assignment(
            create_assignment_payload(cyc["id"], rev["id"], cyc["version"]), COORD)
        validate_error(resp, ApiErrorId.ERR_LICENSE_WINDOW_INSUFFICIENT, 422)


class TestAssignmentLifecycle:
    def test_assignment_on_issued_cycle_rejected(self, api):
        """PRD §3.4: "The target cycle must be `OPEN` or `IN_REVIEW`; any other
        state fails with `ERR_CYCLE_NOT_ASSIGNABLE`."

        Design: Corner/validations/assignment_on_issued_cycle_rejected
        """
        bundle = setup_in_review_cycle()
        rev = bundle["reviewer"]
        cyc = bundle["cycle"]
        raise_comment(cyc["id"], rev["id"], code_section_ref="1604.3",
                      comment_text="nail schedule missing")
        issue_comments(cyc["id"], rev["id"])
        current = get_cycle(cyc["id"])
        resp = api.create_assignment(
            create_assignment_payload(cyc["id"], rev["id"], current["version"]),
            COORD)
        validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_ASSIGNABLE, 409)
        assert get_cycle(cyc["id"])["status"] == "COMMENTS_ISSUED"

    def test_release_of_non_active_assignment_rejected(self, api):
        """PRD §3.4: "Releasing an assignment that is not `ACTIVE` is rejected
        with `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/release_of_non_active_assignment_rejected
        """
        bundle = setup_in_review_cycle()
        asg = bundle["assignment"]
        rev = bundle["reviewer"]
        validate_success(api.release_assignment(asg["id"], COORD), 200)
        resp = api.release_assignment(asg["id"], COORD)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        assert get_reviewer(rev["id"])["active_assignment_count"] == 0

    def test_supersede_completes_active_assignment(self, api):
        """PRD §3.3: "If the previous cycle rests at `COMMENTS_ISSUED`, the new
        cycle supersedes it: the old cycle moves `COMMENTS_ISSUED → SUPERSEDED`
        — a terminal state, like `APPROVED` and `CANCELLED` — and any `ACTIVE`
        assignments on it move to `COMPLETED`."

        Design: Corner/state_machines/supersede_completes_active_assignment
        """
        bundle = setup_in_review_cycle()
        rev = bundle["reviewer"]
        cyc1 = bundle["cycle"]
        asg1 = bundle["assignment"]
        raise_comment(cyc1["id"], rev["id"], code_section_ref="1604.3",
                      comment_text="Missing holdown schedule")
        issue_comments(cyc1["id"], rev["id"])
        open_cycle(bundle["engagement"]["id"], documents_ref="s3://sup-v2")
        assert get_cycle(cyc1["id"])["status"] == "SUPERSEDED"
        assert get_assignment(asg1["id"])["status"] == "COMPLETED"
        assert get_reviewer(rev["id"])["active_assignment_count"] == 0
