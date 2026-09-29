"""Formulas whose rounding points and evaluation order are pinned by the contract.

The housing total rounds once per calendar-month segment, the covered-tuition
waterfall runs in a fixed seven-step order that feeds the annual cap ledger and
the Yellow Ribbon match, and an overpayment debt is derived from a snapshot taken
before the recomputation and then collected through a two-bucket waterfall.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers.fixtures import (
    build_certified_certification,
    build_paid_certification,
    create_agreement,
    create_award,
    create_certification,
    certify_certification,
    price_certification,
    read_agreement,
    read_certification,
    read_student,
    set_clock_to,
    submit_certification,
)
from test_helpers.test_users import BURSAR_HEADERS

WITHDRAWAL_EFFECTIVE_DATE = "2026-09-01"
LATE_REPORTED_DATE = "2026-10-05"


# ─── The housing total ────────────────────────────────────────────────
def test_housing_total_rounds_each_month_segment_before_summing(api, baseline):
    """Segment-level rounding yields 776444 cents, one cent above a single rounding.

    PRD: "The order is pinned and matters: summing all billable days first and
    rounding once at the end is a different computation that differs by whole
    cents, and it is not what this service specifies."

    Design: Difficulty/combinatorial_formula/mha_term_total_per_segment_rounding_then_sum
    """
    scenario = build_certified_certification(api, baseline)

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_integer_cents(certification, "mha_term_total_cents")
    assert certification["mha_term_total_cents"] == 776444
    assert certification["mha_term_total_cents"] != 776443, (
        "Summing the billable days first and rounding once gives 776443, which is wrong"
    )


def test_a_whole_calendar_month_segment_bills_as_thirty_uniform_days(api, baseline):
    """September, October and November each bill 30 days at the campus rate.

    PRD: "Each segment is then assigned a billable-day count under a rule that
    treats a whole calendar month as a uniform 30 days: if a segment begins on
    the first calendar day of its month **and** ends on the last calendar day of
    that same month, its billable days are 30 regardless of whether the month
    actually has 28, 29, 30 or 31 days; otherwise its billable days are the whole
    number of days from its start to its end, plus one."

    Design: Difficulty/combinatorial_formula/mha_term_total_per_segment_rounding_then_sum
    """
    scenario = build_certified_certification(api, baseline)

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_derived_enrollment_block(
        certification,
        certified_days=c.CANONICAL_CERTIFIED_DAYS,
        rate_of_pursuit_pct=100,
        rop_tier_pct=100,
        training_time=c.TRAINING_TIME_FULL,
        modality=c.MODALITY_RESIDENTIAL,
        mha_eligible=True,
        mha_monthly_rate_cents=c.CAMPUS_BAH_MONTHLY_CENTS,
    )
    # 8 days of August, three uniform 30-day months, then 11 days of December.
    assert certification["mha_term_total_cents"] == 56987 + 3 * 213700 + 78357


# ─── The annual cap ledger and the Yellow Ribbon waterfall ────────────
def _two_term_academic_year(api, baseline):
    """Certify a fall term, award against it, then price and submit a spring term."""
    fall = build_certified_certification(api, baseline)
    agreement_id, agreement_version = create_agreement(api, baseline.sup_headers)
    first_award = create_award(
        api,
        baseline.sup_headers,
        fall.certification_id,
        agreement_id,
        agreement_version,
    )

    spring_term = get_success_data(
        api.create_academic_term(f.spring_term_payload(), baseline.sup_headers)
    )
    spring_id, spring_version = create_certification(
        api,
        baseline.sco_headers,
        fall.student_id,
        spring_term["id"],
        baseline.program_id,
        term_start_certified=c.SPRING_TERM_START,
        term_end_certified=c.SPRING_TERM_END,
    )
    _, spring_version = price_certification(
        api,
        spring_id,
        spring_version,
        tuition_specific_aid_cents=0,
    )
    submit_certification(api, baseline.sco_headers, spring_id)
    return fall, agreement_id, first_award, spring_id


def test_the_first_certified_term_charges_the_whole_annual_cap(api, baseline):
    """cap_charged_cents equals va_tuition_cents and nothing else.

    PRD: "Step six sets `cap_charged_cents` equal to `va_tuition_cents` and to
    nothing else."

    Design: Difficulty/combinatorial_formula/annual_cap_ledger_and_yellow_ribbon_waterfall_pinned_order
    """
    fall, _agreement_id, _award, _spring_id = _two_term_academic_year(api, baseline)

    certification = read_certification(
        api, baseline.sup_headers, fall.certification_id
    )
    assert certification["cap_charged_cents"] == 2790000
    assert certification["cap_charged_cents"] == certification["va_tuition_cents"]


def test_a_second_term_in_the_same_year_finds_the_cap_exhausted(api, baseline):
    """The prior term's cap charge leaves no annual headroom for the spring term.

    PRD: "Step three sets `ay_cap_remaining_before_cents` to the statutory annual
    cap of 2790000 cents, that is $27,900.00 per academic year, minus that
    accumulated total, floored at 0."

    Design: Difficulty/combinatorial_formula/annual_cap_ledger_and_yellow_ribbon_waterfall_pinned_order
    """
    _fall, agreement_id, _award, spring_id = _two_term_academic_year(api, baseline)
    read_agreement(api, baseline.sup_headers, agreement_id)

    certified = certify_certification(api, baseline.sup_headers, spring_id)
    assert certified["certified_days"] == 117
    a.assert_covered_tuition_block(
        certified,
        net_covered_cents=3150000,
        ay_cap_remaining_before_cents=0,
        va_tuition_cents=0,
        cap_charged_cents=0,
        yr_gap_cents=3150000,
    )
    assert certified["mha_term_total_cents"] == 840553


def test_the_school_share_is_the_smallest_of_the_three_limits(api, baseline):
    """The per-student headroom of 420000 beats half the gap and the pool.

    PRD: "From those three, `school_share_cents` is the **smallest** of: half of
    `yr_gap_cents` rounded half up, the per-student headroom, and the pool
    headroom."

    Design: Difficulty/combinatorial_formula/annual_cap_ledger_and_yellow_ribbon_waterfall_pinned_order
    """
    _fall, agreement_id, _award, spring_id = _two_term_academic_year(api, baseline)
    certify_certification(api, baseline.sup_headers, spring_id)
    current_version = read_agreement(api, baseline.sup_headers, agreement_id)["version"]

    second_award = create_award(
        api, baseline.sup_headers, spring_id, agreement_id, current_version
    )
    a.assert_award_amounts(
        second_award,
        yr_gap_basis_cents=3150000,
        per_student_remaining_before_cents=420000,
        pool_remaining_before_cents=920000,
        school_share_cents=420000,
        student_out_of_pocket_cents=2310000,
    )


def test_each_award_debits_the_pool_and_raises_the_participant_count(api, baseline):
    """Two awards leave 500000 cents of pool and a participant count of 2.

    PRD: "Award creation debits the agreement: `pool_remaining_cents` falls by
    `school_share_cents`, `participant_count` rises by one, and the agreement's
    `version` increments by one."

    Design: Difficulty/combinatorial_formula/annual_cap_ledger_and_yellow_ribbon_waterfall_pinned_order
    """
    _fall, agreement_id, _award, spring_id = _two_term_academic_year(api, baseline)
    certify_certification(api, baseline.sup_headers, spring_id)
    current_version = read_agreement(api, baseline.sup_headers, agreement_id)["version"]
    create_award(api, baseline.sup_headers, spring_id, agreement_id, current_version)

    agreement = read_agreement(api, baseline.sup_headers, agreement_id)
    a.assert_fields(
        agreement,
        {"pool_remaining_cents": 500000, "participant_count": 2},
    )
    a.assert_pool_ledger_balances(agreement, 80000 + 420000)


# ─── The overpayment debt and the repayment waterfall ─────────────────
def _late_mitigated_withdrawal(api, baseline):
    """Pay a certified term, then report a mitigated withdrawal 34 days late."""
    scenario = build_paid_certification(
        api,
        baseline,
        tuition_amount_cents=2790000,
        mha_amount_cents=776444,
        posted_on=c.CLOCK_START_DATE,
    )
    set_clock_to(api, LATE_REPORTED_DATE)
    change_report = get_success_data(
        api.create_enrollment_change_report(
            f.complete_withdrawal_payload(
                scenario.certification_id,
                WITHDRAWAL_EFFECTIVE_DATE,
                mitigating_circumstances_flag=True,
            ),
            baseline.sco_headers,
        )
    )
    get_success_data(
        api.reconcile_change_report(change_report["id"], {}, baseline.sup_headers)
    )
    debts = get_success_data(
        api.list_benefit_debts(
            baseline.sup_headers, {"change_report_id": change_report["id"]}
        )
    )
    assert len(debts) == 1, f"Expected exactly one overpayment debt, got {debts}"
    return scenario, change_report, debts[0]


def test_a_report_filed_past_the_deadline_makes_the_school_the_debtor(api, baseline):
    """34 days late is LATE, which hands the overpayment to the institution.

    PRD: "Its obligor and its reason are chosen together from the change report's
    `liability_party`: a `liability_party` of `STUDENT` yields a `debtor_type` of
    `STUDENT` and a `source` of `AMENDMENT_OVERPAYMENT`, while a
    `liability_party` of `SCHOOL` yields a `debtor_type` of `SCHOOL` and a
    `source` of `LATE_REPORTING_LIABILITY`."

    Design: Difficulty/combinatorial_formula/overpayment_debt_pinned_snapshot_then_repayment_waterfall
    """
    _scenario, change_report, debt = _late_mitigated_withdrawal(api, baseline)

    a.assert_fields(
        change_report,
        {
            "days_late": 34,
            "reporting_status": c.REPORTING_STATUS_LATE,
            "liability_party": c.LIABILITY_SCHOOL,
        },
    )
    a.assert_fields(
        debt,
        {
            "debtor_type": c.DEBTOR_TYPE_SCHOOL,
            "source": c.DEBT_SOURCE_LATE_REPORTING_LIABILITY,
            "notification_due_on": "2026-11-04",
        },
    )


def test_mitigating_circumstances_keep_the_whole_assessed_tuition(api, baseline):
    """With mitigation the covered amount stands, so only housing is overpaid.

    PRD: "For a `COMPLETE_WITHDRAWAL` with `mitigating_circumstances_flag` true,
    `net_covered_cents` keeps the as-certified covered amount in full — VA pays
    the whole assessed tuition, which is precisely what mitigating circumstances
    buy the student."

    Design: Difficulty/combinatorial_formula/overpayment_debt_pinned_snapshot_then_repayment_waterfall
    """
    scenario, _change_report, debt = _late_mitigated_withdrawal(api, baseline)

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_fields(
        certification,
        {
            "net_covered_cents": c.CANONICAL_NET_COVERED_CENTS,
            "va_tuition_cents": 2790000,
            "mha_term_total_cents": 56987,
        },
    )
    a.assert_fields(
        debt,
        {
            "tuition_component_cents": 0,
            "mha_component_cents": 719457,
            "principal_cents": 719457,
        },
    )


def test_repayments_fill_the_tuition_bucket_before_the_housing_bucket(api, baseline):
    """With an empty tuition bucket the whole payment lands on housing.

    PRD: "Allocation follows a fixed two-bucket waterfall in which the tuition
    bucket fills first: the amount applied to tuition is the smaller of
    `amount_cents` and the tuition bucket's unfilled room, which is
    `tuition_component_cents` minus `tuition_repaid_cents`; the amount applied to
    housing is then the smaller of whatever remains of `amount_cents` after the
    tuition allocation and the housing bucket's unfilled room, which is
    `mha_component_cents` minus `mha_repaid_cents`."

    Design: Difficulty/combinatorial_formula/overpayment_debt_pinned_snapshot_then_repayment_waterfall
    """
    _scenario, _change_report, debt = _late_mitigated_withdrawal(api, baseline)

    after_first = get_success_data(
        api.create_debt_repayment(
            debt["id"], f.repayment_payload(700000), BURSAR_HEADERS
        )
    )
    a.assert_fields(
        after_first,
        {
            "tuition_repaid_cents": 0,
            "mha_repaid_cents": 700000,
            "repaid_cents": 700000,
            "outstanding_cents": 19457,
            "collection_status": c.DEBT_COLLECTION_PARTIALLY_REPAID,
        },
    )

    after_second = get_success_data(
        api.create_debt_repayment(debt["id"], f.repayment_payload(19457), BURSAR_HEADERS)
    )
    a.assert_fields(
        after_second,
        {
            "mha_repaid_cents": 719457,
            "outstanding_cents": 0,
            "collection_status": c.DEBT_COLLECTION_SATISFIED,
        },
    )


def test_a_school_debt_never_enters_the_students_open_balance(api, baseline):
    """The student's open principal stays at 0 while entitlement is credited back.

    PRD: "When `debtor_type` is `SCHOOL`, the obligor is the institution itself,
    which has no row of its own anywhere in this service; `student_id` is still
    recorded, because the overpayment still relates to that student's enrollment,
    but the debt never touches the student's open balance in either direction."

    Design: Difficulty/combinatorial_formula/overpayment_debt_pinned_snapshot_then_repayment_waterfall
    """
    scenario, _change_report, _debt = _late_mitigated_withdrawal(api, baseline)

    student = read_student(api, baseline.sco_headers, scenario.student_id)
    a.assert_fields(
        student,
        {"open_debt_principal_cents": 0, "entitlement_days_remaining": 1072},
    )
    a.assert_entitlement_ledger_balances(student, 8)
