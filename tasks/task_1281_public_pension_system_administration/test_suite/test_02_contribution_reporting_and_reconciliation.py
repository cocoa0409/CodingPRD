"""Employer contribution reporting, reconciliation, and FAS/service accrual."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_line,
    assert_contribution_line,
    assert_contribution_report,
    create_member,
    create_report,
    finalize_report,
    make_employer_clerk_headers,
    review_line,
    setup_fund_and_employer,
    setup_vested_member,
    six_year_line_specs,
    submit_report,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import ANALYST


class TestFinalizeGates:
    def test_finalize_draft_report_returns_invalid_state(self, api):
        """PRD §3.3: "The analyst finalizes a `SUBMITTED` report."
        PRD §2.8: "6. **State gates** — generic invalid from-state
        (`ERR_INVALID_STATE`), member lifecycle gates (`ERR_MEMBER_NOT_ACTIVE`,
        `ERR_MEMBER_DECEASED`), and resource-specific status gates
        (`ERR_PLAN_NOT_ACTIVE`, `ERR_BENEFIT_NOT_ACTIVE`,
        `ERR_BENEFIT_NOT_TERMINATED`)."

        Design: Corner/state_machines/finalize_draft_report_returns_invalid_state
        """
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Draft Fiona",
                               date_of_birth="1990-01-01",
                               hire_date="2020-01-01")
        report = create_report(employer["id"], "2023-01-01", "2024-01-01",
                               480_000)
        add_line(report["id"], employer["id"], member["id"], 2023,
                 6_000_000, 480_000)
        res = api.finalize_contribution_report(report["id"], ANALYST)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_contribution_report(report["id"],
                                                             ANALYST), 200)
        assert after["status"] == "DRAFT"

    def test_finalize_with_pending_lines_returns_lines_pending(self, api):
        """PRD §3.3: "If any line is still `PENDING`, the finalize is rejected
        with `ERR_LINES_PENDING` (HTTP 422) and the report's status does not
        change."

        Design: Corner/validations/finalize_with_pending_lines_returns_lines_pending
        """
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Pending Pete",
                               date_of_birth="1970-01-01",
                               hire_date="2018-01-01")
        report = create_report(employer["id"], "2023-01-01", "2024-01-01",
                               480_000)
        add_line(report["id"], employer["id"], member["id"], 2023,
                 6_000_000, 480_000)
        submit_report(report["id"], employer["id"])
        res = api.finalize_contribution_report(report["id"], ANALYST)
        validate_error(res, ApiErrorId.ERR_LINES_PENDING)
        after = validate_success(api.get_contribution_report(report["id"],
                                                             ANALYST), 200)
        assert after["status"] == "SUBMITTED"

    def test_finalize_unexplained_variance_returns_reconciliation_error(self, api):
        """PRD §3.3: "If no line is rejected but the recomputed
        `accepted_total_cents` does not equal `declared_total_cents`, the
        finalize is rejected with `ERR_RECONCILIATION_VARIANCE` (HTTP 422):
        an unexplained variance with nothing to attribute it to."

        Design: Corner/validations/finalize_unexplained_variance_returns_reconciliation_error
        """
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Variance Vera",
                               date_of_birth="1970-01-01",
                               hire_date="2018-01-01")
        report = create_report(employer["id"], "2023-01-01", "2024-01-01",
                               480_000)
        line = add_line(report["id"], employer["id"], member["id"], 2023,
                        5_000_000, 400_000)
        submit_report(report["id"], employer["id"])
        review_line(report["id"], line["id"], "ACCEPT")
        res = api.finalize_contribution_report(report["id"], ANALYST)
        validate_error(res, ApiErrorId.ERR_RECONCILIATION_VARIANCE)
        after = validate_success(api.get_contribution_report(report["id"],
                                                             ANALYST), 200)
        assert after["status"] == "SUBMITTED"


class TestLineCreationConstraints:
    def test_duplicate_line_same_member_fiscal_year_rejected(self, api):
        """PRD §3.3: "Two structural constraints are enforced at line
        creation: a line's `fiscal_year` must fall inside the report's period
        (a fiscal year outside the half-open period interval is
        `ERR_INVALID_REQUEST`), and a report may contain at most one line per
        member per fiscal year — a duplicate is `ERR_DUPLICATE_LINE_PERIOD`
        (HTTP 409)."

        Design: Corner/validations/duplicate_line_same_member_fiscal_year_returns_error
        """
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Dupe Doris",
                               date_of_birth="1970-01-01",
                               hire_date="2018-01-01")
        report = create_report(employer["id"], "2023-01-01", "2024-01-01",
                               960_000)
        add_line(report["id"], employer["id"], member["id"], 2023,
                 6_000_000, 480_000)
        res = api.create_contribution_line(
            report["id"],
            {"member_id": member["id"], "fiscal_year": 2023,
             "period_salary_cents": 6_000_000,
             "contribution_amount_cents": 480_000},
            make_employer_clerk_headers(employer["id"]))
        validate_error(res, ApiErrorId.ERR_DUPLICATE_LINE_PERIOD)
        _lines, meta = validate_paginated(
            api.list_contribution_lines(report["id"], ANALYST))
        assert meta["total_count"] == 1

    def test_line_fiscal_year_outside_report_period_rejected(self, api):
        """PRD §3.3: "a line's `fiscal_year` must fall inside the report's
        period (a fiscal year outside the half-open period interval is
        `ERR_INVALID_REQUEST`)"

        Design: Corner/validations/line_fiscal_year_outside_report_period_returns_invalid_request
        """
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Outside Oscar",
                               date_of_birth="1970-01-01",
                               hire_date="2018-01-01")
        report = create_report(employer["id"], "2023-01-01", "2024-01-01",
                               480_000)
        res = api.create_contribution_line(
            report["id"],
            {"member_id": member["id"], "fiscal_year": 2025,
             "period_salary_cents": 6_000_000,
             "contribution_amount_cents": 480_000},
            make_employer_clerk_headers(employer["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
        _lines, meta = validate_paginated(
            api.list_contribution_lines(report["id"], ANALYST))
        assert meta["total_count"] == 0


def _setup_variance_report(api):
    """Report 2022-01-01..2024-01-01, declared 920,000; FY2022 line 440,000
    ACCEPTED, FY2023 line 480,000 REJECTED; finalize lands in VARIANCE."""
    fund, employer = setup_fund_and_employer()
    member = create_member(employer["id"], full_name="Variance Vic")
    report = create_report(employer["id"], "2022-01-01", "2024-01-01", 920_000)
    l22 = add_line(report["id"], employer["id"], member["id"], 2022,
                   5_500_000, 440_000)
    l23 = add_line(report["id"], employer["id"], member["id"], 2023,
                   6_000_000, 480_000)
    submit_report(report["id"], employer["id"])
    review_line(report["id"], l22["id"], "ACCEPT")
    review_line(report["id"], l23["id"], "REJECT", "salary unverified")
    return fund, employer, member, report, l22, l23


class TestVarianceBubbleUp:
    def test_finalize_with_rejected_line_moves_report_to_variance(self, api):
        """PRD §3.3: "If every line has been reviewed and at least one line is
        `REJECTED`, the report moves to `VARIANCE` — the fund is signaling
        that the employer's declared total cannot be accepted as submitted."

        Design: Difficulty/transitive_cascade/line_review_bubble_up_reconciles_variance_report
        """
        _f, _e, _m, report, _l22, _l23 = _setup_variance_report(api)
        finalized = finalize_report(report["id"])
        assert finalized["status"] == "VARIANCE"
        assert finalized["accepted_total_cents"] == 440_000, (
            f"only the ACCEPTED line counts toward accepted_total_cents, "
            f"got {finalized['accepted_total_cents']}")

    def test_rereview_accept_bubbles_report_to_reconciled(self, api):
        """PRD §3.3: "When a re-review accepts the last outstanding rejected
        line — leaving no line in `PENDING` or `REJECTED` — and the accepted
        total then equals the declared total, the report bubbles up to
        `RECONCILED` automatically as a side effect of the line review; no
        second finalize call is needed."

        Design: Difficulty/transitive_cascade/line_review_bubble_up_reconciles_variance_report
        """
        _f, _e, _m, report, _l22, l23 = _setup_variance_report(api)
        assert finalize_report(report["id"])["status"] == "VARIANCE"
        line_after = review_line(report["id"], l23["id"], "ACCEPT",
                                 "verification received")
        assert line_after["status"] == "ACCEPTED"
        report_after = validate_success(
            api.get_contribution_report(report["id"], ANALYST), 200)
        assert report_after["accepted_total_cents"] == 920_000
        assert report_after["status"] == "RECONCILED", (
            "report must bubble up VARIANCE -> RECONCILED from the line "
            f"review itself, got {report_after['status']}")


class TestServiceCreditConservation:
    def test_rejected_line_never_counts_toward_service(self, api):
        """PRD §3.2: "Lines in `PENDING` or `REJECTED` never count; purchases
        still on a payment plan never count."

        Design: Difficulty/compensating_invariant/service_credit_conservation_on_line_review
        """
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Service Sam")
        report = create_report(employer["id"], "2022-01-01", "2024-01-01",
                               920_000)
        l22 = add_line(report["id"], employer["id"], member["id"], 2022,
                       5_500_000, 440_000)
        l23 = add_line(report["id"], employer["id"], member["id"], 2023,
                       6_000_000, 480_000)
        submit_report(report["id"], employer["id"])
        review_line(report["id"], l22["id"], "ACCEPT")
        after_accept = validate_success(api.get_member(member["id"], ANALYST),
                                        200)
        assert after_accept["total_service_years"] == pytest.approx(1.0), (
            f"one ACCEPTED 12-month line must yield 1.0 year, "
            f"got {after_accept['total_service_years']}")
        review_line(report["id"], l23["id"], "REJECT", "duplicate suspected")
        after_reject = validate_success(api.get_member(member["id"], ANALYST),
                                        200)
        assert after_reject["total_service_years"] == pytest.approx(1.0), (
            "a PENDING line moving to REJECTED must not change service — "
            f"PENDING never counted, got {after_reject['total_service_years']}")

    def test_rereview_accept_restores_service_exactly(self, api):
        """PRD §3.2: "A member's `total_service_years` is the rounded half-up
        sum, to two decimal places, of all `service_months` over that member's
        contribution lines in `ACCEPTED` status divided by twelve, plus the
        sum of `years_purchased` over the member's service purchases in
        `COMPLETED` status."
        PRD §2.9: "Each time a contribution line is accepted or rejected, or a
        service purchase completes, the member's `total_service_years` and
        `current_annual_salary_cents` are recomputed in full from the
        underlying source records, per the formulas of §3.2."

        Design: Difficulty/compensating_invariant/service_credit_conservation_on_line_review
        """
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Service Sam")
        report = create_report(employer["id"], "2022-01-01", "2024-01-01",
                               920_000)
        l22 = add_line(report["id"], employer["id"], member["id"], 2022,
                       5_500_000, 440_000)
        l23 = add_line(report["id"], employer["id"], member["id"], 2023,
                       6_000_000, 480_000)
        submit_report(report["id"], employer["id"])
        review_line(report["id"], l22["id"], "ACCEPT")
        review_line(report["id"], l23["id"], "REJECT")
        assert finalize_report(report["id"])["status"] == "VARIANCE"
        review_line(report["id"], l23["id"], "ACCEPT", "verified")
        member_after = validate_success(api.get_member(member["id"], ANALYST),
                                        200)
        assert member_after["total_service_years"] == pytest.approx(2.0), (
            "reject-then-accept must leave service a pure function of final "
            f"line statuses, got {member_after['total_service_years']}")
        report_after = validate_success(
            api.get_contribution_report(report["id"], ANALYST), 200)
        assert report_after["status"] == "RECONCILED"


class TestReportPeriodOverlap:
    def test_adjacent_report_period_allowed(self, api):
        """PRD §3.3: "The period is a half-open interval: it includes
        `period_start` and runs up to but does not include `period_end`. Two
        reports of the same employer may not overlap, though adjacency is
        allowed — a new report whose `period_start` equals the prior report's
        `period_end` is legal."

        Design: Difficulty/resource_temporal_overlap/report_period_half_open_adjacency_allowed
        """
        fund, employer = setup_fund_and_employer()
        create_report(employer["id"], "2023-01-01", "2024-01-01", 480_000)
        adjacent = validate_success(api.create_contribution_report(
            employer["id"],
            {"period_start": "2024-01-01", "period_end": "2025-01-01",
             "declared_total_cents": 500_000},
            make_employer_clerk_headers(employer["id"])), 201)
        assert_contribution_report(adjacent)
        assert adjacent["status"] == "DRAFT", (
            "adjacent period (start == prior end) must be accepted under "
            "half-open semantics")

    def test_overlapping_report_period_rejected(self, api):
        """PRD §3.3: "Two reports of the same employer may not overlap, though
        adjacency is allowed — a new report whose `period_start` equals the
        prior report's `period_end` is legal. A violating report create is
        rejected with `ERR_REPORT_PERIOD_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/report_period_half_open_adjacency_allowed
        """
        fund, employer = setup_fund_and_employer()
        create_report(employer["id"], "2023-01-01", "2024-01-01", 480_000)
        create_report(employer["id"], "2024-01-01", "2025-01-01", 500_000)
        res = api.create_contribution_report(
            employer["id"],
            {"period_start": "2023-06-01", "period_end": "2024-06-01",
             "declared_total_cents": 240_000},
            make_employer_clerk_headers(employer["id"]))
        validate_error(res, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)
        _reports, meta = validate_paginated(
            api.list_employer_contribution_reports(employer["id"], ANALYST))
        assert meta["total_count"] == 2


class TestFinalAverageSalary:
    def test_fas_uses_three_most_recent_accepted_fiscal_years(self, api):
        """PRD §3.5: "First, the final average salary: take the set of fiscal
        years having at least one included line, rank them by `fiscal_year`
        descending, and take the top 3 years; `fas_annual_cents` is the sum of
        the `period_salary_cents` of the included lines in those years divided
        by the number of distinct fiscal years taken — if fewer than three
        included years exist, divide by however many exist — rounded half-up
        to whole cents."
        PRD §3.5: "Third, the multiplier, tiered by service: 0.025 when
        service is at least 25 years, else 0.022 when at least 20, else 0.020
        when at least 10, else 0.017."

        Design: Corner/calculations/fas_uses_three_most_recent_accepted_fiscal_years
        """
        ctx = setup_vested_member(full_name="FAS Fred")
        estimate = validate_success(api.get_benefit_estimate(
            ctx["member"]["id"], ANALYST, params={"variant": "FINAL"}), 200)
        assert estimate["fas_cents"] == 5_500_000, (
            "FAS must average only FY2021-2023: (5000000+5500000+6000000)/3, "
            f"got {estimate['fas_cents']}")
        assert estimate["service_years"] == pytest.approx(6.0)
        assert estimate["multiplier"] == pytest.approx(0.017)
        assert estimate["monthly_single_life_cents"] == 46_750
        assert estimate["variant"] == "FINAL"

    def test_fas_excludes_rejected_lines_from_input_set(self, api):
        """PRD §3.5: "The PROVISIONAL variant includes `PENDING` contribution
        lines — salary and service months — projecting not-yet-reconciled
        service into the totals; the FINAL variant counts only `ACCEPTED`
        lines, so identical data with one unreviewed pending line yields a
        lower estimate under FINAL than under PROVISIONAL."

        Design: Corner/calculations/fas_excludes_rejected_lines_from_input_set
        """
        fund, employer = setup_fund_and_employer()
        member = create_member(employer["id"], full_name="Rejected Rita")
        specs = six_year_line_specs(member["id"])
        declared = sum(round(s["salary_cents"] * 0.08) for s in specs)
        report = create_report(employer["id"], "2018-01-01", "2024-01-01",
                               declared)
        lines = [add_line(report["id"], employer["id"], member["id"],
                          s["fiscal_year"], s["salary_cents"])
                 for s in specs]
        submit_report(report["id"], employer["id"])
        for line in lines[:-1]:
            review_line(report["id"], line["id"], "ACCEPT")
        review_line(report["id"], lines[-1]["id"], "REJECT")  # FY2023 out
        finalized = finalize_report(report["id"])
        assert finalized["status"] == "VARIANCE"

        estimate = validate_success(api.get_benefit_estimate(
            member["id"], ANALYST, params={"variant": "FINAL"}), 200)
        assert estimate["fas_cents"] == 5_000_000, (
            "REJECTED FY2023 must drop out: FAS falls back to FY2020-2022 "
            f"(4500000+5000000+5500000)/3, got {estimate['fas_cents']}")
        assert estimate["service_years"] == pytest.approx(5.0)
        assert estimate["monthly_single_life_cents"] == 35_417
