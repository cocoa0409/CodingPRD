"""The two arithmetic bases a certification can carry.

A certification stores its amounts either on the AS_CERTIFIED basis written at
certification time or on the AS_RECONCILED basis written when a change in
enrollment is reconciled, and the same input data yields different money and
different entitlement under the two bases.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers.fixtures import (
    build_certified_certification,
    build_paid_certification,
    read_certification,
    read_student,
    set_clock_to,
)

WITHDRAWAL_EFFECTIVE_DATE = "2026-09-01"
WITHDRAWAL_REPORTED_DATE = "2026-09-05"
REDUCTION_EFFECTIVE_DATE = "2026-10-15"
REDUCTION_REPORTED_DATE = "2026-10-20"


# ─── Covered tuition under the two bases ──────────────────────────────
def test_as_certified_basis_prices_the_whole_assessed_tuition(api, baseline):
    """Certifying stores the covered amount straight from the report in force.

    PRD: "Step one takes the covered amount straight from the tuition and fee
    report in force — add its `gross_tuition_cents` and `mandatory_fees_cents`,
    subtract its `tuition_specific_aid_cents`, floor at 0 — and stores it as the
    certification's `net_covered_cents`."

    Design: Difficulty/dual_variant_calc/covered_tuition_as_certified_vs_as_reconciled_money_divergence
    """
    scenario = build_paid_certification(
        api,
        baseline,
        tuition_amount_cents=2790000,
        mha_amount_cents=776444,
        posted_on=c.CLOCK_START_DATE,
    )

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    assert certification["amount_basis"] == c.AMOUNT_BASIS_AS_CERTIFIED
    a.assert_covered_tuition_block(
        certification,
        net_covered_cents=2950000,
        ay_cap_remaining_before_cents=2790000,
        va_tuition_cents=2790000,
        cap_charged_cents=2790000,
        yr_gap_cents=160000,
    )


def test_as_reconciled_basis_prorates_the_covered_tuition_to_attendance(api, baseline):
    """An unmitigated withdrawal reprices the covered amount by attended days.

    PRD: "For a `COMPLETE_WITHDRAWAL` with `mitigating_circumstances_flag`
    false, tuition is prorated to attendance: count the whole days from
    `term_start_certified` to `effective_date` with the effective date itself
    **excluded**, then set `net_covered_cents` to the as-certified covered
    amount multiplied by that attended-day count, divided by the as-certified
    `certified_days`, rounded half up."

    Design: Difficulty/dual_variant_calc/covered_tuition_as_certified_vs_as_reconciled_money_divergence
    """
    scenario = build_paid_certification(
        api,
        baseline,
        tuition_amount_cents=2790000,
        mha_amount_cents=776444,
        posted_on=c.CLOCK_START_DATE,
    )
    set_clock_to(api, WITHDRAWAL_REPORTED_DATE)
    change_report = get_success_data(
        api.create_enrollment_change_report(
            f.complete_withdrawal_payload(
                scenario.certification_id,
                WITHDRAWAL_EFFECTIVE_DATE,
                mitigating_circumstances_flag=False,
            ),
            baseline.sco_headers,
        )
    )
    get_success_data(
        api.reconcile_change_report(change_report["id"], {}, baseline.sup_headers)
    )

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    assert certification["amount_basis"] == c.AMOUNT_BASIS_AS_RECONCILED
    assert certification["status"] == c.CERT_STATUS_TERMINATED
    a.assert_covered_tuition_block(
        certification,
        net_covered_cents=214545,
        ay_cap_remaining_before_cents=2790000,
        va_tuition_cents=214545,
        cap_charged_cents=214545,
        yr_gap_cents=0,
    )
    assert certification["mha_term_total_cents"] == 56987


def test_the_overpayment_debt_is_the_gap_between_the_two_bases(api, baseline):
    """The debt components subtract the reconciled figures from what VA paid.

    PRD: "Third, derive the components: `tuition_component_cents` is the
    snapshotted `tuition_paid_cents` minus the new `va_tuition_cents`, floored
    at 0; `mha_component_cents` is the snapshotted `mha_paid_cents` minus the
    new `mha_term_total_cents`, floored at 0; `principal_cents` is their sum and
    is never mutated after creation; and `outstanding_cents` opens equal to
    `principal_cents`."

    Design: Difficulty/dual_variant_calc/covered_tuition_as_certified_vs_as_reconciled_money_divergence
    """
    scenario = build_paid_certification(
        api,
        baseline,
        tuition_amount_cents=2790000,
        mha_amount_cents=776444,
        posted_on=c.CLOCK_START_DATE,
    )
    set_clock_to(api, WITHDRAWAL_REPORTED_DATE)
    change_report = get_success_data(
        api.create_enrollment_change_report(
            f.complete_withdrawal_payload(
                scenario.certification_id,
                WITHDRAWAL_EFFECTIVE_DATE,
                mitigating_circumstances_flag=False,
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
    a.assert_fields(
        debts[0],
        {
            "tuition_component_cents": 2575455,
            "mha_component_cents": 719457,
            "principal_cents": 3294912,
            "outstanding_cents": 3294912,
        },
    )


def test_reconciliation_leaves_the_tuition_and_fee_report_untouched(api, baseline):
    """Only the first waterfall step is replaced, so the priced report still stands.

    PRD: "The covered tuition is rebuilt by replacing only the first step of the
    waterfall and rerunning the rest unchanged."

    Design: Difficulty/dual_variant_calc/covered_tuition_as_certified_vs_as_reconciled_money_divergence
    """
    scenario = build_paid_certification(
        api,
        baseline,
        tuition_amount_cents=2790000,
        mha_amount_cents=776444,
        posted_on=c.CLOCK_START_DATE,
    )
    set_clock_to(api, WITHDRAWAL_REPORTED_DATE)
    change_report = get_success_data(
        api.create_enrollment_change_report(
            f.complete_withdrawal_payload(
                scenario.certification_id,
                WITHDRAWAL_EFFECTIVE_DATE,
                mitigating_circumstances_flag=False,
            ),
            baseline.sco_headers,
        )
    )
    get_success_data(
        api.reconcile_change_report(change_report["id"], {}, baseline.sup_headers)
    )

    report = get_success_data(
        api.get_tuition_fee_report(scenario.tuition_report_id, baseline.sup_headers)
    )
    a.assert_fields(
        report,
        {
            "gross_tuition_cents": c.GROSS_TUITION_CENTS,
            "net_covered_cents": c.CANONICAL_NET_COVERED_CENTS,
            "status": c.TUITION_REPORT_STATUS_REPORTED,
        },
    )


# ─── Entitlement under the two bases ──────────────────────────────────
def test_certifying_charges_the_whole_period_with_a_single_rounding(api, baseline):
    """The certify-time entitlement charge rounds once at one tier.

    PRD: "At certification, `entitlement_days_charged` is a single rounding over
    the whole inclusive period at a single tier: multiply `certified_days` by
    `rop_tier_pct`, divide by 100, and round half up."

    Design: Difficulty/dual_variant_calc/entitlement_days_calendar_full_term_vs_prorated_on_change
    """
    scenario = build_certified_certification(api, baseline)

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_whole_days(certification, "certified_days", "entitlement_days_charged")
    a.assert_fields(
        certification,
        {
            "certified_days": c.CANONICAL_CERTIFIED_DAYS,
            "rop_tier_pct": 100,
            "entitlement_days_charged": 110,
        },
    )
    student = read_student(api, baseline.sco_headers, scenario.student_id)
    assert student["entitlement_days_remaining"] == 970
    a.assert_entitlement_ledger_balances(student, 110)


def test_reconciling_a_reduction_rounds_each_side_of_the_change_separately(
    api, baseline
):
    """The prorated charge is 87 days, not the 66 a single rounding would give.

    PRD: "Re-running the single-rounding certify-time rule at the new tier would
    give a materially different answer — for a 110-day term reduced from tier 100
    to tier 60 on day 53, the prorated rule charges 52 plus 35, that is 87 days,
    where a single rounding at the new tier would charge 66."

    Design: Difficulty/dual_variant_calc/entitlement_days_calendar_full_term_vs_prorated_on_change
    """
    scenario = build_certified_certification(api, baseline)
    set_clock_to(api, REDUCTION_REPORTED_DATE)
    change_report = get_success_data(
        api.create_enrollment_change_report(
            f.credit_hour_reduction_payload(
                scenario.certification_id,
                REDUCTION_EFFECTIVE_DATE,
                new_credit_hours=7,
                new_credit_hours_online=0,
            ),
            baseline.sco_headers,
        )
    )
    get_success_data(
        api.reconcile_change_report(change_report["id"], {}, baseline.sup_headers)
    )

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_fields(
        certification,
        {
            "status": c.CERT_STATUS_CERTIFIED,
            "amount_basis": c.AMOUNT_BASIS_AS_RECONCILED,
            "rate_of_pursuit_pct": 58,
            "rop_tier_pct": 60,
            "training_time": c.TRAINING_TIME_HALF,
            "entitlement_days_charged": 87,
        },
    )
    assert certification["entitlement_days_charged"] != 66, (
        "A single rounding at the new tier would charge 66 days, which is wrong"
    )
    student = read_student(api, baseline.sco_headers, scenario.student_id)
    assert student["entitlement_days_remaining"] == 993
    a.assert_entitlement_ledger_balances(student, 87)


def test_reconciled_housing_prices_each_segment_on_its_own_side_of_the_change(
    api, baseline
):
    """Pre-change segments keep the pre-change rate after a credit-hour reduction.

    PRD: "Second, each segment is priced at the rate appropriate to its side of
    the change: a segment whose end falls before `effective_date` is priced at
    the **pre-change** `mha_monthly_rate_cents`, and a segment whose start falls
    on or after `effective_date` is priced at the **post-change** rate."

    Design: Difficulty/dual_variant_calc/entitlement_days_calendar_full_term_vs_prorated_on_change
    """
    scenario = build_certified_certification(api, baseline)
    certified_total = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )["mha_term_total_cents"]
    assert certified_total == 776444

    set_clock_to(api, REDUCTION_REPORTED_DATE)
    change_report = get_success_data(
        api.create_enrollment_change_report(
            f.credit_hour_reduction_payload(
                scenario.certification_id,
                REDUCTION_EFFECTIVE_DATE,
                new_credit_hours=7,
                new_credit_hours_online=0,
            ),
            baseline.sco_headers,
        )
    )
    validate_success(
        api.reconcile_change_report(change_report["id"], {}, baseline.sup_headers)
    )

    certification = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    assert certification["mha_term_total_cents"] == 618306
