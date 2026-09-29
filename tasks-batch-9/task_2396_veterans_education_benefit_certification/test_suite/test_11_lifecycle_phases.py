"""Where each machine starts, which edges it will walk, and which it refuses.

Declared openings, the single-edge closes, the certification's phase-specific
refusals, the absolute terminal lockdown, the non-idempotent replays, the catalog
review cycle, and the certificate of eligibility's own cycle.
"""

import pytest
from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers.fixtures import (
    create_agreement,
    create_catalog_version,
    create_certification,
    create_program,
    create_student,
    create_verified_student,
    price_certification,
    read_agreement,
    read_certification,
    read_student,
    set_clock_to,
    submit_certification,
)
from test_helpers.test_users import BURSAR_HEADERS, SAA_HEADERS, VA_HEADERS

SECOND_CATALOG_YEAR = "2027-2028"
SECOND_WINDOW_START = "2027-07-01"
SECOND_WINDOW_END = "2028-07-01"
REVERIFY_DATE = "2026-09-10"
REVERIFY_REFERENCE = "COE-2026-88220"
FIRST_PROTECTED_UNTIL = "2026-10-30"
SECOND_PROTECTED_UNTIL = "2026-12-09"


# ─── Declared openings ────────────────────────────────────────────────
def test_a_fresh_agreement_opens_active_with_its_whole_pool_uncommitted(api, officials):
    """Nothing is committed until an award draws on the pool.

    PRD: "A new agreement opens with `status` `ACTIVE`, `pool_remaining_cents`
    equal to `annual_pool_cents`, and `participant_count` at 0."

    Design: Corner/state_machines/every_created_row_starts_in_its_declared_initial_state
    """
    agreement = get_success_data(
        api.create_yellow_ribbon_agreement(
            f.yellow_ribbon_agreement_payload(), officials.sup_headers
        ),
        expected_status=201,
    )
    a.assert_common_fields(agreement, expected_version=1)
    a.assert_fields(
        agreement,
        {
            "status": c.AGREEMENT_STATUS_ACTIVE,
            "annual_pool_cents": c.YR_ANNUAL_POOL_CENTS,
            "pool_remaining_cents": c.YR_ANNUAL_POOL_CENTS,
            "participant_count": 0,
        },
    )


def test_a_fresh_catalog_version_opens_at_draft_with_neither_note_written(
    api, officials
):
    """A version starts before the agency has seen it, so both notes are empty.

    PRD: "A new version opens with `review_status` at `DRAFT` and with both
    `conditions_note` and `suspension_reason` null."

    Design: Corner/state_machines/every_created_row_starts_in_its_declared_initial_state
    """
    program_id = create_program(api, officials.sup_headers)

    catalog = get_success_data(
        api.create_catalog_version(
            f.catalog_version_payload(program_id), officials.sup_headers
        ),
        expected_status=201,
    )
    a.assert_common_fields(catalog, expected_version=1)
    a.assert_fields(
        catalog,
        {
            "review_status": c.CATALOG_REVIEW_DRAFT,
            "conditions_note": None,
            "suspension_reason": None,
        },
    )


def test_a_fresh_term_opens_at_open(api, officials):
    """A term is certifiable from the moment it is created.

    PRD: "A new term opens with `status` at `OPEN`."

    Design: Corner/state_machines/every_created_row_starts_in_its_declared_initial_state
    """
    term = get_success_data(
        api.create_academic_term(f.academic_term_payload(), officials.sup_headers),
        expected_status=201,
    )
    a.assert_common_fields(term, expected_version=1)
    assert term["status"] == c.TERM_STATUS_OPEN


def test_a_fresh_certification_opens_at_draft_on_no_amount_basis(api, baseline):
    """Until it is certified, no variant of the arithmetic has produced its amounts.

    PRD: "The new certification opens with `status` at `DRAFT` and `amount_basis`
    null; over its life its `status` moves among `DRAFT`, `SUBMITTED`, `RETURNED`,
    `CERTIFIED`, `AMENDMENT_PENDING`, `TERMINATED` and `VOID`, of which the last
    two are terminal."

    Design: Corner/state_machines/every_created_row_starts_in_its_declared_initial_state
    """
    student_id = create_student(api, baseline.sco_headers)

    certification = get_success_data(
        api.create_enrollment_certification(
            f.certification_payload(student_id, baseline.term_id, baseline.program_id),
            baseline.sco_headers,
        ),
        expected_status=201,
    )
    a.assert_fields(
        certification, {"status": c.CERT_STATUS_DRAFT, "amount_basis": None}
    )


def test_a_fresh_tuition_report_is_the_one_report_in_force(api, baseline):
    """The first report is immediately the report VA's pricing will be read from.

    PRD: "A report is created with `status` `REPORTED`, and in the same operation
    any earlier report for the same `certification_id` that was still `REPORTED` is
    moved `REPORTED → SUPERSEDED`, which is terminal — so a certification always
    has exactly one report in force and an arbitrarily long trail of superseded
    ones behind it."

    Design: Corner/state_machines/every_created_row_starts_in_its_declared_initial_state
    """
    student_id = create_student(api, baseline.sco_headers)
    certification_id, version = create_certification(
        api, baseline.sco_headers, student_id, baseline.term_id, baseline.program_id
    )

    report = get_success_data(
        api.create_tuition_fee_report(
            f.tuition_fee_report_payload(certification_id, version), BURSAR_HEADERS
        ),
        expected_status=201,
    )
    a.assert_common_fields(report, expected_version=1)
    assert report["status"] == c.TUITION_REPORT_STATUS_REPORTED
    in_force = get_success_data(
        api.list_tuition_fee_reports(
            BURSAR_HEADERS,
            {
                "certification_id": certification_id,
                "status": c.TUITION_REPORT_STATUS_REPORTED,
            },
        )
    )
    assert [row["id"] for row in in_force] == [report["id"]]


# ─── The single-edge closes ───────────────────────────────────────────
def test_closing_a_term_advances_it_exactly_one_step(api, officials):
    """OPEN to CLOSED is the whole of this machine.

    PRD: "Closing a term moves it `OPEN → CLOSED`, is reserved to
    `SupervisorySCO`, and cannot be repeated: a term already at `CLOSED` is
    refused with `ERR_TERM_ALREADY_CLOSED`."

    Design: Corner/state_machines/term_agreement_and_official_lifecycle_closes_advance_exactly_one_step
    """
    term = get_success_data(
        api.create_academic_term(f.academic_term_payload(), officials.sup_headers)
    )

    closed = get_success_data(
        api.close_academic_term(term["id"], {}, officials.sup_headers)
    )
    a.assert_fields(closed, {"status": c.TERM_STATUS_CLOSED, "version": 2})


def test_closing_an_agreement_advances_it_exactly_one_step(api, officials):
    """ACTIVE to CLOSED is the whole of this machine.

    PRD: "Closing an agreement moves it `ACTIVE → CLOSED`, and an agreement
    already at `CLOSED` cannot be closed again — that attempt is refused with
    `ERR_AGREEMENT_ALREADY_CLOSED`."

    Design: Corner/state_machines/term_agreement_and_official_lifecycle_closes_advance_exactly_one_step
    """
    agreement_id, version = create_agreement(api, officials.sup_headers)

    closed = get_success_data(
        api.close_yellow_ribbon_agreement(agreement_id, {}, officials.sup_headers)
    )
    a.assert_fields(
        closed, {"status": c.AGREEMENT_STATUS_CLOSED, "version": version + 1}
    )


def test_revoking_one_officials_credentials_leaves_the_other_active(api, officials):
    """Deactivation touches only the addressed row.

    PRD: "Revoking credentials moves an official `ACTIVE → INACTIVE`."

    Design: Corner/state_machines/term_agreement_and_official_lifecycle_closes_advance_exactly_one_step
    """
    deactivated = get_success_data(
        api.deactivate_certifying_official(officials.sco_id, {}, VA_HEADERS)
    )
    a.assert_fields(
        deactivated, {"status": c.OFFICIAL_STATUS_INACTIVE, "version": 2}
    )

    supervisor = get_success_data(
        api.get_certifying_official(officials.sup_id, VA_HEADERS)
    )
    a.assert_fields(
        supervisor, {"status": c.OFFICIAL_STATUS_ACTIVE, "version": 1}
    )


# ─── The certification's off-phase refusals ───────────────────────────
def test_certifying_a_draft_row_reports_that_it_was_never_submitted(api, baseline):
    """The first of the seven certify conditions fails, so nothing is charged.

    PRD: "The certification's own `status` must be `SUBMITTED`, else
    `ERR_CERTIFICATION_NOT_SUBMITTED`."

    Design: Corner/state_machines/certification_actions_taken_outside_their_phase_are_rejected
    """
    student_id = create_verified_student(api, baseline.sco_headers)
    certification_id, version = create_certification(
        api, baseline.sco_headers, student_id, baseline.term_id, baseline.program_id
    )
    price_certification(api, certification_id, version)

    response = api.certify_certification(certification_id, {}, baseline.sup_headers)
    validate_error(response, e.ERR_CERTIFICATION_NOT_SUBMITTED, 409)

    student = read_student(api, baseline.sco_headers, student_id)
    assert student["entitlement_days_remaining"] == c.ENTITLEMENT_DAYS_GRANTED


def test_returning_a_draft_row_reports_that_it_was_never_submitted(api, baseline):
    """Supervisory review has nothing to send back yet.

    PRD: "Returning it is a `SupervisorySCO` action available only while the
    `status` is `SUBMITTED` — anything else is refused with
    `ERR_CERTIFICATION_NOT_SUBMITTED` — and it takes the `return_reason` the
    supervisor wants the front-line official to act on."

    Design: Corner/state_machines/certification_actions_taken_outside_their_phase_are_rejected
    """
    student_id = create_verified_student(api, baseline.sco_headers)
    certification_id, _version = create_certification(
        api, baseline.sco_headers, student_id, baseline.term_id, baseline.program_id
    )

    response = api.return_certification(
        certification_id, f.return_certification_payload(), baseline.sup_headers
    )
    validate_error(response, e.ERR_CERTIFICATION_NOT_SUBMITTED, 409)

    certification = read_certification(api, baseline.sco_headers, certification_id)
    a.assert_fields(
        certification, {"status": c.CERT_STATUS_DRAFT, "return_reason": None}
    )


def _submitted_row(api, baseline):
    """One priced, submitted certification for a verified student."""
    student_id = create_verified_student(api, baseline.sco_headers)
    certification_id, version = create_certification(
        api, baseline.sco_headers, student_id, baseline.term_id, baseline.program_id
    )
    price_certification(api, certification_id, version)
    submit_certification(api, baseline.sco_headers, certification_id)
    return certification_id


def test_resubmitting_a_submitted_row_is_refused_as_not_submittable(api, baseline):
    """Submission is an edge out of DRAFT or RETURNED and nowhere else.

    PRD: "The certification's own `status` must be `DRAFT` or `RETURNED`, else
    `ERR_CERTIFICATION_NOT_SUBMITTABLE`."

    Design: Corner/state_machines/certification_actions_taken_outside_their_phase_are_rejected
    """
    certification_id = _submitted_row(api, baseline)

    response = api.submit_certification(certification_id, {}, baseline.sco_headers)
    validate_error(response, e.ERR_CERTIFICATION_NOT_SUBMITTABLE, 409)

    assert (
        read_certification(api, baseline.sco_headers, certification_id)["status"]
        == c.CERT_STATUS_SUBMITTED
    )


def test_revising_a_submitted_row_is_refused_as_not_editable(api, baseline):
    """A row under review is frozen until review hands it back.

    PRD: "Revision is permitted while the certification's `status` is `DRAFT` or
    `RETURNED`, and from any other status it is refused with
    `ERR_CERTIFICATION_NOT_EDITABLE`."

    Design: Corner/state_machines/certification_actions_taken_outside_their_phase_are_rejected
    """
    certification_id = _submitted_row(api, baseline)

    response = api.update_enrollment_certification(
        certification_id, {"credit_hours_total": 9}, baseline.sco_headers
    )
    validate_error(response, e.ERR_CERTIFICATION_NOT_EDITABLE, 409)

    certification = read_certification(api, baseline.sco_headers, certification_id)
    a.assert_fields(
        certification,
        {
            "status": c.CERT_STATUS_SUBMITTED,
            "credit_hours_total": c.FULL_TIME_CREDIT_HOURS,
        },
    )


def test_voiding_a_submitted_row_is_refused_as_not_editable(api, baseline):
    """Voiding shares the editable window rather than having one of its own.

    PRD: "Voiding is a `SupervisorySCO` action permitted from `DRAFT` or
    `RETURNED` and refused elsewhere with `ERR_CERTIFICATION_NOT_EDITABLE`."

    Design: Corner/state_machines/certification_actions_taken_outside_their_phase_are_rejected
    """
    certification_id = _submitted_row(api, baseline)

    response = api.void_certification(certification_id, {}, baseline.sup_headers)
    validate_error(response, e.ERR_CERTIFICATION_NOT_EDITABLE, 409)

    assert (
        read_certification(api, baseline.sco_headers, certification_id)["status"]
        == c.CERT_STATUS_SUBMITTED
    )


# ─── The terminal lockdown ────────────────────────────────────────────
def _voided_row(api, baseline):
    """A drafted certification driven straight to the terminal VOID state."""
    student_id = create_verified_student(api, baseline.sco_headers)
    certification_id, version = create_certification(
        api, baseline.sco_headers, student_id, baseline.term_id, baseline.program_id
    )
    price_certification(api, certification_id, version)
    voided = get_success_data(
        api.void_certification(certification_id, {}, baseline.sup_headers)
    )
    assert voided["status"] == c.CERT_STATUS_VOID
    return certification_id


@pytest.mark.parametrize(
    "operation",
    [
        "submit",
        "certify",
        "return",
        "void",
        "record_va_payment",
        "change_report",
    ],
)
def test_every_state_changing_operation_on_a_voided_row_is_refused(
    api, baseline, operation
):
    """The terminal check outranks the phase-specific code each call would draw.

    PRD: "Both terminal states are absolute: once a certification's `status` is
    `TERMINATED` or `VOID`, every state-changing operation against it —
    submitting, certifying, returning, voiding, recording a VA payment, or opening
    a further change in enrollment — is refused with `ERR_CERTIFICATION_TERMINAL`."

    Design: Corner/state_machines/a_voided_certification_refuses_every_state_changing_operation
    """
    certification_id = _voided_row(api, baseline)

    calls = {
        "submit": lambda: api.submit_certification(
            certification_id, {}, baseline.sco_headers
        ),
        "certify": lambda: api.certify_certification(
            certification_id, {}, baseline.sup_headers
        ),
        "return": lambda: api.return_certification(
            certification_id, f.return_certification_payload(), baseline.sup_headers
        ),
        "void": lambda: api.void_certification(
            certification_id, {}, baseline.sup_headers
        ),
        "record_va_payment": lambda: api.record_va_payment(
            certification_id,
            f.record_va_payment_payload(100000, 100000, c.CLOCK_START_DATE),
            VA_HEADERS,
        ),
        "change_report": lambda: api.create_enrollment_change_report(
            f.complete_withdrawal_payload(certification_id, c.TERM_START),
            baseline.sco_headers,
        ),
    }
    validate_error(calls[operation](), e.ERR_CERTIFICATION_TERMINAL, 409)


def test_a_voided_row_stays_readable_and_unmodified(api, baseline):
    """Refusing every write is not the same as refusing every read.

    PRD: "Both terminal states are absolute: once a certification's `status` is
    `TERMINATED` or `VOID`, every state-changing operation against it —
    submitting, certifying, returning, voiding, recording a VA payment, or opening
    a further change in enrollment — is refused with `ERR_CERTIFICATION_TERMINAL`."

    Design: Corner/state_machines/a_voided_certification_refuses_every_state_changing_operation
    """
    certification_id = _voided_row(api, baseline)
    api.record_va_payment(
        certification_id,
        f.record_va_payment_payload(100000, 100000, c.CLOCK_START_DATE),
        VA_HEADERS,
    )
    api.create_enrollment_change_report(
        f.complete_withdrawal_payload(certification_id, c.TERM_START),
        baseline.sco_headers,
    )

    certification = read_certification(api, baseline.sco_headers, certification_id)
    a.assert_fields(
        certification,
        {
            "status": c.CERT_STATUS_VOID,
            "credit_hours_total": c.FULL_TIME_CREDIT_HOURS,
            "tuition_payment_posted_on": None,
        },
    )
    reports = get_success_data(
        api.list_enrollment_change_reports(
            baseline.sup_headers, {"certification_id": certification_id}
        )
    )
    assert reports == []


# ─── Non-idempotent replays ───────────────────────────────────────────
def test_deactivating_an_already_inactive_official_is_refused(api, officials):
    """There is no reinstatement path, and no second deactivation either.

    PRD: "The operation is available only to `VaProcessingOffice`, and an official
    already sitting at `INACTIVE` cannot be deactivated again — that attempt is
    refused with `ERR_OFFICIAL_ALREADY_INACTIVE`."

    Design: Corner/state_machines/repeating_a_completed_lifecycle_step_returns_its_own_already_conflict
    """
    get_success_data(
        api.deactivate_certifying_official(officials.sco_id, {}, VA_HEADERS)
    )

    response = api.deactivate_certifying_official(officials.sco_id, {}, VA_HEADERS)
    validate_error(response, e.ERR_OFFICIAL_ALREADY_INACTIVE, 409)

    official = get_success_data(
        api.get_certifying_official(officials.sco_id, VA_HEADERS)
    )
    a.assert_fields(
        official, {"status": c.OFFICIAL_STATUS_INACTIVE, "version": 2}
    )


def test_reverifying_a_verified_certificate_is_refused_and_changes_nothing(
    api, officials
):
    """The window opened by the first verification is left exactly as it was.

    PRD: "A `SchoolCertifyingOfficial` or `SupervisorySCO` performs it, and it is
    permitted only when the student's `coe_status` is `NOT_SUBMITTED` or
    `EXPIRED`; a certificate already sitting at `VERIFIED` cannot be verified
    again, and the attempt is refused with `ERR_COE_ALREADY_VERIFIED`."

    Design: Corner/state_machines/repeating_a_completed_lifecycle_step_returns_its_own_already_conflict
    """
    student_id = create_verified_student(api, officials.sco_headers)

    response = api.verify_coe(
        student_id,
        f.verify_coe_payload(verified_document_reference=REVERIFY_REFERENCE),
        officials.sco_headers,
    )
    validate_error(response, e.ERR_COE_ALREADY_VERIFIED, 409)

    student = read_student(api, officials.sco_headers, student_id)
    a.assert_fields(
        student,
        {
            "coe_status": c.COE_STATUS_VERIFIED,
            "verified_document_reference": c.COE_REFERENCE,
            "protected_until": FIRST_PROTECTED_UNTIL,
        },
    )


def test_closing_an_already_closed_term_is_refused(api, officials):
    """CLOSED is terminal, so the second close is a conflict rather than a no-op.

    PRD: "Closing a term moves it `OPEN → CLOSED`, is reserved to
    `SupervisorySCO`, and cannot be repeated: a term already at `CLOSED` is
    refused with `ERR_TERM_ALREADY_CLOSED`."

    Design: Corner/state_machines/repeating_a_completed_lifecycle_step_returns_its_own_already_conflict
    """
    term = get_success_data(
        api.create_academic_term(f.academic_term_payload(), officials.sup_headers)
    )
    get_success_data(api.close_academic_term(term["id"], {}, officials.sup_headers))

    response = api.close_academic_term(term["id"], {}, officials.sup_headers)
    validate_error(response, e.ERR_TERM_ALREADY_CLOSED, 409)

    reread = get_success_data(
        api.get_academic_term(term["id"], officials.sup_headers)
    )
    a.assert_fields(reread, {"status": c.TERM_STATUS_CLOSED, "version": 2})


def test_closing_an_already_closed_agreement_is_refused(api, officials):
    """The refused replay bumps no version.

    PRD: "Closing an agreement moves it `ACTIVE → CLOSED`, and an agreement
    already at `CLOSED` cannot be closed again — that attempt is refused with
    `ERR_AGREEMENT_ALREADY_CLOSED`."

    Design: Corner/state_machines/repeating_a_completed_lifecycle_step_returns_its_own_already_conflict
    """
    agreement_id, _version = create_agreement(api, officials.sup_headers)
    get_success_data(
        api.close_yellow_ribbon_agreement(agreement_id, {}, officials.sup_headers)
    )

    response = api.close_yellow_ribbon_agreement(
        agreement_id, {}, officials.sup_headers
    )
    validate_error(response, e.ERR_AGREEMENT_ALREADY_CLOSED, 409)

    agreement = read_agreement(api, officials.sup_headers, agreement_id)
    a.assert_fields(
        agreement, {"status": c.AGREEMENT_STATUS_CLOSED, "version": 2}
    )


# ─── Catalog review phases ────────────────────────────────────────────
def _program_with_one_pending_and_one_draft_catalog(api, officials):
    """A program in agency review plus a second, non-overlapping draft window."""
    program_id = create_program(api, officials.sup_headers)
    pending_id = create_catalog_version(api, officials.sup_headers, program_id)
    get_success_data(
        api.submit_catalog_version_to_saa(pending_id, {}, officials.sup_headers)
    )
    draft_id = create_catalog_version(
        api,
        officials.sup_headers,
        program_id,
        catalog_year=SECOND_CATALOG_YEAR,
        effective_start=SECOND_WINDOW_START,
        effective_end=SECOND_WINDOW_END,
    )
    return program_id, pending_id, draft_id


def test_recording_a_decision_on_a_draft_catalog_is_refused(api, officials):
    """The agency can only decide on what was actually sent to it.

    PRD: "The agency's decision is recorded by a `StateApprovingAgent` and is
    permitted only while the version sits at `PENDING_SAA`; anything else is
    refused with `ERR_CATALOG_NOT_PENDING_SAA`."

    Design: Corner/state_machines/catalog_review_actions_require_the_matching_review_phase
    """
    _program_id, _pending_id, draft_id = _program_with_one_pending_and_one_draft_catalog(
        api, officials
    )

    response = api.record_saa_decision(
        draft_id, f.saa_decision_payload(c.SAA_DECISION_APPROVED), SAA_HEADERS
    )
    validate_error(response, e.ERR_CATALOG_NOT_PENDING_SAA, 409)

    catalog = get_success_data(
        api.get_catalog_version(draft_id, officials.sup_headers)
    )
    assert catalog["review_status"] == c.CATALOG_REVIEW_DRAFT


def test_suspending_a_draft_catalog_is_refused_and_stores_no_reason(api, officials):
    """Enforcement is an edge out of the two approved postures only.

    PRD: "A `StateApprovingAgent` supplies a `suspension_reason`, and the action
    is available only from `review_status` `APPROVED` or
    `APPROVED_WITH_CONDITIONS`; from any other posture it is refused with
    `ERR_CATALOG_NOT_SUSPENDABLE`."

    Design: Corner/state_machines/catalog_review_actions_require_the_matching_review_phase
    """
    _program_id, _pending_id, draft_id = _program_with_one_pending_and_one_draft_catalog(
        api, officials
    )

    response = api.suspend_catalog_version(
        draft_id, f.suspend_catalog_payload(), SAA_HEADERS
    )
    validate_error(response, e.ERR_CATALOG_NOT_SUSPENDABLE, 409)

    catalog = get_success_data(
        api.get_catalog_version(draft_id, officials.sup_headers)
    )
    a.assert_fields(
        catalog,
        {"review_status": c.CATALOG_REVIEW_DRAFT, "suspension_reason": None},
    )


def test_resubmitting_a_pending_catalog_is_refused_and_leaves_the_program_in_review(
    api, officials
):
    """PENDING_SAA is not one of the three postures submission may leave from.

    PRD: "Submitting a catalog version to the agency is a `SupervisorySCO` action
    available from `review_status` `DRAFT`, `REJECTED` or `SUSPENDED`, and from
    nowhere else; any other posture is refused with
    `ERR_CATALOG_NOT_SUBMITTABLE`."

    Design: Corner/state_machines/catalog_review_actions_require_the_matching_review_phase
    """
    program_id, pending_id, _draft_id = _program_with_one_pending_and_one_draft_catalog(
        api, officials
    )

    response = api.submit_catalog_version_to_saa(
        pending_id, {}, officials.sup_headers
    )
    validate_error(response, e.ERR_CATALOG_NOT_SUBMITTABLE, 409)

    catalog = get_success_data(
        api.get_catalog_version(pending_id, officials.sup_headers)
    )
    assert catalog["review_status"] == c.CATALOG_REVIEW_PENDING_SAA
    program = get_success_data(api.get_program(program_id, officials.sup_headers))
    a.assert_fields(
        program,
        {
            "approval_status": c.PROGRAM_STATUS_PENDING_SAA,
            "approved_catalog_version_id": None,
        },
    )


# ─── The catalog review cycle ─────────────────────────────────────────
def _rejected_catalog(api, officials):
    """One catalog version that the agency has already turned down once."""
    program_id = create_program(api, officials.sup_headers)
    catalog_id = create_catalog_version(api, officials.sup_headers, program_id)
    get_success_data(
        api.submit_catalog_version_to_saa(catalog_id, {}, officials.sup_headers)
    )
    get_success_data(
        api.record_saa_decision(
            catalog_id, f.saa_decision_payload(c.SAA_DECISION_REJECTED), SAA_HEADERS
        )
    )
    return program_id, catalog_id


def test_a_rejection_pushes_the_program_back_to_draft_and_unpins_the_catalog(
    api, officials
):
    """Rejection is the one decision branch that clears the pin.

    PRD: "Here the program is set to `approval_status` `DRAFT` and its
    `approved_catalog_version_id` is cleared to null: rejection unpins the catalog
    rather than pinning it."

    Design: Corner/state_machines/a_rejected_catalog_reenters_the_review_cycle_and_can_still_be_approved
    """
    program_id, catalog_id = _rejected_catalog(api, officials)

    catalog = get_success_data(
        api.get_catalog_version(catalog_id, officials.sup_headers)
    )
    assert catalog["review_status"] == c.CATALOG_REVIEW_REJECTED
    program = get_success_data(api.get_program(program_id, officials.sup_headers))
    a.assert_fields(
        program,
        {
            "approval_status": c.PROGRAM_STATUS_DRAFT,
            "approved_catalog_version_id": None,
        },
    )


def test_a_rejected_catalog_can_be_resubmitted_and_finally_approved(api, officials):
    """A rejection is a recovery cycle, not a terminal state.

    PRD: "All three entry points are otherwise identical in their conditions and
    effects: `DRAFT → PENDING_SAA` is a first submission, while the two
    non-`DRAFT` entry points are the recovery cycles of this machine — `REJECTED →
    PENDING_SAA` is resubmission after a rejection, and `SUSPENDED →
    PENDING_SAA` is reinstatement after a suspension."

    Design: Corner/state_machines/a_rejected_catalog_reenters_the_review_cycle_and_can_still_be_approved
    """
    program_id, catalog_id = _rejected_catalog(api, officials)

    resubmitted = get_success_data(
        api.submit_catalog_version_to_saa(catalog_id, {}, officials.sup_headers)
    )
    assert resubmitted["review_status"] == c.CATALOG_REVIEW_PENDING_SAA
    approved = get_success_data(
        api.record_saa_decision(
            catalog_id, f.saa_decision_payload(c.SAA_DECISION_APPROVED), SAA_HEADERS
        )
    )
    assert approved["review_status"] == c.CATALOG_REVIEW_APPROVED

    program = get_success_data(api.get_program(program_id, officials.sup_headers))
    a.assert_fields(
        program,
        {
            "approval_status": c.PROGRAM_STATUS_APPROVED,
            "approved_catalog_version_id": catalog_id,
        },
    )


# ─── The certificate of eligibility cycle ─────────────────────────────
def test_expiring_a_never_verified_certificate_is_refused(api, officials):
    """There is no edge from NOT_SUBMITTED to EXPIRED.

    PRD: "VA may later withdraw verification following an entitlement review:
    `VaProcessingOffice` moves the certificate `VERIFIED → EXPIRED`, which is
    permitted only from `VERIFIED` and otherwise refused with
    `ERR_COE_NOT_VERIFIED`."

    Design: Corner/state_machines/expiring_a_never_verified_coe_is_rejected_and_reverification_restarts_the_window
    """
    student_id = create_student(api, officials.sco_headers)

    response = api.expire_coe(student_id, {}, VA_HEADERS)
    validate_error(response, e.ERR_COE_NOT_VERIFIED, 409)

    student = read_student(api, officials.sco_headers, student_id)
    a.assert_fields(
        student,
        {
            "coe_status": c.COE_STATUS_NOT_SUBMITTED,
            "coe_verified_on": None,
            "protected_until": None,
        },
    )


def test_expiry_leaves_the_historical_verification_stamps_in_place(api, officials):
    """Withdrawing verification does not erase the record of it happening.

    PRD: "Expiry deliberately leaves `coe_verified_on` and `protected_until`
    exactly as they were — the historical record of when verification happened is
    not erased — and recomputes `benefit_payment_protected`, which necessarily
    becomes false because the predicate requires a verified certificate."

    Design: Corner/state_machines/expiring_a_never_verified_coe_is_rejected_and_reverification_restarts_the_window
    """
    student_id = create_verified_student(api, officials.sco_headers)

    expired = get_success_data(api.expire_coe(student_id, {}, VA_HEADERS))
    a.assert_fields(
        expired,
        {
            "coe_status": c.COE_STATUS_EXPIRED,
            "coe_verified_on": c.CLOCK_START_DATE,
            "protected_until": FIRST_PROTECTED_UNTIL,
            "benefit_payment_protected": False,
        },
    )


def test_reverification_restarts_the_protection_window_from_the_new_date(
    api, officials
):
    """The second window runs 90 days from 2026-09-10, not from 2026-08-01.

    PRD: "The one thing that differs is that `protected_until` restarts from the
    new `coe_verified_on`: a re-verified student gets a fresh 90 days measured
    from the new verification date, not the remainder of the old window."

    Design: Corner/state_machines/expiring_a_never_verified_coe_is_rejected_and_reverification_restarts_the_window
    """
    student_id = create_verified_student(api, officials.sco_headers)
    get_success_data(api.expire_coe(student_id, {}, VA_HEADERS))
    set_clock_to(api, REVERIFY_DATE)

    reverified = get_success_data(
        api.verify_coe(
            student_id,
            f.verify_coe_payload(verified_document_reference=REVERIFY_REFERENCE),
            officials.sco_headers,
        )
    )
    a.assert_fields(
        reverified,
        {
            "coe_status": c.COE_STATUS_VERIFIED,
            "coe_verified_on": REVERIFY_DATE,
            "protected_until": SECOND_PROTECTED_UNTIL,
            "verified_document_reference": REVERIFY_REFERENCE,
            "benefit_payment_protected": False,
        },
    )
