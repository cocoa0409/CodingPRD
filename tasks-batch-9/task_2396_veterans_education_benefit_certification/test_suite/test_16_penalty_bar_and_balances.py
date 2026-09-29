"""The statutory penalty bar, and the exact edge of a debt balance.

While VA's money is outstanding the bursar's punitive levers are all shut; once
the disbursement posts they open. Separately, a repayment one cent over the
balance is refused rather than truncated.
"""

import pytest
from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers.fixtures import (
    build_certified_certification,
    build_paid_certification,
    read_certification,
    read_student,
    record_va_payment,
    set_clock_to,
)
from test_helpers.test_users import BURSAR_HEADERS

PENALTY_AMOUNT_CENTS = 5000
TUITION_CHARGE_CENTS = 5000
PAID_TUITION_CENTS = 2790000
PAID_MHA_CENTS = 776444

CHANGE_DATE_PAST_THE_PERIOD = "2026-12-20"
WITHDRAWAL_REPORTED_ON = "2026-09-05"
WITHDRAWAL_EFFECTIVE_DATE = "2026-09-15"


# ─── The penalty bar while VA's money is outstanding ───────────────────
def _post_charge(api, student_id, term_id, charge_type):
    return api.create_student_account_charge(
        f.student_account_charge_payload(
            student_id, term_id, charge_type, PENALTY_AMOUNT_CENTS
        ),
        BURSAR_HEADERS,
    )


def _penalty_attempt(api, scenario, surface):
    """Aim one of the four punitive surfaces at a protected student."""
    if surface == "late_fee":
        return _post_charge(
            api, scenario.student_id, scenario.base.term_id, c.CHARGE_TYPE_LATE_FEE
        )
    if surface == "reinstatement_fee":
        return _post_charge(
            api,
            scenario.student_id,
            scenario.base.term_id,
            c.CHARGE_TYPE_REINSTATEMENT_FEE,
        )
    if surface == "registration_hold":
        return api.set_account_hold(
            scenario.student_id,
            f.account_hold_payload(c.ACCOUNT_HOLD_REGISTRATION_HOLD),
            BURSAR_HEADERS,
        )
    return api.create_enrollment_change_report(
        f.complete_withdrawal_payload(
            scenario.certification_id,
            WITHDRAWAL_EFFECTIVE_DATE,
            punitive_grade_flag=True,
        ),
        scenario.base.sco_headers,
    )


@pytest.mark.parametrize(
    "surface",
    ["late_fee", "reinstatement_fee", "registration_hold", "punitive_change_report"],
)
def test_every_punitive_surface_is_shut_while_the_student_is_protected(
    api, baseline, surface
):
    """All four levers answer with the same statutory refusal.

    PRD: "While the student's live protection predicate is true, no penalty charge
    may be posted, no registration hold may be set, and no change report may carry
    a punitive-grade intent, else `ERR_PROTECTED_STUDENT_PENALTY` (422)."

    Design: Corner/validations/a_protected_student_cannot_be_penalized_until_the_va_payment_posts
    """
    scenario = build_certified_certification(api, baseline)

    response = _penalty_attempt(api, scenario, surface)
    validate_error(response, "ERR_PROTECTED_STUDENT_PENALTY", expected_status=422)

    student = read_student(api, baseline.sco_headers, scenario.student_id)
    assert student["account_hold_status"] == c.ACCOUNT_HOLD_NONE
    _rows, meta = validate_paginated(
        api.list_enrollment_change_reports(baseline.sco_headers)
    )
    assert meta["total_count"] == 0
    assert (
        read_certification(api, baseline.sco_headers, scenario.certification_id)[
            "status"
        ]
        == c.CERT_STATUS_CERTIFIED
    )


def test_an_ordinary_tuition_charge_is_never_a_penalty(api, baseline):
    """The same amount posts normally when it is not punitive in character.

    PRD: "The statutory bar of §3.2 lands here — a `LATE_FEE` or a
    `REINSTATEMENT_FEE` may not be posted while the student's live protection
    predicate is true, and the attempt is refused with
    `ERR_PROTECTED_STUDENT_PENALTY`, while a `TUITION` or `MANDATORY_FEE` charge is
    unaffected and may always be posted."

    Design: Corner/validations/a_protected_student_cannot_be_penalized_until_the_va_payment_posts
    """
    scenario = build_certified_certification(api, baseline)

    charge = get_success_data(
        api.create_student_account_charge(
            f.student_account_charge_payload(
                scenario.student_id,
                baseline.term_id,
                c.CHARGE_TYPE_TUITION,
                TUITION_CHARGE_CENTS,
            ),
            BURSAR_HEADERS,
        ),
        expected_status=201,
    )
    a.assert_fields(
        charge,
        {
            "charge_type": c.CHARGE_TYPE_TUITION,
            "amount_cents": TUITION_CHARGE_CENTS,
            "status": c.CHARGE_STATUS_POSTED,
        },
    )


def test_the_refused_late_fee_posts_once_the_disbursement_is_recorded(api, baseline):
    """Recording VA's payment rewrites the snapshot and reopens the lever.

    PRD: "Accordingly, every operation capable of changing any of the three
    conjuncts rewrites the snapshot for the affected student or students: verifying
    a certificate, expiring a certificate, certifying an enrollment, recording VA's
    disbursement against a certification, and advancing the logical clock — the
    last of which rewrites it for every student in the system, since the clock's
    movement can push any of them past their `protected_until`."

    Design: Corner/validations/a_protected_student_cannot_be_penalized_until_the_va_payment_posts
    """
    scenario = build_certified_certification(api, baseline)
    validate_error(
        _post_charge(
            api, scenario.student_id, baseline.term_id, c.CHARGE_TYPE_LATE_FEE
        ),
        "ERR_PROTECTED_STUDENT_PENALTY",
        expected_status=422,
    )

    record_va_payment(
        api,
        scenario.certification_id,
        PAID_TUITION_CENTS,
        PAID_MHA_CENTS,
        c.CLOCK_START_DATE,
    )

    charge = get_success_data(
        _post_charge(
            api, scenario.student_id, baseline.term_id, c.CHARGE_TYPE_LATE_FEE
        ),
        expected_status=201,
    )
    a.assert_fields(
        charge,
        {
            "charge_type": c.CHARGE_TYPE_LATE_FEE,
            "status": c.CHARGE_STATUS_POSTED,
        },
    )
    assert (
        read_student(api, baseline.sco_headers, scenario.student_id)[
            "benefit_payment_protected"
        ]
        is False
    )


# ─── Change dates and repayment balances ──────────────────────────────
def test_a_change_effective_after_the_certified_period_is_refused(api, baseline):
    """Nine days past the last certified day is outside the period, inclusive or not.

    PRD: "On change report creation, `effective_date` falls within
    `term_start_certified` through `term_end_certified` inclusive, else
    `ERR_CHANGE_DATE_OUTSIDE_TERM` (422)."

    Design: Corner/validations/change_dates_outside_the_certified_period_and_overpayments_beyond_the_balance_are_rejected
    """
    scenario = build_certified_certification(api, baseline)

    response = api.create_enrollment_change_report(
        f.complete_withdrawal_payload(
            scenario.certification_id, CHANGE_DATE_PAST_THE_PERIOD
        ),
        baseline.sco_headers,
    )
    validate_error(response, "ERR_CHANGE_DATE_OUTSIDE_TERM", expected_status=422)

    _rows, meta = validate_paginated(
        api.list_enrollment_change_reports(baseline.sco_headers)
    )
    assert meta["total_count"] == 0


def _withdrawal_debt(api, baseline):
    """A timely mid-term withdrawal, reconciled into exactly one student debt."""
    scenario = build_paid_certification(api, baseline, PAID_TUITION_CENTS, PAID_MHA_CENTS)
    set_clock_to(api, WITHDRAWAL_REPORTED_ON)
    change_report = get_success_data(
        api.create_enrollment_change_report(
            f.complete_withdrawal_payload(
                scenario.certification_id, WITHDRAWAL_EFFECTIVE_DATE
            ),
            baseline.sco_headers,
        ),
        expected_status=201,
    )
    get_success_data(
        api.reconcile_change_report(change_report["id"], {}, baseline.sup_headers)
    )
    rows, meta = validate_paginated(api.list_benefit_debts(BURSAR_HEADERS))
    assert meta["total_count"] == 1
    return scenario, rows[0]


def test_a_legitimate_mid_term_withdrawal_opens_the_amendment(api, baseline):
    """A date inside the certified period is accepted and suspends the amounts.

    PRD: "The certification moves `CERTIFIED → AMENDMENT_PENDING`, and — importantly
    — its stored amounts stay on the `AS_CERTIFIED` basis for now; nothing is
    recomputed until a supervisor reconciles."

    Design: Corner/validations/change_dates_outside_the_certified_period_and_overpayments_beyond_the_balance_are_rejected
    """
    scenario = build_paid_certification(api, baseline, PAID_TUITION_CENTS, PAID_MHA_CENTS)
    set_clock_to(api, WITHDRAWAL_REPORTED_ON)

    change_report = get_success_data(
        api.create_enrollment_change_report(
            f.complete_withdrawal_payload(
                scenario.certification_id, WITHDRAWAL_EFFECTIVE_DATE
            ),
            baseline.sco_headers,
        ),
        expected_status=201,
    )
    assert change_report["status"] == c.CHANGE_REPORT_STATUS_REPORTED
    certification = read_certification(
        api, baseline.sco_headers, scenario.certification_id
    )
    a.assert_fields(
        certification,
        {
            "status": c.CERT_STATUS_AMENDMENT_PENDING,
            "amount_basis": c.AMOUNT_BASIS_AS_CERTIFIED,
        },
    )


def test_a_repayment_one_cent_over_the_balance_is_refused_not_truncated(api, baseline):
    """The overshoot leaves the debt exactly as it was.

    PRD: "On booking a repayment, `amount_cents` does not exceed the debt's
    `outstanding_cents`, else `ERR_REPAYMENT_EXCEEDS_BALANCE` (422)."

    Design: Corner/validations/change_dates_outside_the_certified_period_and_overpayments_beyond_the_balance_are_rejected
    """
    _scenario, debt = _withdrawal_debt(api, baseline)

    response = api.create_debt_repayment(
        debt["id"],
        f.repayment_payload(debt["outstanding_cents"] + 1),
        BURSAR_HEADERS,
    )
    validate_error(response, "ERR_REPAYMENT_EXCEEDS_BALANCE", expected_status=422)

    unchanged = get_success_data(api.get_benefit_debt(debt["id"], BURSAR_HEADERS))
    a.assert_fields(
        unchanged,
        {
            "repaid_cents": 0,
            "outstanding_cents": debt["outstanding_cents"],
            "collection_status": c.DEBT_COLLECTION_OPEN,
        },
    )


def test_a_repayment_of_exactly_the_balance_settles_the_debt_in_one_step(api, baseline):
    """The two buckets fill exactly and the balance reaches zero.

    PRD: "The debt's `collection_status` then becomes `SATISFIED` when
    `outstanding_cents` has reached 0 and `PARTIALLY_REPAID` otherwise, so a payment
    that exactly clears the balance settles the debt in one step whether it started
    at `OPEN` or at `PARTIALLY_REPAID`."

    Design: Corner/validations/change_dates_outside_the_certified_period_and_overpayments_beyond_the_balance_are_rejected
    """
    _scenario, debt = _withdrawal_debt(api, baseline)

    settled = get_success_data(
        api.create_debt_repayment(
            debt["id"], f.repayment_payload(debt["outstanding_cents"]), BURSAR_HEADERS
        )
    )
    a.assert_fields(
        settled,
        {
            "collection_status": c.DEBT_COLLECTION_SATISFIED,
            "repaid_cents": debt["principal_cents"],
            "tuition_repaid_cents": debt["tuition_component_cents"],
            "mha_repaid_cents": debt["mha_component_cents"],
            "outstanding_cents": 0,
        },
    )


def test_settling_the_debt_clears_the_students_open_principal(api, baseline):
    """The student-side ledger falls by exactly what was paid.

    PRD: "When `debtor_type` is `STUDENT`, the student's
    `open_debt_principal_cents` falls by the paid `amount_cents`."

    Design: Corner/validations/change_dates_outside_the_certified_period_and_overpayments_beyond_the_balance_are_rejected
    """
    scenario, debt = _withdrawal_debt(api, baseline)
    assert debt["debtor_type"] == c.DEBTOR_TYPE_STUDENT

    get_success_data(
        api.create_debt_repayment(
            debt["id"], f.repayment_payload(debt["outstanding_cents"]), BURSAR_HEADERS
        )
    )

    student = read_student(api, baseline.sco_headers, scenario.student_id)
    assert student["open_debt_principal_cents"] == 0
