"""Lifecycles that loop, fork and re-enter rather than running once forward.

A certificate of eligibility cycles through verification and expiry alongside an
independent registration-hold dimension, an agency review forks three ways with a
different effect on the program in each branch, and a certification can run the
revision loop and then re-enter through an amendment.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers.fixtures import (
    build_submitted_certification,
    certify_certification,
    create_catalog_version,
    create_program,
    create_student,
    price_certification,
    read_audit_entries,
    read_certification,
    read_student,
    set_clock_to,
    submit_certification,
)
from test_helpers.test_users import BURSAR_HEADERS, SAA_HEADERS, VA_HEADERS

REVERIFICATION_DATE = "2026-09-10"
REVERIFIED_COE_ISSUED_ON = "2026-08-20"
REVERIFIED_COE_REFERENCE = "COE-2026-88431"

CONDITIONS_NOTE = "Publish the refund policy in the printed catalog by 2027-01-31"

REDUCTION_EFFECTIVE_DATE = "2026-10-15"
REDUCTION_REPORTED_DATE = "2026-10-20"


# ─── The certificate cycle and the parallel hold dimension ────────────
def test_verifying_a_certificate_opens_a_ninety_day_protection_window(api, officials):
    """coe_verified_on is stamped from the clock and protected_until is 90 days later.

    PRD: "It then opens the statutory protection window by setting
    `protected_until` to 90 days after `coe_verified_on`, and finally recomputes
    the student's `benefit_payment_protected` snapshot."

    Design: Difficulty/non_linear_state_machine/student_coe_cycle_with_parallel_account_hold_dimension
    """
    student_id = create_student(api, officials.sco_headers)

    verified = get_success_data(
        api.verify_coe(student_id, f.verify_coe_payload(), officials.sco_headers)
    )
    a.assert_fields(
        verified,
        {
            "coe_status": c.COE_STATUS_VERIFIED,
            "coe_verified_on": c.CLOCK_START_DATE,
            "protected_until": "2026-10-30",
            "verified_document_reference": c.COE_REFERENCE,
        },
    )


def test_the_hold_dimension_and_the_certificate_dimension_stay_independent(
    api, officials
):
    """Holds never move coe_status and certificate moves never move the hold.

    PRD: "A `VeteranStudent` carries `coe_status`, which tracks entitlement
    verification, alongside `account_hold_status`, which tracks the bursar's
    registration hold; setting or releasing a hold leaves `coe_status` untouched,
    and verifying or expiring a certificate of eligibility leaves
    `account_hold_status` untouched."

    Design: Difficulty/non_linear_state_machine/student_coe_cycle_with_parallel_account_hold_dimension
    """
    student_id = create_student(api, officials.sco_headers)
    get_success_data(
        api.verify_coe(student_id, f.verify_coe_payload(), officials.sco_headers)
    )

    held = get_success_data(
        api.set_account_hold(
            student_id,
            f.account_hold_payload(c.ACCOUNT_HOLD_REGISTRATION_HOLD),
            BURSAR_HEADERS,
        )
    )
    a.assert_fields(
        held,
        {
            "account_hold_status": c.ACCOUNT_HOLD_REGISTRATION_HOLD,
            "coe_status": c.COE_STATUS_VERIFIED,
        },
    )

    expired = get_success_data(api.expire_coe(student_id, {}, VA_HEADERS))
    a.assert_fields(
        expired,
        {
            "coe_status": c.COE_STATUS_EXPIRED,
            "account_hold_status": c.ACCOUNT_HOLD_REGISTRATION_HOLD,
            "coe_verified_on": c.CLOCK_START_DATE,
            "protected_until": "2026-10-30",
        },
    )

    released = get_success_data(
        api.set_account_hold(
            student_id, f.account_hold_payload(c.ACCOUNT_HOLD_NONE), BURSAR_HEADERS
        )
    )
    a.assert_fields(
        released,
        {
            "account_hold_status": c.ACCOUNT_HOLD_NONE,
            "coe_status": c.COE_STATUS_EXPIRED,
        },
    )


def test_reverification_restarts_the_window_from_the_new_verification_date(
    api, officials
):
    """A re-verified student gets a fresh 90 days, not the remainder of the old.

    PRD: "The one thing that differs is that `protected_until` restarts from the
    new `coe_verified_on`: a re-verified student gets a fresh 90 days measured
    from the new verification date, not the remainder of the old window."

    Design: Difficulty/non_linear_state_machine/student_coe_cycle_with_parallel_account_hold_dimension
    """
    student_id = create_student(api, officials.sco_headers)
    get_success_data(
        api.verify_coe(student_id, f.verify_coe_payload(), officials.sco_headers)
    )
    get_success_data(api.expire_coe(student_id, {}, VA_HEADERS))
    set_clock_to(api, REVERIFICATION_DATE)

    reverified = get_success_data(
        api.verify_coe(
            student_id,
            f.verify_coe_payload(
                coe_issued_on=REVERIFIED_COE_ISSUED_ON,
                verified_document_reference=REVERIFIED_COE_REFERENCE,
            ),
            officials.sco_headers,
        )
    )
    a.assert_fields(
        reverified,
        {
            "coe_status": c.COE_STATUS_VERIFIED,
            "coe_verified_on": REVERIFICATION_DATE,
            "protected_until": "2026-12-09",
            "coe_issued_on": REVERIFIED_COE_ISSUED_ON,
            "verified_document_reference": REVERIFIED_COE_REFERENCE,
        },
    )


def test_a_verified_certificate_alone_does_not_protect_the_student(api, officials):
    """Without a live unpaid certification the third conjunct is never satisfied.

    PRD: "The service reduces that statute to a three-part predicate that must
    all hold at once for a student to count as protected: their `coe_status` is
    `VERIFIED`; the current logical clock date is on or before their
    `protected_until`, with the boundary day itself still inside the window; and
    at least one enrollment certification exists for that student whose `status`
    is `CERTIFIED` or `AMENDMENT_PENDING` and whose `tuition_payment_posted_on`
    is still null."

    Design: Difficulty/non_linear_state_machine/student_coe_cycle_with_parallel_account_hold_dimension
    """
    student_id = create_student(api, officials.sco_headers)

    verified = get_success_data(
        api.verify_coe(student_id, f.verify_coe_payload(), officials.sco_headers)
    )
    assert verified["benefit_payment_protected"] is False

    get_success_data(api.expire_coe(student_id, {}, VA_HEADERS))
    set_clock_to(api, REVERIFICATION_DATE)
    reverified = get_success_data(
        api.verify_coe(
            student_id,
            f.verify_coe_payload(
                coe_issued_on=REVERIFIED_COE_ISSUED_ON,
                verified_document_reference=REVERIFIED_COE_REFERENCE,
            ),
            officials.sco_headers,
        )
    )
    assert reverified["benefit_payment_protected"] is False


# ─── The three-way agency fork ────────────────────────────────────────
def _three_programs_pending_review(api, officials):
    """Three programs, each with one catalog version awaiting the agency."""
    programs = {}
    for code, name in (
        ("PROG-A", "Accounting BS"),
        ("PROG-B", "Biology BS"),
        ("PROG-C", "Chemistry BS"),
    ):
        program_id = create_program(
            api, officials.sup_headers, program_code=code, name=name
        )
        catalog_id = create_catalog_version(api, officials.sup_headers, program_id)
        get_success_data(
            api.submit_catalog_version_to_saa(catalog_id, {}, officials.sup_headers)
        )
        programs[code] = (program_id, catalog_id)
    return programs


def test_approval_pins_the_catalog_version_onto_the_program(api, officials):
    """The APPROVED branch is the one that unlocks certification.

    PRD: "The program is set to `approval_status` `APPROVED`, and the program's
    `approved_catalog_version_id` is pinned to this catalog version's `id`."

    Design: Difficulty/non_linear_state_machine/catalog_pending_saa_three_way_fork_with_divergent_program_effects
    """
    programs = _three_programs_pending_review(api, officials)
    program_id, catalog_id = programs["PROG-A"]

    decided = get_success_data(
        api.record_saa_decision(
            catalog_id, f.saa_decision_payload(c.SAA_DECISION_APPROVED), SAA_HEADERS
        )
    )
    a.assert_fields(
        decided,
        {"review_status": c.CATALOG_REVIEW_APPROVED, "conditions_note": None},
    )
    program = get_success_data(api.get_program(program_id, officials.sup_headers))
    a.assert_fields(
        program,
        {
            "approval_status": c.PROGRAM_STATUS_APPROVED,
            "approved_catalog_version_id": catalog_id,
        },
    )


def test_conditional_approval_stores_the_note_and_sets_its_own_posture(api, officials):
    """APPROVED_WITH_CONDITIONS pins the catalog but leaves the program CONDITIONAL.

    PRD: "A `decision` of `APPROVED_WITH_CONDITIONS` moves the version
    `PENDING_SAA → APPROVED_WITH_CONDITIONS` and stores the accompanying
    `conditions_note`; that note is required on this branch, and its absence is a
    malformed request refused with `ERR_INVALID_REQUEST`."

    Design: Difficulty/non_linear_state_machine/catalog_pending_saa_three_way_fork_with_divergent_program_effects
    """
    programs = _three_programs_pending_review(api, officials)
    program_id, catalog_id = programs["PROG-B"]

    decided = get_success_data(
        api.record_saa_decision(
            catalog_id,
            f.saa_decision_payload(
                c.SAA_DECISION_APPROVED_WITH_CONDITIONS,
                conditions_note=CONDITIONS_NOTE,
            ),
            SAA_HEADERS,
        )
    )
    a.assert_fields(
        decided,
        {
            "review_status": c.CATALOG_REVIEW_APPROVED_WITH_CONDITIONS,
            "conditions_note": CONDITIONS_NOTE,
        },
    )
    program = get_success_data(api.get_program(program_id, officials.sup_headers))
    a.assert_fields(
        program,
        {
            "approval_status": c.PROGRAM_STATUS_CONDITIONAL,
            "approved_catalog_version_id": catalog_id,
        },
    )


def test_rejection_unpins_the_catalog_rather_than_pinning_it(api, officials):
    """The REJECTED branch drops the program back to DRAFT with nothing pinned.

    PRD: "Here the program is set to `approval_status` `DRAFT` and its
    `approved_catalog_version_id` is cleared to null: rejection unpins the
    catalog rather than pinning it."

    Design: Difficulty/non_linear_state_machine/catalog_pending_saa_three_way_fork_with_divergent_program_effects
    """
    programs = _three_programs_pending_review(api, officials)
    program_id, catalog_id = programs["PROG-C"]

    decided = get_success_data(
        api.record_saa_decision(
            catalog_id, f.saa_decision_payload(c.SAA_DECISION_REJECTED), SAA_HEADERS
        )
    )
    assert decided["review_status"] == c.CATALOG_REVIEW_REJECTED
    program = get_success_data(api.get_program(program_id, officials.sup_headers))
    a.assert_fields(
        program,
        {
            "approval_status": c.PROGRAM_STATUS_DRAFT,
            "approved_catalog_version_id": None,
        },
    )


def test_a_rejected_catalog_reenters_review_and_takes_the_program_with_it(
    api, officials
):
    """Resubmission pushes both rows back to PENDING_SAA.

    PRD: "Whatever the program's `approval_status` was — `DRAFT`, `APPROVED`,
    `CONDITIONAL` or `SUSPENDED` — it is set to `PENDING_SAA`, because an open
    agency re-review suspends the program's certifiable posture regardless of
    where it stood before."

    Design: Difficulty/non_linear_state_machine/catalog_pending_saa_three_way_fork_with_divergent_program_effects
    """
    programs = _three_programs_pending_review(api, officials)
    program_id, catalog_id = programs["PROG-C"]
    get_success_data(
        api.record_saa_decision(
            catalog_id, f.saa_decision_payload(c.SAA_DECISION_REJECTED), SAA_HEADERS
        )
    )

    resubmitted = get_success_data(
        api.submit_catalog_version_to_saa(catalog_id, {}, officials.sup_headers)
    )
    assert resubmitted["review_status"] == c.CATALOG_REVIEW_PENDING_SAA
    program = get_success_data(api.get_program(program_id, officials.sup_headers))
    assert program["approval_status"] == c.PROGRAM_STATUS_PENDING_SAA


# ─── The revision loop and the amendment re-entry ─────────────────────
def _revise_to_nine_credit_hours(api, baseline):
    """Submit, have the certification returned, revise it down to nine credit hours."""
    scenario = build_submitted_certification(api, baseline)
    returned = get_success_data(
        api.return_certification(
            scenario.certification_id,
            f.return_certification_payload(),
            baseline.sup_headers,
        )
    )
    revised = get_success_data(
        api.update_enrollment_certification(
            scenario.certification_id,
            {"credit_hours_total": 9, "credit_hours_online": 0},
            baseline.sco_headers,
        )
    )
    scenario.certification_version = revised["version"]
    return scenario, returned, revised


def _recertify_after_revision(api, baseline, scenario):
    """Reprice the revised certification, resubmit it and certify it."""
    _, new_version = price_certification(
        api, scenario.certification_id, scenario.certification_version
    )
    scenario.certification_version = new_version
    submit_certification(api, baseline.sco_headers, scenario.certification_id)
    return certify_certification(
        api, baseline.sup_headers, scenario.certification_id
    )


def test_returning_then_revising_reopens_the_certification_as_draft(api, baseline):
    """The return reason is stored, then cleared when the revision lands.

    PRD: "A revision applied while it sits at `RETURNED` moves it
    `RETURNED → DRAFT` and clears the stored `return_reason`, which is how a
    rejected certification re-enters the drafting stage."

    Design: Difficulty/non_linear_state_machine/certification_revision_loop_then_amendment_reentry
    """
    _scenario, returned, revised = _revise_to_nine_credit_hours(api, baseline)

    a.assert_fields(
        returned,
        {
            "status": c.CERT_STATUS_RETURNED,
            "return_reason": "Registrar shows 9 credit hours, not 12",
        },
    )
    a.assert_fields(
        revised,
        {
            "status": c.CERT_STATUS_DRAFT,
            "return_reason": None,
            "rate_of_pursuit_pct": 75,
            "rop_tier_pct": 80,
            "training_time": c.TRAINING_TIME_THREE_QUARTER,
        },
    )


def test_the_revised_load_drives_the_certified_housing_and_entitlement(api, baseline):
    """Certifying after the revision prices the whole term at the revised tier.

    PRD: "A revision may supply any subset of `credit_hours_total`,
    `credit_hours_online`, `term_start_certified` and `term_end_certified`,
    overwrites whichever of them it supplies, and then recomputes the whole
    derived block above from the resulting values."

    Design: Difficulty/non_linear_state_machine/certification_revision_loop_then_amendment_reentry
    """
    scenario, _returned, _revised = _revise_to_nine_credit_hours(api, baseline)

    certified = _recertify_after_revision(api, baseline, scenario)
    a.assert_fields(
        certified,
        {
            "status": c.CERT_STATUS_CERTIFIED,
            "mha_monthly_rate_cents": 170960,
            "mha_term_total_cents": 621154,
            "entitlement_days_charged": 88,
        },
    )
    student = read_student(api, baseline.sco_headers, scenario.student_id)
    assert student["entitlement_days_remaining"] == 992


def test_a_reconciled_reduction_returns_the_certification_to_certified(api, baseline):
    """The amendment cycle closes back at CERTIFIED with no debt raised.

    PRD: "Then the housing total, the covered tuition and the entitlement charge
    are recomputed under the reconciled variants described below, `amount_basis`
    is set to `AS_RECONCILED`, and the certification's `status` is set by
    `change_type`: a `CREDIT_HOUR_REDUCTION` or a `TERM_DATE_CHANGE` returns it
    `AMENDMENT_PENDING → CERTIFIED`, so the cycle
    `CERTIFIED → AMENDMENT_PENDING → CERTIFIED` may repeat for successive
    changes, while a `COMPLETE_WITHDRAWAL` moves it
    `AMENDMENT_PENDING → TERMINATED`, which is terminal."

    Design: Difficulty/non_linear_state_machine/certification_revision_loop_then_amendment_reentry
    """
    scenario, _returned, _revised = _revise_to_nine_credit_hours(api, baseline)
    _recertify_after_revision(api, baseline, scenario)

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
    opened = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    assert opened["status"] == c.CERT_STATUS_AMENDMENT_PENDING
    assert opened["amount_basis"] == c.AMOUNT_BASIS_AS_CERTIFIED

    get_success_data(
        api.reconcile_change_report(change_report["id"], {}, baseline.sup_headers)
    )
    reconciled = read_certification(
        api, baseline.sup_headers, scenario.certification_id
    )
    a.assert_fields(
        reconciled,
        {
            "status": c.CERT_STATUS_CERTIFIED,
            "amount_basis": c.AMOUNT_BASIS_AS_RECONCILED,
            "rop_tier_pct": 60,
            "entitlement_days_charged": 77,
            "mha_term_total_cents": 544222,
        },
    )
    student = read_student(api, baseline.sco_headers, scenario.student_id)
    assert student["entitlement_days_remaining"] == 1003
    debts = get_success_data(
        api.list_benefit_debts(
            baseline.sup_headers, {"certification_id": scenario.certification_id}
        )
    )
    assert debts == [], f"No debt is due when nothing was overpaid, got {debts}"


def test_the_audit_trail_records_the_loop_and_the_amendment_in_order(api, baseline):
    """Six entries in the order the events logically occurred.

    PRD: "The `sequence_index` is a per-certification counter that starts at 1
    and is assigned in ascending `created_at` order of the entries on that
    certification."

    Design: Difficulty/non_linear_state_machine/certification_revision_loop_then_amendment_reentry
    """
    scenario, _returned, _revised = _revise_to_nine_credit_hours(api, baseline)
    _recertify_after_revision(api, baseline, scenario)
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

    entries = read_audit_entries(
        api, baseline.sup_headers, scenario.certification_id, {"limit": 100}
    )
    a.assert_event_sequence(
        entries,
        [
            c.EVENT_CERTIFICATION_SUBMITTED,
            c.EVENT_CERTIFICATION_RETURNED,
            c.EVENT_CERTIFICATION_SUBMITTED,
            c.EVENT_CERTIFICATION_CERTIFIED,
            c.EVENT_AMENDMENT_OPENED,
            c.EVENT_AMENDMENT_RECONCILED,
        ],
    )
    for entry in entries:
        a.assert_audit_entry_shape(entry)
