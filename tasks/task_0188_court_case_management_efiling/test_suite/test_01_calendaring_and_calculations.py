"""Calendaring engine and money/eligibility calculations.

Covers the dual calendaring variants, post-judgment interest, the marginal
appeal-transmittal tiers, the fee-waiver eligibility ratio, and the case fee
aggregates.
"""
from test_helpers import (
    validate_success, get_success_data,
    create_deadline_payload, create_fee_waiver_payload,
    make_attorney_headers, TEST_USERS,
    setup_open_case, setup_draft_case, setup_judgment_entered,
    setup_notice_filed_appeal, add_fee_waiver, add_accepted_motion_filing,
    file_motion, add_party, efile, pay_review_accept, review_accept,
)

CLERK = TEST_USERS["clerk_headers"]
JUDGE = TEST_USERS["judge_headers"]
ADMIN = TEST_USERS["system_admin_headers"]
ATT_PL = "att_1"


# =====================================================================
# Queue A: dual_variant_calc
# =====================================================================
def test_due_date_calendar_vs_court_days_diverge(api):
    """PRD 3.4: "Under the calendar variant, selected when `counting_mode` is `CALENDAR`,
    the engine first adds the full `interval_days` as calendar days to the anchor date."
    PRD 3.4: "Under the court-day variant, selected when `counting_mode` is `COURT_DAYS`,
    the engine instead steps forward one day at a time from the day after the anchor date
    and counts only court days: any day that is a Saturday, Sunday, or court holiday is
    skipped without consuming any of the interval, and stepping stops once `interval_days`
    court days have been counted, so the landing day is always itself a court day."
    PRD 3.4: "The computed `due_date` is pinned to 23:59:59.000Z of the landing day."

    Design: Difficulty/dual_variant_calc/due_date_calendar_vs_court_days_diverge
    """
    base = setup_open_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]

    cal = get_success_data(api.create_deadline(
        create_deadline_payload(
            case_id, anchor_date="2026-03-04T00:00:00.000Z",
            interval_days=10, counting_mode="CALENDAR",
        ), CLERK))
    cd = get_success_data(api.create_deadline(
        create_deadline_payload(
            case_id, anchor_date="2026-03-04T00:00:00.000Z",
            interval_days=10, counting_mode="COURT_DAYS",
        ), CLERK))

    assert cal["due_date"] == "2026-03-16T23:59:59.000Z", cal["due_date"]
    assert cd["due_date"] == "2026-03-18T23:59:59.000Z", cd["due_date"]
    assert cal["due_date"] != cd["due_date"]


def test_judgment_interest_and_fee_eligibility_distinct_domains(api):
    """PRD 3.7: "The accrued interest in cents is the principal_cents multiplied by that
    daily rate multiplied by the elapsed days, rounded half up to whole cents."
    PRD 3.6: "The eligibility ratio is the declared monthly income in cents divided by
    that threshold, rounded half up to four decimal places."

    Design: Difficulty/dual_variant_calc/judgment_interest_vs_fee_eligibility_different_domains
    """
    # OPEN case; fee waiver against the complaint; judgment 1,000,000c @ 1000bps.
    base = setup_open_case(clock="2026-04-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    fw = add_fee_waiver(case_id, base["complaint"]["id"], base["plaintiff"]["id"],
                        attorney_user_id=ATT_PL, monthly_income_cents=150000, household_size=1)
    jpayload = {
        "case_id": case_id, "judgment_type": "TRIAL",
        "prevailing_party_id": base["plaintiff"]["id"],
        "principal_cents": 1000000, "interest_rate_bps": 1000,
        "expected_case_version": base["case_version"],
    }
    judgment = get_success_data(api.create_judgment(jpayload, JUDGE))
    get_success_data(api.set_clock("2026-07-01T00:00:00.000Z", ADMIN))

    jread = validate_success(api.get_judgment(judgment["id"], CLERK))
    fwread = validate_success(api.get_fee_waiver(fw["id"], CLERK))

    assert jread["total_with_interest_cents"] == 1024932, jread["total_with_interest_cents"]
    assert fwread["eligibility_ratio"] == 1.1538, fwread["eligibility_ratio"]


# =====================================================================
# Queue A: combinatorial_formula
# =====================================================================
def test_appeal_transmittal_marginal_tiers_600_pages(api):
    """PRD 3.8: "The transmittal fee is a flat base of 5000 cents plus a marginal
    per-page charge across three tiers, where the boundaries are on cumulative page
    count: the first 100 pages are charged 50 cents each, pages 101 through 500 are
    charged 30 cents each, and every page beyond 500 is charged 15 cents each."
    PRD 3.8: "a 600-page record pays 50 cents on its first 100 pages, 30 cents on the
    next 400, and 15 cents on the final 100 — never a single flat rate across the whole
    record."

    Design: Difficulty/combinatorial_formula/appeal_transmittal_marginal_tiers_nonlinear
    """
    base = setup_notice_filed_appeal(clock="2026-04-01T00:00:00.000Z",
                                     filed_on="2026-04-10T00:00:00.000Z")
    appeal = validate_success(
        api.prepare_record(base["appeal"]["id"], {"record_page_count": 600}, CLERK)
    )
    assert appeal["transmittal_fee_cents"] == 23500, appeal["transmittal_fee_cents"]
    assert appeal["status"] == "RECORD_PREPARED"


def test_case_fee_aggregates_classify_then_sum(api):
    """PRD 3.1: "`total_fees_assessed_cents`, the sum of `fee_cents` over the case's
    accepted filings whose `fee_status` is `ASSESSED` or `PAID`, and
    `total_fees_paid_cents`, the sum of `fee_cents` over the case's filings whose
    `fee_status` is `PAID` or `WAIVED`."

    Design: Difficulty/combinatorial_formula/case_total_fees_sum_then_aggregate_order
    """
    # First complaint PAID, accepted; second complaint WAIVED, accepted.
    base = setup_draft_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    pl = add_party(case_id, role="PLAINTIFF", attorney_user_id=ATT_PL)
    add_party(case_id, role="DEFENDANT", attorney_user_id="att_2")

    f1 = efile(case_id, pl["id"], ATT_PL, document_type="COMPLAINT", title="Complaint 1")
    pay_review_accept(f1["id"])

    f2 = efile(case_id, pl["id"], ATT_PL, document_type="COMPLAINT", title="Complaint 2")
    fw = add_fee_waiver(case_id, f2["id"], pl["id"], attorney_user_id=ATT_PL)
    get_success_data(api.approve_fee_waiver(fw["id"], CLERK))
    review_accept(f2["id"])

    case = validate_success(api.get_case(case_id, CLERK))
    assert case["total_fees_assessed_cents"] == 43500, case["total_fees_assessed_cents"]
    assert case["total_fees_paid_cents"] == 87000, case["total_fees_paid_cents"]


# =====================================================================
# Queue A: boundary_precision_check (fee-waiver strict cutoff)
# =====================================================================
def test_fee_waiver_ratio_exactly_at_cutoff(api):
    """PRD 3.6: "The eligibility ratio is the declared monthly income in cents divided
    by that threshold, rounded half up to four decimal places. A ratio strictly less
    than 1.25 marks the request as presumptively eligible."

    Design: Difficulty/boundary_precision_check/fee_waiver_ratio_strict_cutoff_at_125
    """
    base = setup_draft_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    pl = add_party(case_id, role="PLAINTIFF", attorney_user_id=ATT_PL)
    complaint = efile(case_id, pl["id"], ATT_PL, document_type="COMPLAINT", title="Complaint")

    fw = validate_success(api.create_fee_waiver(
        create_fee_waiver_payload(case_id, complaint["id"], pl["id"],
                                  monthly_income_cents=162500, household_size=1),
        make_attorney_headers(ATT_PL)), expected_status=201)
    assert fw["eligibility_ratio"] == 1.25, fw["eligibility_ratio"]


# =====================================================================
# Queue B (Corner): calculations section
# =====================================================================
def test_judgment_interest_one_day_accrual(api):
    """PRD 3.7: "The accrued interest in cents is the principal_cents multiplied by that
    daily rate multiplied by the elapsed days, rounded half up to whole cents. The
    total_with_interest_cents is the principal_cents plus that accrued interest."

    Design: Corner/calculations/judgment_interest_one_day_accrual
    """
    base = setup_judgment_entered(
        clock="2026-04-01T00:00:00.000Z",
        judgment_overrides={"principal_cents": 1000000, "interest_rate_bps": 1000},
    )
    get_success_data(api.set_clock("2026-04-02T00:00:00.000Z", ADMIN))
    jread = validate_success(api.get_judgment(base["judgment"]["id"], CLERK))
    assert jread["total_with_interest_cents"] == 1000274, jread["total_with_interest_cents"]


def test_judgment_interest_zero_on_entry_day(api):
    """PRD 3.7: "The number of elapsed days is the larger of zero and the whole number
    of days from the date of entered_at through the current clock date."

    Design: Corner/calculations/judgment_interest_zero_at_entry_day
    """
    base = setup_judgment_entered(
        clock="2026-04-01T00:00:00.000Z",
        judgment_overrides={"principal_cents": 1000000, "interest_rate_bps": 1000},
    )
    # Clock unchanged at 2026-04-01 (entry day).
    jread = validate_success(api.get_judgment(base["judgment"]["id"], CLERK))
    assert jread["total_with_interest_cents"] == 1000000, jread["total_with_interest_cents"]


def test_appeal_fee_tier_boundary_at_100_pages(api):
    """PRD 3.8: "the first 100 pages are charged 50 cents each, pages 101 through 500
    are charged 30 cents each, and every page beyond 500 is charged 15 cents each."

    Design: Corner/calculations/appeal_fee_tier_boundary_at_100_pages
    """
    base = setup_notice_filed_appeal(clock="2026-04-01T00:00:00.000Z",
                                     filed_on="2026-04-10T00:00:00.000Z")
    appeal = validate_success(
        api.prepare_record(base["appeal"]["id"], {"record_page_count": 100}, CLERK)
    )
    assert appeal["transmittal_fee_cents"] == 10000, appeal["transmittal_fee_cents"]


def test_due_date_court_day_skips_holiday(api):
    """PRD 3.4: "any day that is a Saturday, Sunday, or court holiday is skipped without
    consuming any of the interval, and stepping stops once interval_days court days have
    been counted, so the landing day is always itself a court day."

    Design: Corner/calculations/due_date_court_day_holiday_skip
    """
    base = setup_draft_case(clock="2026-03-01T00:00:00.000Z",
                            court_overrides={"holidays": ["2026-03-10"]})
    case_id = base["case"]["id"]
    dl = validate_success(api.create_deadline(
        create_deadline_payload(
            case_id, anchor_date="2026-03-04T00:00:00.000Z",
            interval_days=10, counting_mode="COURT_DAYS",
        ), CLERK), expected_status=201)
    assert dl["due_date"] == "2026-03-19T23:59:59.000Z", dl["due_date"]


def test_fee_waiver_threshold_scales_with_household(api):
    """PRD 3.6: "The eligibility threshold for a household is a base of 130000 cents
    plus 47000 cents for each additional person beyond the first; that is, the threshold
    equals the base plus the per-person amount multiplied by one less than the household
    size."

    Design: Corner/calculations/feewaiver_eligibility_household_threshold_scaling
    """
    base = setup_draft_case(clock="2026-03-01T00:00:00.000Z")
    case_id = base["case"]["id"]
    pl = add_party(case_id, role="PLAINTIFF", attorney_user_id=ATT_PL)
    complaint = efile(case_id, pl["id"], ATT_PL, document_type="COMPLAINT", title="Complaint")
    fw = validate_success(api.create_fee_waiver(
        create_fee_waiver_payload(case_id, complaint["id"], pl["id"],
                                  monthly_income_cents=200000, household_size=3),
        make_attorney_headers(ATT_PL)), expected_status=201)
    assert fw["eligibility_ratio"] == 0.8929, fw["eligibility_ratio"]
