"""Boundary behaviour of the APC fund auto-freeze threshold and of an empty
reporting population.

Both scenarios sit exactly on a documented boundary: the ninety-eight percent
auto-freeze test on an APC fund, and the annual spend report for a fiscal year in
which no fund, no allocation line and no paid invoice exists.
"""

import pytest

from test_helpers import (
    create_decision_payload,
    decide_request,
    open_fund,
    open_fund_request,
    record_article,
    record_grant,
    register_author,
    register_funder,
    register_journal,
    register_publisher,
    run_eligibility_check,
    set_clock,
    start_review,
    validate_paginated,
    validate_success,
)


# --------------------------------------------------------------------------- #
# private preambles
# --------------------------------------------------------------------------- #
def _setup_threshold_pair_under_review() -> dict:
    """Two independent fund-route articles whose approvals will land one fund
    exactly on the ninety-eight percent threshold and the other one cent below it.

    Each fund admits exactly one of the two authors through its
    ``eligible_affiliation_statuses`` list, so the two waterfalls never interact.
    """
    set_clock("2026-08-05T00:00:00Z")
    publisher = register_publisher(
        publisher_code="HALDEN", name="Halden Open Science", country_code="NO"
    )
    journal_at_threshold = register_journal(
        publisher["id"],
        issn="2515-0847",
        title="Halden Journal of Threshold Studies",
        oa_model="FULLY_OA",
        list_apc_cents=196000,
        required_embargo_months=12,
    )
    journal_below_threshold = register_journal(
        publisher["id"],
        issn="2397-3374",
        title="Halden Journal of Boundary Metabolism",
        oa_model="FULLY_OA",
        list_apc_cents=195999,
        required_embargo_months=12,
    )
    author_at_threshold = register_author(
        full_name="Ada Kerr",
        email="ada.kerr@uni.example",
        orcid="0000-0006-5555-6666",
        department_code="MET",
        affiliation_status="ELIGIBLE_FACULTY",
        appointment_from="2024-01-01",
        appointment_until="2028-12-31",
        annual_cap_cents=500000,
    )
    author_below_threshold = register_author(
        full_name="Ben Oyelaran",
        email="ben.oyelaran@uni.example",
        orcid="0000-0006-7777-8888",
        department_code="MET",
        affiliation_status="ELIGIBLE_POSTDOC",
        appointment_from="2024-01-01",
        appointment_until="2028-12-31",
        annual_cap_cents=500000,
    )
    funder = register_funder(
        name="National Research Council",
        funder_code="NRC",
        mandate_type="GOLD_OA",
        max_embargo_months=6,
        deposit_deadline_days=90,
        license_required="CC_BY",
        apc_allowable=True,
    )
    grant_at_threshold = record_grant(
        funder["id"],
        author_at_threshold["id"],
        grant_number="NRC-2026-401",
        award_from="2026-01-01",
        award_until="2027-12-31",
        apc_budget_cents=900000,
    )
    grant_below_threshold = record_grant(
        funder["id"],
        author_below_threshold["id"],
        grant_number="NRC-2026-402",
        award_from="2026-01-01",
        award_until="2027-12-31",
        apc_budget_cents=900000,
    )
    fund_at_threshold = open_fund(
        fund_code="OA-FACULTY-2027",
        fiscal_year=2027,
        period_from="2026-07-01",
        period_to="2027-06-30",
        total_budget_cents=200000,
        priority_rank=1,
        eligible_affiliation_statuses=["ELIGIBLE_FACULTY"],
        per_article_cap_cents=196000,
    )
    fund_below_threshold = open_fund(
        fund_code="OA-POSTDOC-2027",
        fiscal_year=2027,
        period_from="2026-07-01",
        period_to="2027-06-30",
        total_budget_cents=200000,
        priority_rank=2,
        eligible_affiliation_statuses=["ELIGIBLE_POSTDOC"],
        per_article_cap_cents=196000,
    )
    article_at_threshold = record_article(
        journal_at_threshold["id"],
        author_at_threshold["id"],
        grant_id=grant_at_threshold["id"],
        manuscript_title="Exactly at the freeze threshold",
        accepted_on="2026-08-05",
    )
    article_below_threshold = record_article(
        journal_below_threshold["id"],
        author_below_threshold["id"],
        grant_id=grant_below_threshold["id"],
        manuscript_title="One cent below the freeze threshold",
        accepted_on="2026-08-05",
    )
    determination_at_threshold = run_eligibility_check(
        article_at_threshold["id"], basis="PROVISIONAL"
    )
    determination_below_threshold = run_eligibility_check(
        article_below_threshold["id"], basis="PROVISIONAL"
    )
    request_at_threshold = open_fund_request(
        article_at_threshold["id"],
        author_at_threshold["id"],
        196000,
        justification="Threshold-exact request.",
    )
    request_below_threshold = open_fund_request(
        article_below_threshold["id"],
        author_below_threshold["id"],
        195999,
        justification="One cent below the threshold.",
    )
    start_review(request_at_threshold["id"])
    start_review(request_below_threshold["id"])
    return {
        "fund_at_threshold": fund_at_threshold,
        "fund_below_threshold": fund_below_threshold,
        "article_at_threshold": article_at_threshold,
        "article_below_threshold": article_below_threshold,
        "determination_at_threshold": determination_at_threshold,
        "determination_below_threshold": determination_below_threshold,
        "request_at_threshold": request_at_threshold,
        "request_below_threshold": request_below_threshold,
    }


def _setup_encumbered_fiscal_year_2027() -> dict:
    """A single fiscal-year 2027 fund carrying one ENCUMBERED allocation line of
    300000 cents, with no publisher invoice anywhere in the database."""
    set_clock("2026-08-05T00:00:00Z")
    publisher = register_publisher(
        publisher_code="HALDEN", name="Halden Open Science", country_code="NO"
    )
    journal = register_journal(
        publisher["id"],
        issn="2515-0847",
        title="Halden Journal of Open Metabolism",
        oa_model="FULLY_OA",
        list_apc_cents=300000,
        required_embargo_months=12,
    )
    author = register_author(
        full_name="Tomas Berg",
        email="tomas.berg@uni.example",
        orcid="0000-0001-5109-3700",
        department_code="MET",
        affiliation_status="ELIGIBLE_FACULTY",
        appointment_from="2024-01-01",
        appointment_until="2028-12-31",
        annual_cap_cents=500000,
    )
    funder = register_funder(
        name="National Research Council",
        funder_code="NRC",
        mandate_type="GOLD_OA",
        max_embargo_months=6,
        deposit_deadline_days=90,
        license_required="CC_BY",
        apc_allowable=True,
    )
    grant = record_grant(
        funder["id"],
        author["id"],
        grant_number="NRC-2026-118",
        award_from="2026-01-01",
        award_until="2027-12-31",
        apc_budget_cents=900000,
    )
    fund = open_fund(
        fund_code="OA-CENTRAL-2027",
        fiscal_year=2027,
        period_from="2026-07-01",
        period_to="2027-06-30",
        total_budget_cents=1000000,
        priority_rank=1,
        eligible_affiliation_statuses=["ELIGIBLE_FACULTY"],
        per_article_cap_cents=300000,
    )
    article = record_article(
        journal["id"],
        author["id"],
        grant_id=grant["id"],
        manuscript_title="Reporting on an empty fiscal year",
        accepted_on="2026-08-05",
    )
    run_eligibility_check(article["id"], basis="PROVISIONAL")
    request = open_fund_request(
        article["id"], author["id"], 300000, justification="Gold OA fee."
    )
    start_review(request["id"])
    decide_request(request["id"], "APPROVE")
    return {"publisher": publisher, "fund": fund, "article": article, "request": request}


# --------------------------------------------------------------------------- #
# the ninety-eight percent auto-freeze threshold
# --------------------------------------------------------------------------- #
def test_apc_fund_auto_freezes_when_committed_reaches_ninety_eight_percent_of_budget(
    api, fund_manager_headers
):
    """An encumbrance that lands committed_cents on exactly 196000 against a
    200000 budget trips the inclusive auto-freeze test.

    PRD §3.3: "The system also freezes funds by itself."
    PRD §3.3: "Whenever an allocation is encumbered or disbursed against a fund, the fund is re-examined: if `committed_cents` plus `spent_cents` reaches or exceeds ninety-eight percent of `total_budget_cents` — computed as `total_budget_cents` multiplied by 0.98 and rounded half up to whole cents — the fund moves from `OPEN` to `FROZEN` with `freeze_reason` set to the literal value `AUTO_THRESHOLD`."
    PRD §2.10: "`APCFund.committed_cents` is the sum of `amount_cents` over that fund's `ENCUMBERED` allocation lines; `APCFund.spent_cents` is the same sum over its `DISBURSED` lines; `APCFund.available_cents` is `total_budget_cents` less `committed_cents` less `spent_cents`."
    PRD §3.4: "It qualifies when, and only when, all four of these hold: the article names a grant; that grant's `status` is `ACTIVE`; the grant's funder has a `mandate_type` of either `GOLD_OA` or `IMMEDIATE_CC_BY`; the funder's `apc_allowable` is true; and the journal's `oa_model` is `FULLY_OA`."
    PRD §3.4: "If it qualifies, the `route` is `FUND_APC`, `covered_amount_cents` is 0, `author_share_cents` is the whole `list_base_cents`, `eligible_request_cents` is likewise the whole `list_base_cents`, and `determination_reason` is `NO_COVERAGE_FUND_ELIGIBLE`."
    PRD §3.5: "Otherwise the sequence counter increases by one and an allocation line is written carrying the `fund_request_id`, the `fund_id`, the `amount_cents` taken, the `sequence_index` from the counter, and a `status` of `ENCUMBERED` with no `released_reason`."
    PRD §3.5: "The article's funding dimension moves from `FUNDING_REQUESTED` to `FUNDED` when the request was fully funded and to `PARTIALLY_FUNDED` when it was not."
    Design: Difficulty/boundary_precision_check/fund_auto_freeze_at_exactly_ninety_eight_percent_vs_one_cent_below
    """
    scenario = _setup_threshold_pair_under_review()

    assert scenario["determination_at_threshold"]["eligible_request_cents"] == 196000, (
        "a FUND_APC determination on a 196000 cent fully open access journal must make "
        "the whole list base requestable"
    )

    decided = validate_success(
        api.decide_fund_request(
            scenario["request_at_threshold"]["id"],
            create_decision_payload("APPROVE"),
            fund_manager_headers,
        )
    )
    validate_success(
        api.decide_fund_request(
            scenario["request_below_threshold"]["id"],
            create_decision_payload("APPROVE"),
            fund_manager_headers,
        )
    )

    assert decided["approved_cents"] == 196000, (
        f"the waterfall should approve the whole 196000 cent ceiling, "
        f"got {decided['approved_cents']}"
    )

    fund = validate_success(
        api.get_apc_fund(scenario["fund_at_threshold"]["id"], fund_manager_headers)
    )
    assert fund["committed_cents"] == 196000, (
        f"committed_cents should be 196000, got {fund['committed_cents']}"
    )
    assert fund["spent_cents"] == 0, (
        f"nothing has been disbursed, so spent_cents should be 0, got {fund['spent_cents']}"
    )
    assert fund["available_cents"] == 4000, (
        f"available_cents should be 200000 - 196000 - 0 = 4000, got {fund['available_cents']}"
    )
    assert fund["status"] == "FROZEN", (
        f"committed 196000 reaches 0.98 * 200000 = 196000, so the fund must be FROZEN, "
        f"got {fund['status']}"
    )
    assert fund["freeze_reason"] == "AUTO_THRESHOLD", (
        f"an automatic freeze records the literal reason AUTO_THRESHOLD, "
        f"got {fund['freeze_reason']!r}"
    )

    article = validate_success(
        api.get_article(scenario["article_at_threshold"]["id"], fund_manager_headers)
    )
    assert article["funding_status"] == "FUNDED", (
        f"a fully funded request moves the article to FUNDED, got {article['funding_status']}"
    )

    rows, _meta = validate_paginated(
        api.list_fund_allocations(
            scenario["fund_at_threshold"]["id"], fund_manager_headers
        )
    )
    assert len(rows) == 1, f"exactly one allocation line should exist, got {len(rows)}"
    assert rows[0]["amount_cents"] == 196000, (
        f"the single line should carry 196000 cents, got {rows[0]['amount_cents']}"
    )
    assert rows[0]["sequence_index"] == 1, (
        f"the first line drawn carries sequence_index 1, got {rows[0]['sequence_index']}"
    )
    assert rows[0]["status"] == "ENCUMBERED", (
        f"a newly written allocation line is ENCUMBERED, got {rows[0]['status']}"
    )


def test_apc_fund_stays_open_when_committed_is_one_cent_below_the_freeze_threshold(
    api, fund_manager_headers
):
    """An encumbrance of 195999 cents against the identical 200000 budget misses the
    196000 threshold by one cent, so the fund keeps taking work.

    PRD §3.3: "Whenever an allocation is encumbered or disbursed against a fund, the fund is re-examined: if `committed_cents` plus `spent_cents` reaches or exceeds ninety-eight percent of `total_budget_cents` — computed as `total_budget_cents` multiplied by 0.98 and rounded half up to whole cents — the fund moves from `OPEN` to `FROZEN` with `freeze_reason` set to the literal value `AUTO_THRESHOLD`."
    PRD §3.3: "On opening, `status` is `OPEN`, `committed_cents` and `spent_cents` are zero, `available_cents` equals `total_budget_cents`, and `freeze_reason` is absent."
    PRD §2.10: "`APCFund.committed_cents` is the sum of `amount_cents` over that fund's `ENCUMBERED` allocation lines; `APCFund.spent_cents` is the same sum over its `DISBURSED` lines; `APCFund.available_cents` is `total_budget_cents` less `committed_cents` less `spent_cents`."
    PRD §3.4: "If it qualifies, the `route` is `FUND_APC`, `covered_amount_cents` is 0, `author_share_cents` is the whole `list_base_cents`, `eligible_request_cents` is likewise the whole `list_base_cents`, and `determination_reason` is `NO_COVERAGE_FUND_ELIGIBLE`."
    PRD §3.5: "Otherwise the sequence counter increases by one and an allocation line is written carrying the `fund_request_id`, the `fund_id`, the `amount_cents` taken, the `sequence_index` from the counter, and a `status` of `ENCUMBERED` with no `released_reason`."
    PRD §3.5: "The article's funding dimension moves from `FUNDING_REQUESTED` to `FUNDED` when the request was fully funded and to `PARTIALLY_FUNDED` when it was not."
    Design: Difficulty/boundary_precision_check/fund_auto_freeze_at_exactly_ninety_eight_percent_vs_one_cent_below
    """
    scenario = _setup_threshold_pair_under_review()

    assert scenario["determination_below_threshold"]["eligible_request_cents"] == 195999, (
        "a FUND_APC determination on a 195999 cent fully open access journal must make "
        "the whole list base requestable"
    )

    validate_success(
        api.decide_fund_request(
            scenario["request_at_threshold"]["id"],
            create_decision_payload("APPROVE"),
            fund_manager_headers,
        )
    )
    decided = validate_success(
        api.decide_fund_request(
            scenario["request_below_threshold"]["id"],
            create_decision_payload("APPROVE"),
            fund_manager_headers,
        )
    )

    assert decided["approved_cents"] == 195999, (
        f"the waterfall should approve the whole 195999 cent ceiling, "
        f"got {decided['approved_cents']}"
    )

    fund = validate_success(
        api.get_apc_fund(scenario["fund_below_threshold"]["id"], fund_manager_headers)
    )
    assert fund["committed_cents"] == 195999, (
        f"committed_cents should be 195999, got {fund['committed_cents']}"
    )
    assert fund["available_cents"] == 4001, (
        f"available_cents should be 200000 - 195999 - 0 = 4001, got {fund['available_cents']}"
    )
    assert fund["status"] == "OPEN", (
        f"committed 195999 is one cent below 0.98 * 200000 = 196000, so the fund must "
        f"stay OPEN, got {fund['status']}"
    )
    assert fund.get("freeze_reason") is None, (
        f"a fund that was never frozen carries no freeze_reason, "
        f"got {fund.get('freeze_reason')!r}"
    )

    article = validate_success(
        api.get_article(scenario["article_below_threshold"]["id"], fund_manager_headers)
    )
    assert article["funding_status"] == "FUNDED", (
        f"a fully funded request moves the article to FUNDED, got {article['funding_status']}"
    )

    rows, _meta = validate_paginated(
        api.list_fund_allocations(
            scenario["fund_below_threshold"]["id"], fund_manager_headers
        )
    )
    assert len(rows) == 1, f"exactly one allocation line should exist, got {len(rows)}"
    assert rows[0]["amount_cents"] == 195999, (
        f"the single line should carry 195999 cents, got {rows[0]['amount_cents']}"
    )
    assert rows[0]["sequence_index"] == 1, (
        f"the first line drawn carries sequence_index 1, got {rows[0]['sequence_index']}"
    )
    assert rows[0]["status"] == "ENCUMBERED", (
        f"a newly written allocation line is ENCUMBERED, got {rows[0]['status']}"
    )


# --------------------------------------------------------------------------- #
# an empty reporting population
# --------------------------------------------------------------------------- #
def test_annual_spend_for_a_fiscal_year_with_no_rows_reports_zeros_and_no_top_publisher(
    api, librarian_headers
):
    """Fiscal year 2028 holds no fund, no allocation line and no paid invoice, so
    every figure is zero and the average and the leverage ratio are defined rather
    than divisions by zero.

    PRD §3.9: "From the allocation ledger, the report takes every allocation line whose fund carries the requested `fiscal_year`: `total_committed_cents` is the sum of `amount_cents` over lines whose status is `ENCUMBERED`, and `total_disbursed_cents` is the same sum over lines whose status is `DISBURSED`; released lines are excluded from both."
    PRD §3.9: "The headline `total_allocated_cents` then depends on the `basis`: on the encumbrance basis it is `total_committed_cents` plus `total_disbursed_cents`, and on the cash basis it is `total_disbursed_cents` alone."
    PRD §3.9: "From the invoice ledger, the report takes every invoice whose `status` is `PAID` and whose `invoice_date` falls inside the fiscal-year window, further narrowed to the requested `publisher_id` when one is supplied: `paid_invoice_count` is how many such invoices there are, and `avg_paid_net_cents` is the sum of their `net_cents` divided by that count and rounded half up to whole cents — or exactly zero when there are no such invoices, since division by zero is never attempted."
    PRD §3.9: "From the determination ledger, the report takes the effective determination of every article whose `accepted_on` falls inside the fiscal-year window: `ta_articles_covered` counts those whose route is `TA_FULL` or `TA_CAPPED`, and `ta_savings_cents` sums, over exactly that same subset, the `list_base_cents` less the `covered_amount_cents` less the `author_share_cents` of each determination — the portion of list price that the negotiated discount removed altogether."
    PRD §3.9: "Across the whole determination population, `hybrid_article_count` counts those whose journal has an `oa_model` of `HYBRID` and `fully_oa_article_count` counts those whose journal has an `oa_model` of `FULLY_OA`."
    PRD §3.9: "The `top_publisher_code` names the publisher with the largest paid net spend: the eligible pool is the publishers appearing among the paid invoices above, they are ranked by the sum of their invoices' `net_cents` descending with `publisher_code` ascending as the tie-break, and the winner's `publisher_code` is reported — or nothing at all when the pool is empty."
    PRD §3.9: "The `negotiation_leverage_ratio` expresses savings against cash actually paid: it is `ta_savings_cents` divided by `total_disbursed_cents`, except that the divisor is floored at 1 so that a year with no disbursement yields the savings figure rather than an undefined value, and the quotient is rounded half up to four decimal places."
    PRD §3.9: "The fiscal-year window runs from 1 July of the year before the requested `fiscal_year` through 30 June of the requested `fiscal_year`, inclusive at both ends."
    Design: Difficulty/boundary_precision_check/empty_input_set_analytics_returns_zeros_not_division_error
    """
    _setup_encumbered_fiscal_year_2027()

    report = validate_success(
        api.get_annual_spend(
            librarian_headers, params={"fiscal_year": 2028, "basis": "ENCUMBRANCE"}
        ),
        expected_status=200,
    )

    assert report["total_allocated_cents"] == 0, (
        f"no fiscal year 2028 fund exists, so total_allocated_cents should be 0, "
        f"got {report['total_allocated_cents']}"
    )
    assert report["total_committed_cents"] == 0, (
        f"total_committed_cents should be 0, got {report['total_committed_cents']}"
    )
    assert report["total_disbursed_cents"] == 0, (
        f"total_disbursed_cents should be 0, got {report['total_disbursed_cents']}"
    )
    assert report["paid_invoice_count"] == 0, (
        f"no invoice exists at all, so paid_invoice_count should be 0, "
        f"got {report['paid_invoice_count']}"
    )
    assert report["avg_paid_net_cents"] == 0, (
        f"an empty paid-invoice set averages to exactly zero, "
        f"got {report['avg_paid_net_cents']}"
    )
    assert report["ta_articles_covered"] == 0, (
        f"ta_articles_covered should be 0, got {report['ta_articles_covered']}"
    )
    assert report["ta_savings_cents"] == 0, (
        f"ta_savings_cents should be 0, got {report['ta_savings_cents']}"
    )
    assert report["hybrid_article_count"] == 0, (
        f"no article was accepted inside the 2028 window, so hybrid_article_count "
        f"should be 0, got {report['hybrid_article_count']}"
    )
    assert report["fully_oa_article_count"] == 0, (
        f"no article was accepted inside the 2028 window, so fully_oa_article_count "
        f"should be 0, got {report['fully_oa_article_count']}"
    )
    assert report.get("top_publisher_code") is None, (
        f"an empty paid-invoice pool reports no top publisher, "
        f"got {report.get('top_publisher_code')!r}"
    )
    assert report["negotiation_leverage_ratio"] == pytest.approx(0.0, abs=0.01), (
        f"0 savings over a divisor floored at 1 is 0.0, "
        f"got {report['negotiation_leverage_ratio']}"
    )


def test_annual_spend_for_the_populated_fiscal_year_reports_the_encumbered_allocation(
    api, librarian_headers
):
    """The same report for fiscal year 2027 proves the database is not empty: the
    encumbered allocation shows up while the invoice-derived figures stay at their
    empty-set values.

    PRD §3.9: "From the allocation ledger, the report takes every allocation line whose fund carries the requested `fiscal_year`: `total_committed_cents` is the sum of `amount_cents` over lines whose status is `ENCUMBERED`, and `total_disbursed_cents` is the same sum over lines whose status is `DISBURSED`; released lines are excluded from both."
    PRD §3.9: "Across the whole determination population, `hybrid_article_count` counts those whose journal has an `oa_model` of `HYBRID` and `fully_oa_article_count` counts those whose journal has an `oa_model` of `FULLY_OA`."
    PRD §3.9: "From the invoice ledger, the report takes every invoice whose `status` is `PAID` and whose `invoice_date` falls inside the fiscal-year window, further narrowed to the requested `publisher_id` when one is supplied: `paid_invoice_count` is how many such invoices there are, and `avg_paid_net_cents` is the sum of their `net_cents` divided by that count and rounded half up to whole cents — or exactly zero when there are no such invoices, since division by zero is never attempted."
    PRD §3.9: "The `negotiation_leverage_ratio` expresses savings against cash actually paid: it is `ta_savings_cents` divided by `total_disbursed_cents`, except that the divisor is floored at 1 so that a year with no disbursement yields the savings figure rather than an undefined value, and the quotient is rounded half up to four decimal places."
    Design: Difficulty/boundary_precision_check/empty_input_set_analytics_returns_zeros_not_division_error
    """
    _setup_encumbered_fiscal_year_2027()

    report = validate_success(
        api.get_annual_spend(
            librarian_headers, params={"fiscal_year": 2027, "basis": "ENCUMBRANCE"}
        ),
        expected_status=200,
    )

    assert report["total_committed_cents"] == 300000, (
        f"the single ENCUMBERED line of the 2027 fund totals 300000, "
        f"got {report['total_committed_cents']}"
    )
    assert report["fully_oa_article_count"] == 1, (
        f"one article accepted inside the 2027 window sits at a FULLY_OA journal, "
        f"got {report['fully_oa_article_count']}"
    )
    assert report["paid_invoice_count"] == 0, (
        f"no invoice was ever recorded, so paid_invoice_count should be 0, "
        f"got {report['paid_invoice_count']}"
    )
    assert report["avg_paid_net_cents"] == 0, (
        f"an empty paid-invoice set averages to exactly zero, "
        f"got {report['avg_paid_net_cents']}"
    )
    assert report["negotiation_leverage_ratio"] == pytest.approx(0.0, abs=0.01), (
        f"no TA savings over a divisor floored at 1 is 0.0, "
        f"got {report['negotiation_leverage_ratio']}"
    )
