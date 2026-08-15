"""Curtailment operating limits and transparency reporting."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_curtailment_limit,
    assert_transparency_report,
    create_curtailment_limit_payload,
    create_project,
    create_queued_project,
    create_transparency_report,
    make_developer_headers,
    post_full_deposit,
    setup_developer_and_cluster,
    setup_project_agreement_executed,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_project,
)

ADMIN = TEST_USERS["queue_admin_headers"]


class TestCurtailmentWindowOverlap:
    def test_curtailment_touching_endpoints_overlap(self, api):
        """PRD §2.9: "Two limits on the same project with the same `limit_type`
        must have disjoint effective intervals — and because the intervals are
        closed, touching endpoints count as overlap, triggering
        `ERR_CURTAILMENT_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/curtailment_window_overlap_closed_adjacency_rejected
        """
        scenario = setup_project_agreement_executed(curtailment_hours_cap=100)
        project = scenario["project"]

        first = validate_success(api.create_curtailment_limit(
            project["id"],
            create_curtailment_limit_payload(
                limit_type="SEASONAL", max_output_mw=8,
                effective_start="2027-06-01T00:00:00Z",
                effective_end="2027-08-31T00:00:00Z",
                curtailment_hours_per_year=200),
            ADMIN), expected_status=201)
        assert_curtailment_limit(first)

        # Start 2027-08-31 equals the existing limit's end 2027-08-31; closed
        # intervals share that instant.
        resp = api.create_curtailment_limit(
            project["id"],
            create_curtailment_limit_payload(
                limit_type="SEASONAL", max_output_mw=5,
                effective_start="2027-08-31T00:00:00Z",
                effective_end="2027-10-01T00:00:00Z",
                curtailment_hours_per_year=100),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_CURTAILMENT_WINDOW_OVERLAP)

    def test_curtailment_overlap_scoped_per_limit_type(self, api):
        """PRD §3.8: "The disjointness rule of §2.9 applies per project and
        `limit_type`, with touching endpoints counting as overlap
        (`ERR_CURTAILMENT_WINDOW_OVERLAP`)."

        Design: Difficulty/resource_temporal_overlap/curtailment_window_overlap_closed_adjacency_rejected
        """
        scenario = setup_project_agreement_executed(curtailment_hours_cap=100)
        project = scenario["project"]

        validate_success(api.create_curtailment_limit(
            project["id"],
            create_curtailment_limit_payload(
                limit_type="SEASONAL", max_output_mw=8,
                effective_start="2027-06-01T00:00:00Z",
                effective_end="2027-08-31T00:00:00Z",
                curtailment_hours_per_year=200),
            ADMIN), expected_status=201)

        # Identical window under a different limit_type is allowed.
        resp = api.create_curtailment_limit(
            project["id"],
            create_curtailment_limit_payload(
                limit_type="EMERGENCY", max_output_mw=6,
                effective_start="2027-06-01T00:00:00Z",
                effective_end="2027-08-31T00:00:00Z",
                curtailment_hours_per_year=50),
            ADMIN)
        data = validate_success(resp, expected_status=201)
        assert_curtailment_limit(data)
        assert data["limit_type"] == "EMERGENCY"


class TestCurtailmentStateGate:
    def test_curtailment_requires_executed_agreement(self, api):
        """PRD §3.8: "Operating-limit conditions are recorded once a project is
        `AGREEMENT_EXECUTED` or in `COMMERCIAL_OPERATION`; earlier attempts are
        rejected with `ERR_PROJECT_NOT_ACCEPTING_CURTAILMENT_LIMITS`."

        Design: Corner/validations/curtailment_requires_executed_agreement
        """
        developer, cluster = setup_developer_and_cluster()
        project = create_queued_project(developer["id"], cluster["id"])
        assert project["status"] == "QUEUED"

        resp = api.create_curtailment_limit(
            project["id"],
            create_curtailment_limit_payload(
                limit_type="SEASONAL", max_output_mw=8,
                effective_start="2027-06-01T00:00:00Z",
                effective_end="2027-08-31T00:00:00Z",
                curtailment_hours_per_year=200),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_ACCEPTING_CURTAILMENT_LIMITS)

        limits, meta = validate_paginated(
            api.list_curtailment_limits(project["id"], ADMIN))
        assert limits == [] and meta["total_count"] == 0


class TestTransparencyReporting:
    def test_transparency_snapshot_counts(self, api):
        """PRD §3.9: "At creation, the snapshot counts and totals over all projects
        regardless of cluster: `queued_project_count` is the number of projects
        whose status is one of `SUBMITTED`, `QUEUED`, `READY`, `IN_STUDY`,
        `STUDY_COMPLETE`, `RESTUDY_REQUIRED`, `AGREEMENT_PENDING`, or
        `AGREEMENT_EXECUTED`; `queued_mw` is the sum of `capacity_mw` over that
        same set; `withdrawn_project_count` is the number of projects in
        `WITHDRAWN`; and `commercial_operation_project_count` is the number in
        `COMMERCIAL_OPERATION`."

        Design: Corner/calculations/transparency_snapshot_counts
        """
        developer, cluster = setup_developer_and_cluster()
        p1 = create_project(developer["id"], cluster["id"], project_name="P1",
                            capacity_mw=10, point_of_interconnection="SUB-1")
        p2 = create_project(developer["id"], cluster["id"], project_name="P2",
                            capacity_mw=20, point_of_interconnection="SUB-2")
        post_full_deposit(p2, developer["id"])  # QUEUED
        p3 = create_project(developer["id"], cluster["id"], project_name="P3",
                            capacity_mw=15, point_of_interconnection="SUB-3")
        withdraw_project(p3["id"], acting_developer_id=developer["id"])

        resp = api.create_transparency_report({"reporting_period": "2026-Q3"}, ADMIN)
        data = validate_success(resp, expected_status=201)
        assert_transparency_report(data)
        assert data["queued_project_count"] == 2, "P1 SUBMITTED + P2 QUEUED"
        assert data["queued_mw"] == 30
        assert data["withdrawn_project_count"] == 1, "P3"
        assert data["commercial_operation_project_count"] == 0
        assert data["reporting_period"] == "2026-Q3"

    def test_duplicate_reporting_period_rejected(self, api):
        """PRD §3.9: "a `QueueAdministrator` publishes an immutable transparency
        snapshot for a reporting period identified by a unique `reporting_period`
        label such as `2026-Q3`; a label already in use is rejected with
        `ERR_REPORTING_PERIOD_CONFLICT`."

        Design: Corner/validations/duplicate_reporting_period_rejected
        """
        first = create_transparency_report("2026-Q3")

        resp = api.create_transparency_report({"reporting_period": "2026-Q3"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_REPORTING_PERIOD_CONFLICT)

        again = validate_success(api.get_transparency_report(first["id"], ADMIN),
                                 expected_status=200)
        assert again["reporting_period"] == "2026-Q3"
        assert again["id"] == first["id"], "first report remains readable and unchanged"
