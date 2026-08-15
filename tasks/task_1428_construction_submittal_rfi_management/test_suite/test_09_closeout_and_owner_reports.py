"""Project closeout gating and owner reporting (PRD §2.5, §3.1, §3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_spec_section,
    add_reviewer,
    add_spec_section,
    add_subcontractor,
    answer_rfi,
    create_active_project,
    create_owner_report,
    create_rfi,
    publish_owner_report,
    report_metrics,
    return_revision,
    route_revision,
    route_rfi,
    set_clock,
    setup_register_world,
    submit_revision,
    submittals_of_section,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["project_manager_headers"]
PE = TEST_USERS["project_engineer_headers"]


class TestBeginCloseout:
    def test_begin_closeout_blocked_by_open_items(self, api):
        """PRD §3.1: "Beginning closeout is the consequential step: it moves the project
        from `ACTIVE` to `CLOSEOUT` only when the project is fully drained of open work,
        and otherwise fails with `ERR_CLOSEOUT_BLOCKED`. The gate demands that every
        submittal has a `review_status` of `CLOSED` or `VOID` — or, failing that, holds a
        `deferral_status` of `DEFERRED_APPROVED`; that every RFI is `CLOSED` or `VOID`;
        that every ImpactAssessment is `ACCEPTED` or `WAIVED`; that every
        DistributionRecord is `ACKNOWLEDGED`; that every InstallationActivity is
        `COMPLETED` or `CANCELLED`; and that no OwnerReport remains in `DRAFT`."
        A single REGISTERED submittal blocks the gate; voiding it lets closeout begin.

        Design: Corner/state_machines/begin_closeout_blocked_by_open_items
        """
        world = setup_register_world(
            section_number="033000", lead_time_days=5, default_need_date="2026-10-30"
        )
        project = world["project"]
        submittal = world["submittals"][0]

        resp = api.begin_closeout_project(project["id"], PM)
        validate_error(resp, ApiErrorId.ERR_CLOSEOUT_BLOCKED, 409)

        validate_success(
            api.void_submittal(submittal["id"], {"reason": "cut"}, PM), 200
        )
        closed_out = validate_success(api.begin_closeout_project(project["id"], PM), 200)
        assert closed_out["posture"] == "CLOSEOUT"


class TestOwnerReportLifecycle:
    def test_publish_twice_rejected(self, api):
        """PRD §3.9: "Publishing, by a `ProjectEngineer`, requires `DRAFT` (otherwise
        `ERR_REPORT_NOT_DRAFT`)."

        Design: Corner/state_machines/publish_twice_rejected
        """
        project = create_active_project("P")
        report = create_owner_report(project["id"], "2026-08-01", "2026-08-31")
        publish_owner_report(report["id"])

        resp = api.publish_owner_report(report["id"], PE)
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_DRAFT, 409)

    def test_occ_report_create_supersedes_then_stale_rejected(self, api):
        """PRD §3.9: "The new report is born `DRAFT`, and its creation immediately
        supersedes any `PUBLISHED` report whose inclusive period interval overlaps its
        own: the older report moves to `SUPERSEDED` with its `superseded_by_report_id`
        set to the new report's id."
        PRD §3.9: "because creation is optimistic-concurrency guarded, an
        `expected_project_version` equal to the project's current `version`: a new report
        whose period overlaps a published report legitimately supersedes it and advances
        the project, so a create carrying a previously observed version is stale and is
        refused with `ERR_STALE_PROJECT_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_report_create_supersedes_then_stale_rejected
        """
        project = create_active_project("P")
        report1 = create_owner_report(project["id"], "2026-08-01", "2026-08-31")
        publish_owner_report(report1["id"])

        from test_helpers import current_project_version

        pre_supersede_version = current_project_version(project["id"])
        report2 = create_owner_report(
            project["id"], "2026-08-15", "2026-09-15", pre_supersede_version
        )

        report1_after = validate_success(api.get_owner_report(report1["id"], PE), 200)
        assert report1_after["status"] == "SUPERSEDED"
        assert report1_after["superseded_by_report_id"] == report2["id"], (
            "the overlapping create supersedes the published report"
        )

        resp = api.create_owner_report(
            project["id"],
            {
                "period_start": "2026-09-01",
                "period_end": "2026-09-30",
                "expected_project_version": pre_supersede_version,
            },
            PE,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_PROJECT_VERSION, 412)


class TestReportMetrics:
    def test_owner_report_avg_response_and_yield_literals(self, api):
        """PRD §3.9: "`avg_rfi_response_days` averages the business-day response
        duration over RFIs in `ANSWERED` or `CLOSED` whose `answered_date` falls within
        the report period inclusive, where a single RFI's duration counts the business
        days strictly after its `opened_date` up to and including its `answered_date` —
        so an answer on the opening day itself counts zero; the mean is rounded half-up
        to two decimal places, and an empty set reports 0.00."
        PRD §3.9: "`first_pass_yield_pct` looks at submittals whose revision number zero
        has a `returned_date` within the period inclusive, and computes one hundred times
        the count of those returned with `action_code` `A` or `B` divided by the count
        returned, rounded half-up to one decimal place; an empty set reports 0.0."
        PRD §3.9: "`open_submittals` counts the project's submittals whose
        `review_status` is neither `CLOSED` nor `VOID`."
        RFIs answered in 4 and 6 business days average to 5.0; one revision-zero 'A'
        return in the period yields 100.0; the APPROVED submittal still counts open.

        Design: Corner/calculations/owner_report_avg_response_and_yield_literals
        """
        project = create_active_project("M")
        subcontractor = add_subcontractor(
            project["id"], company_name="SteelFab", trade="steel"
        )
        reviewer = add_reviewer(project["id"], display_name="Arch One", discipline="ARCH")
        section = add_spec_section(
            project["id"], "051200", responsible_subcontractor_id=subcontractor["id"]
        )
        activate_spec_section(section["id"])
        submittal = submittals_of_section(project["id"], "051200")[0]

        set_clock("2026-08-03T09:00:00Z")
        rfi1 = create_rfi(project["id"], subject="R1")
        route_rfi(rfi1["id"], reviewer["id"])
        rfi2 = create_rfi(project["id"], subject="R2")
        route_rfi(rfi2["id"], reviewer["id"])

        set_clock("2026-08-07T09:00:00Z")
        answer_rfi(rfi1["id"], reviewer["id"], answer_text="a")

        set_clock("2026-08-11T09:00:00Z")
        answer_rfi(rfi2["id"], reviewer["id"], answer_text="a")

        set_clock("2026-08-12T09:00:00Z")
        revision = submit_revision(submittal["id"], subcontractor["id"], "doc://r0")
        route_revision(revision["id"], reviewer["id"])
        return_revision(revision["id"], reviewer["id"], "A")

        report = create_owner_report(project["id"], "2026-08-01", "2026-08-31")
        publish_owner_report(report["id"])

        metrics = report_metrics(report["id"], view="published")
        assert metrics["avg_rfi_response_days"] == pytest.approx(5.0, abs=0.005), (
            "durations 4 (2026-08-03 -> 2026-08-07) and 6 (2026-08-03 -> 2026-08-11) "
            "over (opened, answered] business days"
        )
        assert metrics["first_pass_yield_pct"] == pytest.approx(100.0, abs=0.05)
        assert metrics["open_submittals"] == 1, "APPROVED is neither CLOSED nor VOID"

    def test_metrics_snapshot_frozen_at_publish(self, api):
        """PRD §3.9: "At publish the system freezes the report's `snapshot_metrics` —
        the SNAPSHOT variant of the period metrics, reflecting the database exactly as it
        stood at publish time and never changing afterward"
        PRD §3.9: "the `view` parameter selects `published` (the default), which returns
        the frozen `snapshot_metrics` fields"
        Two REGISTERED submittals at publish freeze open_submittals at 2 even after one
        is voided.

        Design: Difficulty/dual_variant_calc/report_metrics_snapshot_vs_live
        """
        project = create_active_project("DV Metrics")
        section = add_spec_section(
            project["id"],
            "033000",
            required_submittal_kinds=["PRODUCT_DATA", "SHOP_DRAWINGS"],
            default_need_date="2026-10-30",
        )
        activate_spec_section(section["id"])
        submittals = submittals_of_section(project["id"], "033000")
        assert len(submittals) == 2

        report = create_owner_report(project["id"], "2026-08-01", "2026-08-31")
        publish_owner_report(report["id"])

        validate_success(
            api.void_submittal(submittals[0]["id"], {"reason": "scope removed"}, PM),
            200,
        )

        published = report_metrics(report["id"], view="published")
        assert published["open_submittals"] == 2, "the snapshot never changes after publish"

    def test_metrics_live_view_recomputes_after_publish(self, api):
        """PRD §3.9: "or `live`, which recomputes the same five metrics from current
        data and therefore diverges from the snapshot once the underlying entities
        mutate after publish."
        PRD §3.9: "`open_submittals` counts the project's submittals whose
        `review_status` is neither `CLOSED` nor `VOID`."
        After the void, the live view counts 1 open submittal while the published
        snapshot still reports 2.

        Design: Difficulty/dual_variant_calc/report_metrics_snapshot_vs_live
        """
        project = create_active_project("DV Metrics")
        section = add_spec_section(
            project["id"],
            "033000",
            required_submittal_kinds=["PRODUCT_DATA", "SHOP_DRAWINGS"],
            default_need_date="2026-10-30",
        )
        activate_spec_section(section["id"])
        submittals = submittals_of_section(project["id"], "033000")

        report = create_owner_report(project["id"], "2026-08-01", "2026-08-31")
        publish_owner_report(report["id"])
        validate_success(
            api.void_submittal(submittals[0]["id"], {"reason": "scope removed"}, PM),
            200,
        )

        live = report_metrics(report["id"], view="live")
        published = report_metrics(report["id"], view="published")
        assert live["open_submittals"] == 1, "the VOID submittal is excluded live"
        assert published["open_submittals"] == 2
        assert live["open_submittals"] != published["open_submittals"]
