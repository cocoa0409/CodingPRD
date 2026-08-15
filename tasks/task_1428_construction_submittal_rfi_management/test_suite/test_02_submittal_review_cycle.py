"""The submittal review cycle: revisions, routing, returns, selector, capacity (PRD §3.2)."""
from test_helpers import (
    ApiErrorId,
    create_revision_payload,
    get_reviewer,
    get_submittal,
    get_success_data,
    make_reviewer_headers,
    make_subcontractor_rep_headers,
    return_revision,
    route_revision,
    setup_register_world,
    setup_reviewer_capacity_world,
    submit_revision,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["project_manager_headers"]
PE = TEST_USERS["project_engineer_headers"]


class TestRevisionStateMachine:
    def test_return_before_route_rejected(self, api):
        """PRD §3.2: "Returning a revision belongs to the assigned `Reviewer` alone: the
        revision must be `UNDER_REVIEW` (otherwise `ERR_REVISION_NOT_UNDER_REVIEW`), and
        the acting `X-User-ID` must equal the revision's `reviewer_id` (otherwise
        `ERR_REVIEWER_NOT_ASSIGNED`)."
        Isolated scenario: the assigned reviewer returns twice — the second return meets
        the identity check, so only the state rule can fail (revision already RETURNED).

        Design: Corner/state_machines/return_before_route_rejected
        """
        world = setup_register_world()
        submittal = world["submittals"][0]
        reviewer = world["reviewers"][0]
        revision = submit_revision(submittal["id"], world["subcontractor"]["id"])
        route_revision(revision["id"], reviewer["id"])
        returned = return_revision(revision["id"], reviewer["id"], "A")
        assert returned["status"] == "RETURNED"

        resp = api.return_revision(
            revision["id"], {"action_code": "A"}, make_reviewer_headers(reviewer["id"])
        )
        validate_error(resp, ApiErrorId.ERR_REVISION_NOT_UNDER_REVIEW, 409)

    def test_route_twice_rejected(self, api):
        """PRD §3.2: "Routing, performed by a `ProjectEngineer` while the project is
        `ACTIVE` (`ERR_PROJECT_NOT_ACTIVE` otherwise), requires the revision to be
        `SUBMITTED` (otherwise `ERR_REVISION_NOT_SUBMITTED`)."
        PRD §3.2: "increments the reviewer's `open_review_count` by one, and moves the
        revision to `UNDER_REVIEW`" — the rejected second route must not double-count.

        Design: Corner/state_machines/route_twice_rejected
        """
        world = setup_register_world()
        submittal = world["submittals"][0]
        reviewer = world["reviewers"][0]
        revision = submit_revision(submittal["id"], world["subcontractor"]["id"])
        route_revision(revision["id"], reviewer["id"])

        resp = api.route_revision(revision["id"], {"reviewer_id": reviewer["id"]}, PE)
        validate_error(resp, ApiErrorId.ERR_REVISION_NOT_SUBMITTED, 409)
        assert get_reviewer(reviewer["id"])["open_review_count"] == 1, (
            "the first route's assignment is unchanged by the rejected re-route"
        )


class TestOwnershipOnReviewCycle:
    def test_wrong_subcontractor_cannot_submit_revision(self, api):
        """PRD §3.2: "The acting representative must be the section's responsible
        subcontractor — the `X-User-ID` is compared to the section's
        `responsible_subcontractor_id`, and a mismatch is `ERR_WRONG_SUBCONTRACTOR`"
        PRD §2.1: "with a mismatch rejected as `ERR_WRONG_SUBCONTRACTOR` (HTTP 403)."

        Design: Corner/validations/wrong_subcontractor_cannot_submit_revision
        """
        world = setup_register_world()
        other = get_success_data(
            api.create_subcontractor(
                world["project"]["id"],
                {"company_name": "OtherCo", "trade": "glazing"},
                PE,
            )
        )
        submittal = world["submittals"][0]
        resp = api.create_revision(
            submittal["id"],
            create_revision_payload("doc://bad", submittal["version"]),
            make_subcontractor_rep_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WRONG_SUBCONTRACTOR, 403)

    def test_unassigned_reviewer_cannot_return(self, api):
        """PRD §3.2: "the acting `X-User-ID` must equal the revision's `reviewer_id`
        (otherwise `ERR_REVIEWER_NOT_ASSIGNED`)."

        Design: Corner/validations/unassigned_reviewer_cannot_return
        """
        world = setup_register_world(
            reviewers=(
                {"display_name": "Arch One", "discipline": "ARCH"},
                {"display_name": "Arch Two", "discipline": "ARCH"},
            )
        )
        r1, r2 = world["reviewers"]
        revision = submit_revision(
            world["submittals"][0]["id"], world["subcontractor"]["id"]
        )
        route_revision(revision["id"], r1["id"])

        resp = api.return_revision(
            revision["id"], {"action_code": "A"}, make_reviewer_headers(r2["id"])
        )
        validate_error(resp, ApiErrorId.ERR_REVIEWER_NOT_ASSIGNED, 403)


class TestReviewerRouting:
    def test_explicit_reviewer_discipline_mismatch_rejected(self, api):
        """PRD §3.2: "An explicit reviewer must exist within the project, hold
        `reviewer_status` `ACTIVE`, match the section's `required_discipline` (a mismatch
        is `ERR_DISCIPLINE_MISMATCH`), and have an `open_review_count` strictly below
        their `review_capacity`"

        Design: Corner/errors/explicit_reviewer_discipline_mismatch_rejected
        """
        world = setup_register_world(
            reviewers=({"display_name": "Struct One", "discipline": "STRUCT"},)
        )
        revision = submit_revision(
            world["submittals"][0]["id"], world["subcontractor"]["id"]
        )
        resp = api.route_revision(
            revision["id"], {"reviewer_id": world["reviewers"][0]["id"]}, PE
        )
        validate_error(resp, ApiErrorId.ERR_DISCIPLINE_MISMATCH, 409)

    def test_no_eligible_reviewer_when_pool_empty(self, api):
        """PRD §3.2: "An empty candidate set fails with `ERR_NO_ELIGIBLE_REVIEWER`;
        there is no fallback assignment."

        Design: Corner/errors/no_eligible_reviewer_when_pool_empty
        """
        world = setup_register_world(reviewers=())
        revision = submit_revision(
            world["submittals"][0]["id"], world["subcontractor"]["id"]
        )
        resp = api.route_revision(revision["id"], {}, PE)
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_REVIEWER, 409)

    def test_reviewer_selector_tiebreak_uses_created_at(self, api):
        """PRD §3.2: "they are ranked by `open_review_count` ascending with `created_at`
        ascending as the only tie-break (never the id), and the first candidate is
        selected." Two equally loaded ACTIVE ARCH reviewers: the one created first wins.

        Design: Corner/calculations/reviewer_selector_tiebreak_uses_created_at
        """
        world = setup_register_world(
            reviewers=(
                {"display_name": "Arch One", "discipline": "ARCH"},
                {"display_name": "Arch Two", "discipline": "ARCH"},
            )
        )
        r1, _r2 = world["reviewers"]
        revision = submit_revision(
            world["submittals"][0]["id"], world["subcontractor"]["id"]
        )
        routed = route_revision(revision["id"], None)
        assert routed["reviewer_id"] == r1["id"], (
            "equal open_review_count on both candidates selects the earlier created_at"
        )


class TestReviewerCapacityBoundary:
    def test_reviewer_accepts_assignments_up_to_capacity(self, api):
        """PRD §3.2: "candidates are the project's reviewers who are `ACTIVE`, whose
        `discipline` equals the section's `required_discipline`, and whose
        `open_review_count` is strictly below `review_capacity`"
        Three explicit routes onto a capacity-3 reviewer all succeed: the strict-less-than
        rule admits the assignment that brings the count exactly to capacity.

        Design: Difficulty/boundary_precision_check/reviewer_capacity_strict_less_than_boundary
        """
        world = setup_reviewer_capacity_world(num_submittals=4, r1_capacity=3)
        r1, _r2 = world["reviewers"]
        for revision in world["revisions"][:3]:
            route_revision(revision["id"], r1["id"])
        assert get_reviewer(r1["id"])["open_review_count"] == 3, (
            "three successful routes leave the reviewer exactly at capacity 3"
        )

    def test_selector_excludes_reviewer_at_capacity(self, api):
        """PRD §3.2: "An explicit reviewer must exist within the project, hold
        `reviewer_status` `ACTIVE`, match the section's `required_discipline` (a mismatch
        is `ERR_DISCIPLINE_MISMATCH`), and have an `open_review_count` strictly below
        their `review_capacity` — a reviewer already at capacity is rejected with
        `ERR_REVIEWER_AT_CAPACITY`."
        With R1 at count == capacity, the unassigned fourth route falls to R2.

        Design: Difficulty/boundary_precision_check/reviewer_capacity_strict_less_than_boundary
        """
        world = setup_reviewer_capacity_world(num_submittals=4, r1_capacity=3)
        r1, r2 = world["reviewers"]
        for revision in world["revisions"][:3]:
            route_revision(revision["id"], r1["id"])

        routed = route_revision(world["revisions"][3]["id"], None)
        assert get_reviewer(r1["id"])["open_review_count"] == 3
        assert routed["reviewer_id"] == r2["id"], (
            "a reviewer at open_review_count == review_capacity is excluded from the "
            "selector; the capacity value itself belongs to the rejection side"
        )


class TestReviewerAggregateCapacity:
    def test_third_overlapping_assignment_rejected_at_capacity(self, api):
        """PRD §3.2: "have an `open_review_count` strictly below their
        `review_capacity` — a reviewer already at capacity is rejected with
        `ERR_REVIEWER_AT_CAPACITY`." Capacity counts concurrent held reviews: the third
        overlapping assignment onto a capacity-2 reviewer fails.

        Design: Difficulty/resource_temporal_overlap/reviewer_window_aggregate_capacity_overlap
        """
        world = setup_reviewer_capacity_world(num_submittals=3, r1_capacity=2, with_r2=False)
        r1 = world["reviewers"][0]
        route_revision(world["revisions"][0]["id"], r1["id"])
        route_revision(world["revisions"][1]["id"], r1["id"])

        resp = api.route_revision(
            world["revisions"][2]["id"], {"reviewer_id": r1["id"]}, PE
        )
        validate_error(resp, ApiErrorId.ERR_REVIEWER_AT_CAPACITY, 409)
        assert get_reviewer(r1["id"])["open_review_count"] == 2

    def test_return_frees_slot_and_retry_succeeds(self, api):
        """PRD §3.2: "The reviewer's `open_review_count` decrements by one, floored at
        zero." Returning one held review frees a slot, so the previously rejected route
        succeeds — capacity is a count of overlapping reviews, not a boolean lock.

        Design: Difficulty/resource_temporal_overlap/reviewer_window_aggregate_capacity_overlap
        """
        world = setup_reviewer_capacity_world(num_submittals=3, r1_capacity=2, with_r2=False)
        r1 = world["reviewers"][0]
        route_revision(world["revisions"][0]["id"], r1["id"])
        route_revision(world["revisions"][1]["id"], r1["id"])
        resp = api.route_revision(
            world["revisions"][2]["id"], {"reviewer_id": r1["id"]}, PE
        )
        validate_error(resp, ApiErrorId.ERR_REVIEWER_AT_CAPACITY, 409)

        return_revision(world["revisions"][0]["id"], r1["id"], "B", comments="noted")
        retry = route_revision(world["revisions"][2]["id"], r1["id"])
        assert retry["status"] == "UNDER_REVIEW"
        assert get_reviewer(r1["id"])["open_review_count"] == 2, (
            "the returned revision freed exactly one slot; the retry refilled it"
        )


class TestReviewerWorkloadInvariant:
    def test_routes_increment_open_review_count(self, api):
        """PRD §3.2: "increments the reviewer's `open_review_count` by one, and moves the
        revision to `UNDER_REVIEW`." Two routes onto one reviewer move the count 0 -> 2.

        Design: Difficulty/compensating_invariant/reviewer_workload_route_return_conserves_count
        """
        world = setup_reviewer_capacity_world(num_submittals=2, r1_capacity=3, with_r2=False)
        r1 = world["reviewers"][0]
        assert get_reviewer(r1["id"])["open_review_count"] == 0
        route_revision(world["revisions"][0]["id"], r1["id"])
        route_revision(world["revisions"][1]["id"], r1["id"])
        assert get_reviewer(r1["id"])["open_review_count"] == 2

    def test_returns_decrement_open_review_count_to_origin(self, api):
        """PRD §3.2: "The reviewer's `open_review_count` decrements by one, floored at
        zero." Route (+1) and return (-1) are compensating actions: after a
        route/return pair per revision the count returns to its origin, matching the
        number of that reviewer's remaining UNDER_REVIEW revisions.

        Design: Difficulty/compensating_invariant/reviewer_workload_route_return_conserves_count
        """
        world = setup_reviewer_capacity_world(num_submittals=2, r1_capacity=3, with_r2=False)
        r1 = world["reviewers"][0]
        route_revision(world["revisions"][0]["id"], r1["id"])
        route_revision(world["revisions"][1]["id"], r1["id"])
        assert get_reviewer(r1["id"])["open_review_count"] == 2

        return_revision(world["revisions"][0]["id"], r1["id"], "A")
        return_revision(world["revisions"][1]["id"], r1["id"], "C", comments="redo")
        assert get_reviewer(r1["id"])["open_review_count"] == 0


class TestResubmittalCycle:
    def _cycle_world(self):
        return setup_register_world(
            project_name="Cycle",
            section_number="051200",
            lead_time_days=35,
            review_days=10,
            default_need_date="2026-10-30",
            required_submittal_kinds=("SHOP_DRAWINGS",),
        )

    def test_c_return_primes_resubmittal_and_supersedes_prior_revision(self, api):
        """PRD §3.2: "an `A` or `B` action moves `review_status` from `IN_REVIEW` to
        `APPROVED`, while a `C` or `D` action moves it to `RETURNED_NEEDS_RESUBMIT`,
        priming the resubmittal loop"
        PRD §3.2: "On acceptance the revision takes `revision_number` equal to the
        submittal's current `revision_count`, which is then incremented by one (so the
        first revision is number zero)."
        PRD §3.2: "any prior revision of the same submittal in `RETURNED` status with
        action code `C` or `D` is moved to `SUPERSEDED` — only `RETURNED` revisions
        carrying `C` or `D` may be superseded."

        Design: Difficulty/non_linear_state_machine/submittal_resubmittal_cycle_with_parallel_dimension
        """
        world = self._cycle_world()
        submittal = world["submittals"][0]
        reviewer = world["reviewers"][0]
        subcontractor = world["subcontractor"]

        rev0 = submit_revision(submittal["id"], subcontractor["id"], "doc://rev0")
        route_revision(rev0["id"], reviewer["id"])
        return_revision(rev0["id"], reviewer["id"], "C", comments="fix welds")
        mid = get_submittal(submittal["id"])
        assert mid["review_status"] == "RETURNED_NEEDS_RESUBMIT"

        rev1 = submit_revision(submittal["id"], subcontractor["id"], "doc://rev1")
        assert rev1["revision_number"] == 1, "the resubmittal takes the next number"
        rev0_after = get_success_data(api.get_revision(rev0["id"], PE))
        assert rev0_after["status"] == "SUPERSEDED"
        assert get_submittal(submittal["id"])["review_status"] == "IN_REVIEW"

    def test_review_cycle_leaves_expediting_dimension_untouched(self, api):
        """PRD §3.4: "The submittal's `expediting_status` rides alongside as a parallel
        dimension, independent of `review_status`." A long-lead submittal generated into
        `MONITORING` completes the full C-return -> resubmit -> A-return review cycle
        while the expediting dimension never moves.

        Design: Difficulty/non_linear_state_machine/submittal_resubmittal_cycle_with_parallel_dimension
        """
        world = self._cycle_world()
        submittal = world["submittals"][0]
        reviewer = world["reviewers"][0]
        subcontractor = world["subcontractor"]

        assert get_submittal(submittal["id"])["expediting_status"] == "MONITORING"

        rev0 = submit_revision(submittal["id"], subcontractor["id"], "doc://rev0")
        route_revision(rev0["id"], reviewer["id"])
        return_revision(rev0["id"], reviewer["id"], "C", comments="fix welds")
        assert get_submittal(submittal["id"])["expediting_status"] == "MONITORING"

        rev1 = submit_revision(submittal["id"], subcontractor["id"], "doc://rev1")
        route_revision(rev1["id"], reviewer["id"])
        return_revision(rev1["id"], reviewer["id"], "A", comments="ok")

        final = get_submittal(submittal["id"])
        assert final["review_status"] == "APPROVED", "the cycle closes on the A return"
        assert final["revision_count"] == 2
        assert final["expediting_status"] == "MONITORING"


class TestRevisionCreateConcurrencyAndPosture:
    def test_occ_stale_submittal_version_on_revision_create(self, api):
        """PRD §2.9: "Creating a submittal revision
        (`POST /v1/submittals/{submittalId}/revisions`) requires
        `expected_submittal_version`. A new revision legitimately supersedes a returned
        predecessor and advances the submittal's `version`; a create carrying a
        previously observed version is stale and is rejected with
        `ERR_STALE_SUBMITTAL_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_submittal_version_on_revision_create
        """
        world = setup_register_world()
        submittal = world["submittals"][0]
        observed_version = submittal["version"]
        submit_revision(submittal["id"], world["subcontractor"]["id"], "doc://r0")

        resp = api.create_revision(
            submittal["id"],
            create_revision_payload("doc://r1", observed_version),
            make_subcontractor_rep_headers(world["subcontractor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_SUBMITTAL_VERSION, 412)

    def test_revision_submit_rejected_while_project_suspended(self, api):
        """PRD §2.5: "every operation that creates or mutates a child resource —
        submittal date changes, deferral requests and decisions, releases and voids and
        closes, revision submission, routing, and return, RFI creation, routing,
        answering, reopening, distribution, and closure, impact pricing, repricing,
        acceptance, waiver, and dispute, distribution sends and acknowledgements,
        installation activity creation, release, completion, and cancellation, long-lead
        advances and manual expedites, owner-report creation and publication, and the
        daily scan — requires the project to be `ACTIVE` and is otherwise rejected with
        `ERR_PROJECT_NOT_ACTIVE` (HTTP 409)."
        The submittal itself is in a revision-accepting state (REGISTERED); the parent
        posture gates the child write.

        Design: Difficulty/cross_entity_state_dependency/revision_submit_requires_project_active
        """
        world = setup_register_world(project_name="Gate3")
        project = world["project"]
        submittal = world["submittals"][0]
        get_success_data(api.suspend_project(project["id"], PM))

        resp = api.create_revision(
            submittal["id"],
            create_revision_payload("doc://r0", current_or_fresh_version(api, submittal["id"])),
            make_subcontractor_rep_headers(world["subcontractor"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_ACTIVE, 409)
        assert get_submittal(submittal["id"])["revision_count"] == 0, (
            "no revision was created while the project was suspended"
        )

    def test_revision_submit_succeeds_after_project_resume(self, api):
        """PRD §2.5: "A `ProjectManager` activates it (`SETUP` → `ACTIVE`), may suspend
        it (`ACTIVE` → `SUSPENDED`) and later resume it (`SUSPENDED` → `ACTIVE`)"
        After resumption the posture gate lifts and the same revision submit succeeds.

        Design: Difficulty/cross_entity_state_dependency/revision_submit_requires_project_active
        """
        world = setup_register_world(project_name="Gate3")
        project = world["project"]
        submittal = world["submittals"][0]
        get_success_data(api.suspend_project(project["id"], PM))
        get_success_data(api.resume_project(project["id"], PM))

        revision = submit_revision(submittal["id"], world["subcontractor"]["id"], "doc://r0")
        assert revision["status"] == "SUBMITTED"
        assert get_submittal(submittal["id"])["review_status"] == "IN_REVIEW"


def current_or_fresh_version(api, submittal_id) -> int:
    """Local helper: read the submittal's current version for the OCC payload."""
    return get_submittal(submittal_id)["version"]
