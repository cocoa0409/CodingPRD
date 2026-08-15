"""Contribution reporting: creation defaults, due dates, rounding order,
provisional vs final dues, submission, and listing (PRD §3.3, §2.6, §2.11)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_contribution_report,
    assert_instant_equals,
    create_apprentice,
    create_employer,
    create_fund,
    create_indentured_apprentice,
    create_report,
    get_apprentice,
    get_employer,
    get_report,
    make_employer_rep_headers,
    report_line,
    setup_fund_employer_apprentice,
    submit_report,
    update_employer_rate,
    validate_error,
    validate_paginated,
)


def test_rate_raise_between_create_and_submit_diverges_due(api):
    """PRD §3.1: "Rates are never retroactive — a draft report keeps the
    provisional estimate computed at its creation, and a submitted report
    keeps the authoritative due computed at its submission."
    PRD §3.3: "On acceptance, the final `contribution_due_cents` is computed
    at the employer's current agreement rate — so a rate change between
    creation and submission makes the final due diverge from the provisional
    one for identical lines — each line's hours are added to its apprentice's
    `ojt_hours_accumulated` with the wage step and rate recomputed (§3.6), and
    the employer's `outstanding_cents` is recomputed."

    Design: Difficulty/dual_variant_calc/dual_variant_contribution_provisional_vs_final
    """
    _fund, employer, apprentice = setup_fund_employer_apprentice(rate=500)
    report = create_report(
        employer, 2026, 6, [report_line(apprentice["id"], 100)],
    )
    assert_contribution_report(report)
    assert report["provisional_due_cents"] == 50000, (
        "provisional estimate uses the creation-time rate: 100h x 500c"
    )
    assert report["contribution_due_cents"] is None

    update_employer_rate(employer["id"], 600)
    submitted = submit_report(employer, report["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["contribution_due_cents"] == 60000, (
        "final due uses the submission-time rate: 100h x 600c"
    )
    assert submitted["contribution_due_cents"] != report["provisional_due_cents"]


def test_rate_cut_between_create_and_submit_diverges_due(api):
    """PRD §3.3: "Its `provisional_due_cents` estimates what will be owed,
    computed from the reported lines at the employer's agreement rate at that
    moment."
    PRD §2.6: "An employer's `outstanding_cents` is the sum of
    `contribution_due_cents` over that employer's reports in `SUBMITTED`,
    `FLAGGED`, or `DELINQUENT` status; DRAFT reports contribute nothing
    because their due is still null, and PAID reports are excluded."

    Design: Difficulty/dual_variant_calc/dual_variant_contribution_provisional_vs_final
    """
    _fund, employer, apprentice = setup_fund_employer_apprentice(rate=600)
    report = create_report(
        employer, 2026, 6, [report_line(apprentice["id"], 100)],
    )
    assert report["provisional_due_cents"] == 60000

    update_employer_rate(employer["id"], 500)
    submitted = submit_report(employer, report["id"])
    assert submitted["contribution_due_cents"] == 50000, (
        "a rate cut before submission lowers the final due below the estimate"
    )
    assert get_employer(employer["id"])["outstanding_cents"] == 50000


def test_per_line_rounding_sums_to_1500(api):
    """PRD §3.3: "Both the provisional and the final due share one pinned
    recipe: for each line, multiply that line's `ojt_hours` by the applicable
    hourly rate and round the product half-up to a whole cent; then sum those
    per-line amounts."
    PRD §3.3: "Rounding each line before summing is mandatory — the
    alternative order (sum all hours, multiply by the rate, round once) yields
    different cents for fractional hours and must not be used."

    Design: Difficulty/combinatorial_formula/combinatorial_contribution_line_rounding_order
    """
    fund, employer, _a = setup_fund_employer_apprentice(rate=333)
    a2 = create_indentured_apprentice(fund["id"], employer["id"],
                                      full_name="App Two")
    a3 = create_indentured_apprentice(fund["id"], employer["id"],
                                      full_name="App Three")
    a1 = _a
    report = create_report(
        employer, 2026, 6,
        [
            report_line(a1["id"], 1.5),
            report_line(a2["id"], 1.5),
            report_line(a3["id"], 1.5),
        ],
    )
    submitted = submit_report(employer, report["id"])
    assert submitted["contribution_due_cents"] == 1500, (
        "3 x round_half_up(1.5 x 333) = 3 x 500 = 1500; the forbidden "
        "sum-then-round order would give round_half_up(1498.5) = 1499"
    )


def test_per_line_rounding_flows_to_employer_outstanding(api):
    """PRD §3.3: "Both the provisional and the final due share one pinned
    recipe: for each line, multiply that line's `ojt_hours` by the applicable
    hourly rate and round the product half-up to a whole cent; then sum those
    per-line amounts."
    PRD §2.6: "An employer's `outstanding_cents` is the sum of
    `contribution_due_cents` over that employer's reports in `SUBMITTED`,
    `FLAGGED`, or `DELINQUENT` status; DRAFT reports contribute nothing
    because their due is still null, and PAID reports are excluded."

    Design: Difficulty/combinatorial_formula/combinatorial_contribution_line_rounding_order
    """
    fund, employer, a1 = setup_fund_employer_apprentice(rate=333)
    a2 = create_indentured_apprentice(fund["id"], employer["id"],
                                      full_name="App Two")
    a3 = create_indentured_apprentice(fund["id"], employer["id"],
                                      full_name="App Three")
    report = create_report(
        employer, 2026, 6,
        [
            report_line(a1["id"], 1.5),
            report_line(a2["id"], 1.5),
            report_line(a3["id"], 1.5),
        ],
    )
    submit_report(employer, report["id"])

    assert get_employer(employer["id"])["outstanding_cents"] == 1500
    for app in (a1, a2, a3):
        assert get_apprentice(app["id"])["ojt_hours_accumulated"] == 1.5


def test_report_due_date_and_provisional_computed(api):
    """PRD §3.3: "Its `due_date` falls on the fifteenth day of the month
    immediately following the reporting period at 00:00:00 UTC — a December
    period rolls into January 15 of the following year."
    PRD §3.3: "Its `provisional_due_cents` estimates what will be owed,
    computed from the reported lines at the employer's agreement rate at that
    moment."

    Design: Corner/entities/contribution_report_due_date_computed
    """
    _fund, employer, apprentice = setup_fund_employer_apprentice(rate=500)
    report = create_report(
        employer, 2026, 6, [report_line(apprentice["id"], 40)],
    )
    assert_contribution_report(report)
    assert_instant_equals(report["due_date"], "2026-07-15T00:00:00Z")
    assert report["provisional_due_cents"] == 20000, "40h x 500c"
    assert report["status"] == "DRAFT"
    assert report["contribution_due_cents"] is None


def test_submit_credits_hours_and_outstanding(api):
    """PRD §3.3: "On acceptance, the final `contribution_due_cents` is
    computed at the employer's current agreement rate — so a rate change
    between creation and submission makes the final due diverge from the
    provisional one for identical lines — each line's hours are added to its
    apprentice's `ojt_hours_accumulated` with the wage step and rate
    recomputed (§3.6), and the employer's `outstanding_cents` is recomputed."

    Design: Corner/calculations/report_submission_credits_hours_and_wage_rate
    """
    _fund, employer, apprentice = setup_fund_employer_apprentice(rate=500)
    report = create_report(
        employer, 2026, 6, [report_line(apprentice["id"], 120)],
    )
    submitted = submit_report(employer, report["id"])
    assert submitted["status"] == "SUBMITTED"
    assert submitted["contribution_due_cents"] == 60000, "120h x 500c"

    after = get_apprentice(apprentice["id"])
    assert after["ojt_hours_accumulated"] == 120
    assert after["current_wage_step"] == 1
    assert after["current_wage_rate_cents"] == 2000
    assert get_employer(employer["id"])["outstanding_cents"] == 60000


def test_submit_line_with_applicant_apprentice_rejected(api):
    """PRD §3.3: "The line set must be non-empty (else `ERR_INVALID_REQUEST`),
    every line's apprentice must belong to this employer (else
    `ERR_LINE_EMPLOYER_MISMATCH`, HTTP 400), and every line's apprentice must
    be in `INDENTURED` or `SUSPENDED` program status (else
    `ERR_APPRENTICE_NOT_HOUR_ELIGIBLE`, HTTP 400)."

    Design: Corner/validations/report_line_with_applicant_apprentice_rejected
    """
    fund = create_fund()
    employer = create_employer(fund["id"], rate=500)
    apprentice = create_apprentice(fund["id"], employer["id"])
    report = create_report(
        employer, 2026, 6, [report_line(apprentice["id"], 10)],
    )
    resp = api.submit_report(report["id"], make_employer_rep_headers(employer["id"]))
    validate_error(resp, ApiErrorId.ERR_APPRENTICE_NOT_HOUR_ELIGIBLE)
    assert get_report(report["id"])["status"] == "DRAFT"
    assert get_apprentice(apprentice["id"])["ojt_hours_accumulated"] == 0


def test_duplicate_report_period_rejected(api):
    """PRD §3.3: "Only one report may exist per employer per period in any
    status at all; a second report for the same employer and period is
    rejected with `ERR_DUPLICATE_REPORT_PERIOD`."

    Design: Corner/validations/duplicate_report_period_rejected
    """
    _fund, employer, apprentice = setup_fund_employer_apprentice(rate=500)
    create_report(employer, 2026, 6, [report_line(apprentice["id"], 10)])
    resp = api.create_contribution_report(
        {
            "employer_id": employer["id"],
            "period_year": 2026,
            "period_month": 6,
            "lines": [report_line(apprentice["id"], 20)],
        },
        make_employer_rep_headers(employer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_REPORT_PERIOD)


def test_future_period_rejected(api):
    """PRD §3.3: "The period month must lie within 1 through 12, and the
    period must already have begun — a period whose first day lies after the
    current logical time is rejected — with violations reported as
    `ERR_INVALID_PERIOD`."

    Design: Corner/validations/invalid_period_rejected
    """
    fund = create_fund()
    employer = create_employer(fund["id"], rate=500)
    apprentice = create_apprentice(fund["id"], employer["id"])
    # Default logical clock (2026-08-01T00:00:00Z): September 2026 has not begun.
    resp = api.create_contribution_report(
        {
            "employer_id": employer["id"],
            "period_year": 2026,
            "period_month": 9,
            "lines": [report_line(apprentice["id"], 10)],
        },
        make_employer_rep_headers(employer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD)


def test_default_logical_clock_rejects_future_period(api):
    """PRD §2.11: "Before it has ever been adjusted, the logical clock reads
    exactly 2026-08-01T00:00:00Z."
    PRD §3.3: "The period month must lie within 1 through 12, and the period
    must already have begun — a period whose first day lies after the current
    logical time is rejected — with violations reported as
    `ERR_INVALID_PERIOD`."

    Design: Corner/endpoints/clock_default_is_fixed_epoch
    """
    # No clock call is made anywhere in this test: the reading is the default.
    fund = create_fund()
    employer = create_employer(fund["id"], rate=500)
    apprentice = create_apprentice(fund["id"], employer["id"])
    resp = api.create_contribution_report(
        {
            "employer_id": employer["id"],
            "period_year": 2026,
            "period_month": 9,
            "lines": [report_line(apprentice["id"], 10)],
        },
        make_employer_rep_headers(employer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_PERIOD)


def test_report_list_filter_and_pagination(api):
    """PRD §3.3: "The report ledger can be listed with optional `employer_id`,
    `status`, `period_year`, and `period_month` filters."
    PRD §2.3: "The `meta` object of every list response carries the four
    pagination fields `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/contribution_report_list_filter_and_pagination
    """
    fund = create_fund()
    employer1 = create_employer(fund["id"], rate=500)
    employer2 = create_employer(fund["id"], rate=500,
                                legal_name="Beacon Mechanical")
    apprentice = create_apprentice(fund["id"], employer1["id"],
                                   full_name="App One")
    create_report(employer1, 2026, 6, [report_line(apprentice["id"], 10)])
    create_report(employer1, 2026, 7, [report_line(apprentice["id"], 10)])
    create_report(employer2, 2026, 6, [report_line(apprentice["id"], 5)])

    resp = api.list_contribution_reports(
        ADMIN,
        params={"employer_id": employer1["id"], "limit": 1, "offset": 0},
    )
    data, meta = validate_paginated(resp)
    assert len(data) == 1
    assert data[0]["employer_id"] == employer1["id"]
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0


def test_submit_by_non_owner_rejected(api):
    """PRD §3.3: "The caller must own the report — an `EmployerRep` whose
    `X-User-ID` differs from the report's `employer_id` is rejected with
    `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/roles/report_submit_by_non_owner_forbidden
    """
    # E1 owns the report; E2 attempts the submit.
    fund = create_fund()
    employer1 = create_employer(fund["id"], rate=500)
    employer2 = create_employer(fund["id"], rate=500,
                                legal_name="Beacon Mechanical")
    apprentice = create_apprentice(fund["id"], employer1["id"])
    report = create_report(
        employer1, 2026, 6, [report_line(apprentice["id"], 10)],
    )
    resp = api.submit_report(
        report["id"], make_employer_rep_headers(employer2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)
    assert get_report(report["id"])["status"] == "DRAFT"
