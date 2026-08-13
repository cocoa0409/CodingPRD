"""Project submission, initial state, queue promotion, capacity, windows, pagination."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_project,
    create_cluster_group_payload,
    create_project,
    create_project_payload,
    create_queued_project,
    get_cluster_group,
    get_project,
    make_developer_headers,
    post_deposit,
    satisfy_readiness,
    scope_study,
    setup_developer_and_cluster,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["queue_admin_headers"]


class TestProjectCreation:
    def test_project_initial_state_submitted(self, api):
        """PRD §3.2: "The new project's `status` field lands in `SUBMITTED` with
        `deposit_posted_cents` at zero, `queue_position` null, and
        `readiness_satisfied` false"

        Design: Corner/state_machines/project_initial_state_submitted
        """
        developer, cluster = setup_developer_and_cluster()
        resp = api.create_project(
            create_project_payload(developer["id"], cluster["id"]),
            make_developer_headers(developer["id"]))
        data = validate_success(resp, expected_status=201)
        assert_project(data)
        assert data["status"] == "SUBMITTED"
        assert data["queue_position"] is None
        assert data["deposit_posted_cents"] == 0
        assert data["readiness_satisfied"] is False

    def test_project_computed_field_input_ignored(self, api):
        """PRD §3.2: "At creation, the system assesses the study deposit and stamps
        it onto the read-only `deposit_required_cents`."
        PRD §3.2: "The new project's `status` field lands in `SUBMITTED` with
        `deposit_posted_cents` at zero, `queue_position` null, and
        `readiness_satisfied` false"

        Design: Corner/entities/project_computed_field_input_ignored
        """
        developer, cluster = setup_developer_and_cluster()
        payload = create_project_payload(developer["id"], cluster["id"])
        payload.update({"deposit_required_cents": 1, "queue_position": 99,
                        "status": "QUEUED"})
        resp = api.create_project(payload, make_developer_headers(developer["id"]))
        data = validate_success(resp, expected_status=201)
        assert data["deposit_required_cents"] == 1000000, (
            "server computes the deposit (10 MW SOLAR ENERGY_ONLY tier 1); "
            "the supplied 1 is ignored"
        )
        assert data["queue_position"] is None, "supplied queue_position ignored"
        assert data["status"] == "SUBMITTED", "supplied status ignored"

    def test_cluster_capacity_boundary_then_exceeded(self, api):
        """PRD §2.9: "at project creation, the cluster's `committed_mw` plus the
        new project's `capacity_mw` must not exceed the cluster's `capacity_mw`, or
        creation fails with `ERR_CLUSTER_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Corner/validations/cluster_capacity_exact_boundary_then_exceeded
        """
        developer, cluster = setup_developer_and_cluster(cluster_capacity_mw=30)
        headers = make_developer_headers(developer["id"])
        p1 = create_project(developer["id"], cluster["id"], project_name="P1",
                            capacity_mw=10, point_of_interconnection="SUB-1")
        p2 = create_project(developer["id"], cluster["id"], project_name="P2",
                            capacity_mw=20, point_of_interconnection="SUB-2")
        assert p1["id"] and p2["id"], "10 + 20 == 30 MW exactly fills the cluster"
        assert get_cluster_group(cluster["id"])["committed_mw"] == 30

        resp = api.create_project(
            create_project_payload(developer["id"], cluster["id"], project_name="P3",
                                   capacity_mw=1, point_of_interconnection="SUB-3"),
            headers)
        validate_error(resp, ApiErrorId.ERR_CLUSTER_CAPACITY_EXCEEDED)

    def test_project_creation_succeeds_while_cluster_forming(self, api):
        """PRD §3.2: "The cluster must still be `FORMING`; otherwise the submission
        is rejected with `ERR_CLUSTER_NOT_ACCEPTING_PROJECTS`."

        Design: Difficulty/cross_entity_state_dependency/project_creation_requires_cluster_forming
        """
        developer, cluster = setup_developer_and_cluster()
        resp = api.create_project(
            create_project_payload(developer["id"], cluster["id"]),
            make_developer_headers(developer["id"]))
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SUBMITTED"
        assert get_cluster_group(cluster["id"])["status"] == "FORMING"

    def test_project_creation_rejected_after_study_scoped(self, api):
        """PRD §3.2: "The cluster must still be `FORMING`; otherwise the submission
        is rejected with `ERR_CLUSTER_NOT_ACCEPTING_PROJECTS`."
        PRD §3.4: "The study is created in `IN_PROGRESS`; the cluster advances from
        `FORMING` to `STUDY_UNDERWAY`"

        Design: Difficulty/cross_entity_state_dependency/project_creation_requires_cluster_forming
        """
        developer, cluster = setup_developer_and_cluster()
        create_ready = create_queued_project(developer["id"], cluster["id"],
                                             project_name="P1")
        satisfy_readiness(create_ready["id"], developer["id"])
        scope_study(cluster["id"], total_cost_cents=1000000)
        assert get_cluster_group(cluster["id"])["status"] == "STUDY_UNDERWAY"

        resp = api.create_project(
            create_project_payload(developer["id"], cluster["id"],
                                   project_name="Latecomer", capacity_mw=5,
                                   point_of_interconnection="SUB-2"),
            make_developer_headers(developer["id"]))
        validate_error(resp, ApiErrorId.ERR_CLUSTER_NOT_ACCEPTING_PROJECTS)


class TestQueuePromotion:
    def test_deposit_exact_threshold_promotes_to_queued(self, api):
        """PRD §3.2: "The moment a deposit makes the cumulative
        `deposit_posted_cents` reach or exceed `deposit_required_cents` while the
        project is still `SUBMITTED`, the system automatically promotes the project
        from `SUBMITTED` to `QUEUED` and assigns its queue position: one greater
        than the maximum `queue_position` among the non-withdrawn members of the
        same cluster, or position one when the project is the first."

        Design: Corner/state_machines/deposit_exact_threshold_promotes_to_queued
        """
        developer, cluster = setup_developer_and_cluster()
        project = create_project(developer["id"], cluster["id"])
        assert project["deposit_required_cents"] == 1000000

        post_deposit(project["id"], developer["id"], 999999)
        mid = get_project(project["id"])
        assert mid["status"] == "SUBMITTED", "999999 < 1000000 stays SUBMITTED"
        assert mid["queue_position"] is None

        post_deposit(project["id"], developer["id"], 1)
        end = get_project(project["id"])
        assert end["status"] == "QUEUED", "1000000 >= 1000000 is inclusive"
        assert end["queue_position"] == 1, "first queued member takes position one"

    def test_occ_version_increments_on_mutation(self, api):
        """PRD §2.4: "Most resources — specifically `Developer`, `ClusterGroup`,
        `Project`, `MilestoneSubmission`, `Study`, `CostShare`, and
        `InterconnectionAgreement` — additionally carry `updated_at`, an ISO 8601
        UTC timestamp refreshed on any mutation, and `version`, an integer that
        starts at its initial value and increments by one on every mutation of the
        resource."

        Design: Corner/cross_cutting_complexity_layers/occ_version_increments_on_mutation
        """
        developer, cluster = setup_developer_and_cluster()
        project = create_project(developer["id"], cluster["id"])
        v1 = project["version"]
        assert v1 == 1, "version starts at its initial value"

        post_deposit(project["id"], developer["id"], 1000000)
        after = get_project(project["id"])
        assert after["status"] == "QUEUED"
        assert after["version"] == v1 + 1 == 2, (
            "exactly one increment for the deposit-triggered SUBMITTED -> QUEUED "
            "transition"
        )


class TestClusterWindows:
    def test_cluster_window_overlap_rejected(self, api):
        """PRD §2.9: "Within a single `region`, the application windows of any two
        clusters that are not both closed may not overlap; adjacency — one
        cluster's close exactly equal to another's open — is permitted because of
        the half-open semantics. An overlapping window is rejected with
        `ERR_CLUSTER_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/cluster_window_overlap_halfopen_adjacency_allowed
        """
        resp = api.create_cluster_group(
            create_cluster_group_payload(
                name="A", application_window_open="2026-08-01T00:00:00Z",
                application_window_close="2026-10-01T00:00:00Z", capacity_mw=100),
            ADMIN)
        cluster_a = validate_success(resp, expected_status=201)
        assert cluster_a["status"] == "FORMING"

        # B's [2026-09-01, 2026-11-01) intersects A's [2026-08-01, 2026-10-01).
        resp = api.create_cluster_group(
            create_cluster_group_payload(
                name="B", application_window_open="2026-09-01T00:00:00Z",
                application_window_close="2026-11-01T00:00:00Z", capacity_mw=100),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_CLUSTER_WINDOW_OVERLAP)

    def test_cluster_window_adjacency_and_region_scope_allowed(self, api):
        """PRD §2.9: "adjacency — one cluster's close exactly equal to another's
        open — is permitted because of the half-open semantics."
        PRD §2.9: "Within a single `region`, the application windows of any two
        clusters that are not both closed may not overlap"

        Design: Difficulty/resource_temporal_overlap/cluster_window_overlap_halfopen_adjacency_allowed
        """
        validate_success(api.create_cluster_group(
            create_cluster_group_payload(
                name="A", application_window_open="2026-08-01T00:00:00Z",
                application_window_close="2026-10-01T00:00:00Z", capacity_mw=100),
            ADMIN), expected_status=201)

        # Adjacent: C's open equals A's close — allowed under half-open semantics.
        resp = api.create_cluster_group(
            create_cluster_group_payload(
                name="C", application_window_open="2026-10-01T00:00:00Z",
                application_window_close="2026-12-01T00:00:00Z", capacity_mw=100),
            ADMIN)
        assert validate_success(resp, expected_status=201)["status"] == "FORMING"

        # Same dates as a would-be overlap but a different region never conflicts.
        resp = api.create_cluster_group(
            create_cluster_group_payload(
                name="D", region="EAST",
                application_window_open="2026-09-01T00:00:00Z",
                application_window_close="2026-11-01T00:00:00Z", capacity_mw=100),
            ADMIN)
        assert validate_success(resp, expected_status=201)["region"] == "EAST"


class TestClusterProjectListing:
    def test_cluster_projects_pagination_interaction(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of returned items; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips a number of items from the front of the list and defaults
        to 0. All list endpoints sort their results by `created_at` ascending,
        earliest first. The `meta` object of every list response carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/cluster_projects_pagination_interaction
        """
        developer, cluster = setup_developer_and_cluster()
        for i in range(1, 4):
            create_project(developer["id"], cluster["id"], project_name=f"P{i}",
                           capacity_mw=5, point_of_interconnection=f"SUB-{i}")

        page1, meta1 = validate_paginated(api.list_cluster_projects(
            cluster["id"], ADMIN, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert meta1["limit"] == 2
        assert meta1["offset"] == 0

        page2, meta2 = validate_paginated(api.list_cluster_projects(
            cluster["id"], ADMIN, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
        assert meta2["offset"] == 2

        ids = [p["id"] for p in page1] + [p["id"] for p in page2]
        assert len(set(ids)) == 3, "pages partition the member list without repeats"
