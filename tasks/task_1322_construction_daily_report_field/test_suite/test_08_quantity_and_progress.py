"""Quantity entries: write-time rounding, supersede, approve/reopen rollups."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_crew_entry,
    add_quantity_entry,
    add_weather_observation,
    api_client,
    get_progress_summary,
    get_project,
    get_quantity_entry,
    get_report,
    get_work_item,
    make_active_project,
    make_report,
    make_work_area,
    make_work_item,
    set_clock,
    submit_clock_for,
    validate_success,
)

_ADMIN = TEST_USERS["system_admin_headers"]
_PM = TEST_USERS["project_manager_headers"]
_SUPT = TEST_USERS["superintendent_headers"]


def _drive_to_approved(report_id):
    """Submit -> start-review -> approve a fully populated DRAFT report."""
    report = get_report(report_id)
    set_clock(submit_clock_for(report["report_date"]))
    validate_success(api_client.submit_report(report_id, _SUPT))
    validate_success(api_client.start_review_report(report_id, _PM))
    return validate_success(api_client.approve_report(report_id, _PM))


class TestWriteTimeRoundingOrder:
    def test_round_per_entry_then_sum(self, api):
        """PRD section 3.8: "the entry's `rounded_quantity` is
        `quantity_installed` rounded half-up to three decimal places, computed
        once at write time and stored." and "two entries of 1.2344 each store
        1.234 apiece and roll up to an installed total of 2.468 — summing the
        raw values first would have produced 2.469."

        Design: Difficulty/combinatorial_formula/quantity_rollup_per_entry_rounding_order
        """
        project = make_active_project()
        area1 = make_work_area(project["id"])
        area2 = make_work_area(project["id"])
        wi = make_work_item(project["id"], cost_code="03-100", description="Curb",
                            budgeted_quantity=100, unit="LF", unit_cost_cents=1000)
        report = make_report(project["id"])

        qe1 = add_quantity_entry(report["id"], wi["id"], area1["id"], 1.2344)
        assert qe1["rounded_quantity"] == pytest.approx(1.234, abs=1e-9)
        qe2 = add_quantity_entry(report["id"], wi["id"], area2["id"], 1.2344)
        assert qe2["rounded_quantity"] == pytest.approx(1.234, abs=1e-9)

        add_weather_observation(report["id"])
        add_crew_entry(report["id"], area1["id"], worker_count=1,
                       work_performed="pour")
        _drive_to_approved(report["id"])

        item = get_work_item(wi["id"])
        assert item["installed_to_date"] == pytest.approx(2.468, abs=1e-9), \
            "round-per-entry-then-sum: 1.234 + 1.234 = 2.468, never 2.469"

    def test_half_up_at_third_decimal(self, api):
        """PRD section 3.8: "the entry's `rounded_quantity` is
        `quantity_installed` rounded half-up to three decimal places, computed
        once at write time and stored." and "A work item's `installed_to_date`
        is the exact sum of `rounded_quantity` over quantity entries that are
        `ACTIVE` and sit on reports in `APPROVED` or `LOCKED` status."

        Design: Difficulty/combinatorial_formula/quantity_rollup_per_entry_rounding_order
        """
        project = make_active_project()
        area = make_work_area(project["id"])
        wi = make_work_item(project["id"], budgeted_quantity=100, unit="LF",
                            unit_cost_cents=1000)
        report = make_report(project["id"])

        qe = add_quantity_entry(report["id"], wi["id"], area["id"], 1.2345)
        assert qe["rounded_quantity"] == pytest.approx(1.235, abs=1e-9), \
            "1.2345 rounds half-up to 1.235 at write time"

        add_weather_observation(report["id"])
        add_crew_entry(report["id"], area["id"], worker_count=1)
        _drive_to_approved(report["id"])

        item = get_work_item(wi["id"])
        assert item["installed_to_date"] == pytest.approx(1.235, abs=1e-9)


class TestSupersede:
    def test_second_entry_for_same_triple_voids_prior(self, api):
        """PRD section 3.8: "the new entry supersedes any existing `ACTIVE`
        entry for the same report, work item, and work area triple: that prior
        row flips to `VOIDED` and its `supersedes_id` is set to point at the
        replacement row."

        Design: Corner/endpoints/quantity_entry_supersede_voids_prior
        """
        project = make_active_project()
        area = make_work_area(project["id"])
        wi = make_work_item(project["id"], budgeted_quantity=100, unit="LF",
                            unit_cost_cents=1000)
        report = make_report(project["id"])

        qe1 = add_quantity_entry(report["id"], wi["id"], area["id"], 10)
        assert qe1["status"] == "ACTIVE"

        qe2 = add_quantity_entry(report["id"], wi["id"], area["id"], 12)
        assert qe2["status"] == "ACTIVE"
        assert qe2["rounded_quantity"] == pytest.approx(12.0, abs=1e-9)

        prior = get_quantity_entry(qe1["id"])
        assert prior["status"] == "VOIDED"
        assert prior["supersedes_id"] == qe2["id"]


class TestApproveRollupCascade:
    def test_approve_cascades_to_work_item_status_and_project_percents(self, api):
        """PRD section 3.8: "At the first level, for each work item referenced
        by `ACTIVE` quantity entries on the approved report, `installed_to_date`
        increases by each entry's `rounded_quantity`. At the second level, every
        work item so touched recomputes its `status` — `NOT_STARTED` at zero,
        `IN_PROGRESS` above zero and below budget, `COMPLETE` at or above
        budget. At the third level, the project's two progress percentages
        recompute."

        Design: Difficulty/transitive_cascade/approve_rollup_cascade_to_project_percent
        """
        project = make_active_project()
        area = make_work_area(project["id"])
        wi_a = make_work_item(project["id"], cost_code="03-100", description="Curb",
                              budgeted_quantity=100, unit="LF", unit_cost_cents=1000)
        wi_b = make_work_item(project["id"], cost_code="03-200", description="Concrete",
                              budgeted_quantity=100, unit="CY", unit_cost_cents=10000)
        report = make_report(project["id"])
        add_quantity_entry(report["id"], wi_a["id"], area["id"], 100)
        add_weather_observation(report["id"])
        add_crew_entry(report["id"], area["id"], work_performed="pour")

        _drive_to_approved(report["id"])

        item_a = get_work_item(wi_a["id"])
        assert item_a["installed_to_date"] == pytest.approx(100.0, abs=1e-9)
        assert item_a["status"] == "COMPLETE", "100 >= budget 100 -> COMPLETE"
        item_b = get_work_item(wi_b["id"])
        assert item_b["status"] == "NOT_STARTED", "untouched item stays NOT_STARTED"

        summary = get_progress_summary(project["id"])
        # units: mean(min(100,100)/100, 0/100) * 100 = 50.00
        assert summary["units_based_pct"] == pytest.approx(50.00, abs=1e-9)
        # cost: (100*1000) / (100*1000 + 100*10000) * 100 = 9.0909.. -> 9.09
        assert summary["cost_weighted_pct"] == pytest.approx(9.09, abs=1e-9)

    def test_partial_install_marks_in_progress(self, api):
        """PRD section 3.8: "every work item so touched recomputes its `status`
        — `NOT_STARTED` at zero, `IN_PROGRESS` above zero and below budget,
        `COMPLETE` at or above budget." and "The cost-weighted variant,
        `percent_complete_cost`, divides the sum over items of
        `installed_to_date` multiplied by `unit_cost_cents` by the sum over
        items of `budgeted_quantity` multiplied by `unit_cost_cents`, expressed
        as a percentage and rounded half-up to two decimals".

        Design: Difficulty/transitive_cascade/approve_rollup_cascade_to_project_percent
        """
        project = make_active_project()
        area = make_work_area(project["id"])
        wi_a = make_work_item(project["id"], cost_code="03-100",
                              budgeted_quantity=100, unit="LF", unit_cost_cents=1000)
        wi_b = make_work_item(project["id"], cost_code="03-200",
                              budgeted_quantity=100, unit="CY", unit_cost_cents=10000)
        report = make_report(project["id"])
        add_quantity_entry(report["id"], wi_a["id"], area["id"], 40)
        add_weather_observation(report["id"])
        add_crew_entry(report["id"], area["id"], worker_count=1)

        _drive_to_approved(report["id"])

        item_a = get_work_item(wi_a["id"])
        assert item_a["installed_to_date"] == pytest.approx(40.0, abs=1e-9)
        assert item_a["status"] == "IN_PROGRESS", "0 < 40 < 100 -> IN_PROGRESS"

        summary = get_progress_summary(project["id"])
        # units: mean(0.40, 0.00) * 100 = 20.00
        assert summary["units_based_pct"] == pytest.approx(20.00, abs=1e-9)
        # cost: 40000 / 1100000 * 100 = 3.6363.. -> 3.64
        assert summary["cost_weighted_pct"] == pytest.approx(3.64, abs=1e-9)


class TestReopenCompensation:
    def test_approve_reopen_reapprove_conserves_installed_to_date(self, api):
        """PRD section 3.8: "Reopening an approved report runs the exact
        compensation: the same entries' stored `rounded_quantity` values are
        subtracted back out of `installed_to_date`, the affected work items
        recompute their status, and the project's percent fields recompute.
        Because rollups sum stored values, the subtraction undoes the approval
        exactly."

        Design: Difficulty/compensating_invariant/approve_reopen_reapproves_conserve_installed_to_date
        """
        project = make_active_project()
        area1 = make_work_area(project["id"])
        area2 = make_work_area(project["id"])
        wi = make_work_item(project["id"], cost_code="03-100", description="Curb",
                            budgeted_quantity=100, unit="LF", unit_cost_cents=1000)
        report = make_report(project["id"])
        add_quantity_entry(report["id"], wi["id"], area1["id"], 1.2344)
        add_quantity_entry(report["id"], wi["id"], area2["id"], 1.2344)
        add_weather_observation(report["id"])
        add_crew_entry(report["id"], area1["id"], worker_count=1,
                       work_performed="pour")

        _drive_to_approved(report["id"])
        assert get_work_item(wi["id"])["installed_to_date"] == pytest.approx(
            2.468, abs=1e-9)

        reopened = validate_success(api_client.reopen_report(
            report["id"], {"reason": "Quantity audit"}, _PM))
        assert reopened["status"] == "UNDER_REVIEW"
        item = get_work_item(wi["id"])
        assert item["installed_to_date"] == pytest.approx(0.0, abs=1e-9), \
            "reopen subtracts exactly what approve added"
        assert item["status"] == "NOT_STARTED"

        validate_success(api_client.approve_report(report["id"], _PM))
        item = get_work_item(wi["id"])
        assert item["installed_to_date"] == pytest.approx(2.468, abs=1e-9), \
            "re-approve re-adds the same stored values — no drift, no doubling"

    def test_reopen_restores_zero_progress_percents(self, api):
        """PRD section 3.8: "Reopening an approved report runs the exact
        compensation: the same entries' stored `rounded_quantity` values are
        subtracted back out of `installed_to_date`, the affected work items
        recompute their status, and the project's percent fields recompute."

        Design: Difficulty/compensating_invariant/approve_reopen_reapproves_conserve_installed_to_date
        """
        project = make_active_project()
        area = make_work_area(project["id"])
        wi = make_work_item(project["id"], budgeted_quantity=100, unit="LF",
                            unit_cost_cents=1000)
        report = make_report(project["id"])
        add_quantity_entry(report["id"], wi["id"], area["id"], 25)
        add_weather_observation(report["id"])
        add_crew_entry(report["id"], area["id"], worker_count=1)

        _drive_to_approved(report["id"])
        summary = get_progress_summary(project["id"])
        assert summary["units_based_pct"] == pytest.approx(25.00, abs=1e-9)
        assert summary["cost_weighted_pct"] == pytest.approx(25.00, abs=1e-9)

        validate_success(api_client.reopen_report(report["id"],
                                                  {"reason": "audit"}, _PM))
        after = get_progress_summary(project["id"])
        assert after["units_based_pct"] == pytest.approx(0.00, abs=1e-9)
        assert after["cost_weighted_pct"] == pytest.approx(0.00, abs=1e-9)
        assert get_work_item(wi["id"])["status"] == "NOT_STARTED"


class TestDualProgressVariants:
    def test_units_and_cost_variants_diverge_on_same_rollup(self, api):
        """PRD section 3.8: "The units-based variant, surfaced as
        `percent_complete_units`, is the unweighted mean across all of the
        project's work items — regardless of status — of each item's
        `installed_to_date` capped at its `budgeted_quantity` and divided by
        that budget, expressed as a percentage and rounded half-up to two
        decimals". "The cost-weighted variant, `percent_complete_cost`, divides
        the sum over items of `installed_to_date` multiplied by
        `unit_cost_cents` by the sum over items of `budgeted_quantity`
        multiplied by `unit_cost_cents`, expressed as a percentage and rounded
        half-up to two decimals; it is deliberately uncapped".

        Design: Difficulty/dual_variant_calc/progress_percent_units_vs_cost_weighted
        """
        project = make_active_project(scheduled_shift_hours=8)
        area = make_work_area(project["id"])
        wi_a = make_work_item(project["id"], cost_code="03-100", description="Curb",
                              budgeted_quantity=100, unit="LF", unit_cost_cents=1000)
        wi_b = make_work_item(project["id"], cost_code="03-200", description="Concrete",
                              budgeted_quantity=100, unit="CY", unit_cost_cents=10000)
        report = make_report(project["id"])
        add_quantity_entry(report["id"], wi_a["id"], area["id"], 100)
        add_quantity_entry(report["id"], wi_b["id"], area["id"], 50)
        add_weather_observation(report["id"])
        add_crew_entry(report["id"], area["id"], work_performed="framing")

        _drive_to_approved(report["id"])

        summary = get_progress_summary(project["id"])
        # units: mean(100/100 capped, 50/100) * 100 = 75.00
        assert summary["units_based_pct"] == pytest.approx(75.00, abs=1e-9)
        # cost: (100000 + 500000) / (100000 + 1000000) * 100 = 54.5454.. -> 54.55
        assert summary["cost_weighted_pct"] == pytest.approx(54.55, abs=1e-9)
        assert summary["units_based_pct"] != summary["cost_weighted_pct"], \
            "same rollup data, two valid algorithms, different results"
        assert summary["work_item_count"] == 2
        assert summary["project_id"] == project["id"]

    def test_project_read_exposes_both_progress_fields(self, api):
        """PRD section 3.1: "the project read exposes the two computed progress
        figures `percent_complete_units` and `percent_complete_cost`". PRD
        section 3.8: "Both variants are exposed side by side — as
        `units_based_pct` and `cost_weighted_pct`, alongside `project_id` and a
        `work_item_count` — on the project's progress summary."

        Design: Difficulty/dual_variant_calc/progress_percent_units_vs_cost_weighted
        """
        project = make_active_project(scheduled_shift_hours=8)
        area = make_work_area(project["id"])
        wi_a = make_work_item(project["id"], cost_code="03-100",
                              budgeted_quantity=100, unit="LF", unit_cost_cents=1000)
        wi_b = make_work_item(project["id"], cost_code="03-200",
                              budgeted_quantity=100, unit="CY", unit_cost_cents=10000)
        report = make_report(project["id"])
        add_quantity_entry(report["id"], wi_a["id"], area["id"], 100)
        add_quantity_entry(report["id"], wi_b["id"], area["id"], 50)
        add_weather_observation(report["id"])
        add_crew_entry(report["id"], area["id"], work_performed="framing")

        _drive_to_approved(report["id"])

        proj = get_project(project["id"])
        assert proj["percent_complete_units"] == pytest.approx(75.00, abs=1e-9)
        assert proj["percent_complete_cost"] == pytest.approx(54.55, abs=1e-9)
