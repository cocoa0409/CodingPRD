"""Examination workflow: begin-examination gating, margin/notary defects, rejection,
the reject -> re-record cycle, validation precedence, and cross-entity state gating.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    fixtures,
)


# ===========================================================================
# Difficulty: non_linear_state_machine / package_reject_rerecord_cycle
# ===========================================================================
def test_rejected_package_re_records_into_examination(api):
    """PRD Section 3.3: "marks the latest RejectionNotice as cured (its cured flag becomes
    true), increments resubmission_count by one, and returns the package to IN_EXAMINATION.
    This is the cyclic REJECTED → IN_EXAMINATION path, and a package may traverse it
    repeatedly."

    A MARGIN-rejected package re-records back to IN_EXAMINATION.

    Design: Difficulty/non_linear_state_machine/package_reject_rerecord_cycle
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package_in_examination(
        office["id"], submitter["id"], first_page_top_margin_inches=2.0,
        grantors=("G1",), grantees=("E1",),
    )
    fixtures.reject_package(pkg["id"], reason_code="MARGIN", detail="top margin under 3 inches")
    resp = api.re_record(
        pkg["id"], {"first_page_top_margin_inches": 3.0},
        fixtures.make_submitter_headers(submitter["id"]),
    )
    data = validate_success(resp, expected_status=200)
    assert data["status"] == "IN_EXAMINATION", f"status must be IN_EXAMINATION, got {data['status']}"
    assert data["first_page_top_margin_inches"] == 3.0, (
        f"corrected margin must be applied, got {data['first_page_top_margin_inches']}"
    )


def test_re_record_increments_resubmission_count(api):
    """PRD Section 3.3: "increments resubmission_count by one, and returns the package to
    IN_EXAMINATION."
    PRD Section 3.2: "its resubmission_count starts at 0."

    The first re-record raises resubmission_count from 0 to 1.

    Design: Difficulty/non_linear_state_machine/package_reject_rerecord_cycle
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package_in_examination(
        office["id"], submitter["id"], first_page_top_margin_inches=2.0,
        grantors=("G1",), grantees=("E1",),
    )
    fixtures.reject_package(pkg["id"], reason_code="MARGIN")
    resp = api.re_record(
        pkg["id"], {"first_page_top_margin_inches": 3.0},
        fixtures.make_submitter_headers(submitter["id"]),
    )
    data = validate_success(resp, expected_status=200)
    assert data["resubmission_count"] == 1, (
        f"resubmission_count must increment to 1, got {data['resubmission_count']}"
    )


# ===========================================================================
# Difficulty: priority_pair_validation_conflict / state_beats_fiscal_on_payment
# ===========================================================================
def test_payment_on_unassessed_package_fails_state_not_fiscal(api):
    """PRD Section 2.10: "Fifth, the target resource must be in a valid source state for
    the requested transition, or the request is rejected with ERR_INVALID_STATE." PRD
    Section 2.10: "Tenth come the fiscal checks (payment amount equals the finalized total;
    escrow sufficiency for escrow-method payments)."

    Paying a package still in IN_EXAMINATION (no FINALIZED assessment) with a wrong amount
    fails the higher-priority state check: ERR_INVALID_STATE, not ERR_PAYMENT_AMOUNT_MISMATCH.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_payment
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package_in_examination(
        office["id"], submitter["id"], grantors=("G",), grantees=("E",),
    )
    resp = api.create_payment(
        pkg["id"],
        {"amount_cents": 999999, "method": "CARD", "expected_package_version": pkg["version"]},
        fixtures.make_submitter_headers(submitter["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_payment_on_unassessed_package_creates_no_payment(api):
    """PRD Section 2.10: "Fifth, the target resource must be in a valid source state for
    the requested transition, or the request is rejected with ERR_INVALID_STATE."
    PRD Section 3.4: "Once a package is ASSESSED, its owning submitter pays the finalized
    assessment."

    The rejected payment on an IN_EXAMINATION package leaves no Payment row.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_payment
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package_in_examination(
        office["id"], submitter["id"], grantors=("G",), grantees=("E",),
    )
    api.create_payment(
        pkg["id"],
        {"amount_cents": 999999, "method": "CARD", "expected_package_version": pkg["version"]},
        fixtures.make_submitter_headers(submitter["id"]),
    )
    payments, meta = _list(api.list_payments(pkg["id"], fixtures._clerk()))
    assert meta["total_count"] == 0, f"no payment must be created, got {meta['total_count']}"


# ===========================================================================
# Difficulty: priority_pair_validation_conflict / safety_beats_referential_on_begin_examination
# ===========================================================================
def test_suspended_and_index_incomplete_reports_suspended(api):
    """PRD Section 2.10: "Seventh come the compliance and safety checks (submitter not
    suspended, segregation of duties, and the margin and notary defects that block
    examination approval)." PRD Section 2.10: "Eighth come index-completeness and
    cross-entity state checks (at least one grantor and one grantee; assessment finalized
    before payment; document recorded before a certified copy)."
    PRD Section 3.3: "the owning submitter must be ACTIVE, or the request is rejected with
    ERR_SUBMITTER_SUSPENDED."

    A package with only a GRANTOR (index incomplete) owned by a SUSPENDED submitter fails
    the higher-priority safety check: ERR_SUBMITTER_SUSPENDED, not ERR_INDEX_INCOMPLETE.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_begin_examination
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package(office["id"], submitter["id"], doc_type="DEED")
    fixtures.add_party(pkg["id"], submitter["id"], "GRANTOR", "G only")
    fixtures.suspend_submitter(submitter["id"])
    resp = api.begin_examination(pkg["id"], fixtures._examiner())
    validate_error(resp, ApiErrorId.ERR_SUBMITTER_SUSPENDED)


def test_suspended_index_incomplete_package_stays_submitted(api):
    """PRD Section 3.3: "the owning submitter must be ACTIVE, or the request is rejected
    with ERR_SUBMITTER_SUSPENDED."
    PRD Section 3.2: "The package is born in SUBMITTED status."

    After the rejected begin-examination, the package remains SUBMITTED.

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_begin_examination
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package(office["id"], submitter["id"], doc_type="DEED")
    fixtures.add_party(pkg["id"], submitter["id"], "GRANTOR", "G only")
    fixtures.suspend_submitter(submitter["id"])
    api.begin_examination(pkg["id"], fixtures._examiner())
    data = validate_success(api.get_package(pkg["id"], fixtures._clerk()))
    assert data["status"] == "SUBMITTED", f"package must stay SUBMITTED, got {data['status']}"


# ===========================================================================
# Difficulty: boundary_precision_check / begin_examination_empty_grantee_set
# ===========================================================================
def test_begin_examination_empty_grantee_rejected(api):
    """PRD Section 3.3: "the package must already carry at least one PartyEntry whose
    party_role is GRANTOR and at least one whose party_role is GRANTEE, or it is rejected
    with ERR_INDEX_INCOMPLETE."

    A package with a GRANTOR but zero GRANTEE entries is rejected with ERR_INDEX_INCOMPLETE.

    Design: Difficulty/boundary_precision_check/begin_examination_empty_grantee_set
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package(office["id"], submitter["id"], doc_type="DEED")
    fixtures.add_party(pkg["id"], submitter["id"], "GRANTOR", "G only")
    resp = api.begin_examination(pkg["id"], fixtures._examiner())
    validate_error(resp, ApiErrorId.ERR_INDEX_INCOMPLETE)


def test_begin_examination_empty_grantee_leaves_package_submitted(api):
    """PRD Section 3.3: "or it is rejected with ERR_INDEX_INCOMPLETE."
    PRD Section 3.2: "The package is born in SUBMITTED status."

    The index-incomplete rejection leaves the package in SUBMITTED.

    Design: Difficulty/boundary_precision_check/begin_examination_empty_grantee_set
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package(office["id"], submitter["id"], doc_type="DEED")
    fixtures.add_party(pkg["id"], submitter["id"], "GRANTOR", "G only")
    api.begin_examination(pkg["id"], fixtures._examiner())
    data = validate_success(api.get_package(pkg["id"], fixtures._clerk()))
    assert data["status"] == "SUBMITTED", f"package must stay SUBMITTED, got {data['status']}"


# ===========================================================================
# Difficulty: cross_entity_state_dependency / submit_requires_submitter_active
# ===========================================================================
def test_begin_examination_requires_submitter_active(api):
    """PRD Section 3.3: "This transition is gated on two preconditions: the owning
    submitter must be ACTIVE, or the request is rejected with ERR_SUBMITTER_SUSPENDED."

    With a complete index but a SUSPENDED owning submitter, begin-examination is rejected
    with ERR_SUBMITTER_SUSPENDED (entity-pair: package transition gated on submitter state).

    Design: Difficulty/cross_entity_state_dependency/submit_requires_submitter_active
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package(office["id"], submitter["id"], doc_type="DEED")
    fixtures.add_grantor_grantee(pkg["id"], submitter["id"])
    fixtures.suspend_submitter(submitter["id"])
    resp = api.begin_examination(pkg["id"], fixtures._examiner())
    validate_error(resp, ApiErrorId.ERR_SUBMITTER_SUSPENDED)


def test_begin_examination_suspended_owner_no_transition(api):
    """PRD Section 2.6: "a SUSPENDED submitter may neither submit new packages nor
    re-record." PRD Section 3.3: "the owning submitter must be ACTIVE, or the request is
    rejected with ERR_SUBMITTER_SUSPENDED."

    The package stays SUBMITTED when its owner is SUSPENDED.

    Design: Difficulty/cross_entity_state_dependency/submit_requires_submitter_active
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package(office["id"], submitter["id"], doc_type="DEED")
    fixtures.add_grantor_grantee(pkg["id"], submitter["id"])
    fixtures.suspend_submitter(submitter["id"])
    api.begin_examination(pkg["id"], fixtures._examiner())
    data = validate_success(api.get_package(pkg["id"], fixtures._clerk()))
    assert data["status"] == "SUBMITTED", f"package must stay SUBMITTED, got {data['status']}"


# ===========================================================================
# Difficulty: cross_entity_state_dependency / payment_requires_assessment_finalized
# ===========================================================================
def test_payment_succeeds_when_assessment_finalized(api):
    """PRD Section 3.4: "there must be a FINALIZED FeeAssessment for the package, or the
    request is rejected with ERR_ASSESSMENT_NOT_FINALIZED." PRD Section 3.4: "On a
    successful capture the system creates a Payment in CAPTURED status ... The package
    advances to PAID."

    With the FeeAssessment FINALIZED, an exact-amount ESCROW payment captures and the
    package becomes PAID.

    Design: Difficulty/cross_entity_state_dependency/payment_requires_assessment_finalized
    """
    office, submitter = fixtures.setup_office_and_submitter(escrow_cents=100000)
    pkg_after, assessment = fixtures.create_assessed_package(
        office["id"], submitter["id"], doc_type="DEED",
        verified_page_count=1, verified_consideration_cents=0,
    )
    assert assessment["status"] == "FINALIZED"
    resp = api.create_payment(
        pkg_after["id"],
        {"amount_cents": assessment["total_due_cents"], "method": "ESCROW",
         "expected_package_version": pkg_after["version"]},
        fixtures.make_submitter_headers(submitter["id"]),
    )
    payment = validate_success(resp, expected_status=201)
    assert payment["status"] == "CAPTURED", f"payment must be CAPTURED, got {payment['status']}"
    pkg = validate_success(api.get_package(pkg_after["id"], fixtures._clerk()))
    assert pkg["status"] == "PAID", f"package must be PAID, got {pkg['status']}"


def test_finalized_assessment_remains_finalized_after_payment(api):
    """PRD Section 3.4: "there must be a FINALIZED FeeAssessment for the package, or the
    request is rejected with ERR_ASSESSMENT_NOT_FINALIZED."
    PRD Section 2.6: "the sum of total_due_cents for this submitter's packages whose
    assessment is FINALIZED."

    The cross-entity precondition (FeeAssessment FINALIZED) that permitted the payment is
    observable as FINALIZED on the package's assessment list.

    Design: Difficulty/cross_entity_state_dependency/payment_requires_assessment_finalized
    """
    office, submitter = fixtures.setup_office_and_submitter(escrow_cents=100000)
    pkg_after, assessment = fixtures.create_assessed_package(
        office["id"], submitter["id"], doc_type="DEED",
        verified_page_count=1, verified_consideration_cents=0,
    )
    fixtures.pay_package(pkg_after["id"], submitter["id"],
                         assessment["total_due_cents"], pkg_after["version"])
    rows, _meta = _list(api.list_assessments(pkg_after["id"], fixtures._clerk()))
    finalized = [a for a in rows if a["id"] == assessment["id"]]
    assert finalized and finalized[0]["status"] == "FINALIZED", (
        "the finalized assessment that permitted the payment must remain FINALIZED"
    )


# ===========================================================================
# Corner: validations / margin_defect_at_assessment
# ===========================================================================
def test_margin_defect_blocks_assessment(api):
    """PRD Section 3.3: "Approval is blocked unless the first-page top margin is at least
    the minimum top margin of 3.0 inches — a margin of exactly 3.0 inches passes —
    otherwise the request is rejected with ERR_MARGIN_DEFECT."

    A package with first_page_top_margin_inches 2.9 is rejected with ERR_MARGIN_DEFECT.

    Design: Corner/validations/margin_defect_at_assessment
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package_in_examination(
        office["id"], submitter["id"], first_page_top_margin_inches=2.9,
        grantors=("G",), grantees=("E",),
    )
    resp = api.create_assessment(
        pkg["id"],
        {"verified_page_count": 1, "verified_consideration_cents": 0,
         "expected_package_version": pkg["version"]},
        fixtures._examiner(),
    )
    validate_error(resp, ApiErrorId.ERR_MARGIN_DEFECT)
    data = validate_success(api.get_package(pkg["id"], fixtures._clerk()))
    assert data["status"] == "IN_EXAMINATION", f"package must stay IN_EXAMINATION, got {data['status']}"


# ===========================================================================
# Corner: validations / notary_defect_at_assessment
# ===========================================================================
def test_notary_defect_blocks_assessment(api):
    """PRD Section 3.3: "Approval is also blocked unless notary_present is true, otherwise
    it is rejected with ERR_NOTARY_DEFECT."

    A package with notary_present false (margin OK at 3.0) is rejected with ERR_NOTARY_DEFECT.

    Design: Corner/validations/notary_defect_at_assessment
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package_in_examination(
        office["id"], submitter["id"], first_page_top_margin_inches=3.0,
        notary_present=False, grantors=("G",), grantees=("E",),
    )
    resp = api.create_assessment(
        pkg["id"],
        {"verified_page_count": 1, "verified_consideration_cents": 0,
         "expected_package_version": pkg["version"]},
        fixtures._examiner(),
    )
    validate_error(resp, ApiErrorId.ERR_NOTARY_DEFECT)


# ===========================================================================
# Corner: state_machines / begin_examination_from_recorded_invalid_state
# ===========================================================================
def test_begin_examination_on_recorded_package_invalid_state(api):
    """PRD Section 2.10: "Fifth, the target resource must be in a valid source state for
    the requested transition, or the request is rejected with ERR_INVALID_STATE."
    PRD Section 3.5: "The package itself advances from PAID to RECORDED, a terminal state."

    begin-examination on a RECORDED (terminal) package returns ERR_INVALID_STATE.

    Design: Corner/state_machines/begin_examination_from_recorded_invalid_state
    """
    office, submitter = fixtures.setup_office_and_submitter(escrow_cents=100000)
    pkg_id, _assessment, _rd = fixtures.create_recorded_package(
        office["id"], submitter["id"], doc_type="DEED",
        verified_page_count=1, verified_consideration_cents=0,
    )
    resp = api.begin_examination(pkg_id, fixtures._examiner())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    data = validate_success(api.get_package(pkg_id, fixtures._clerk()))
    assert data["status"] == "RECORDED", f"package must stay RECORDED, got {data['status']}"


# ===========================================================================
# Corner: state_machines / terminal_withdrawn_package_locked
# ===========================================================================
def test_withdrawn_package_rejects_begin_examination(api):
    """PRD Section 2.10: "Fifth, the target resource must be in a valid source state for
    the requested transition, or the request is rejected with ERR_INVALID_STATE."
    PRD Section 3.2: "A package may be withdrawn by its owning submitter while it is in
    SUBMITTED or REJECTED status; withdrawal moves the package to WITHDRAWN."

    A WITHDRAWN package rejects begin-examination with ERR_INVALID_STATE.

    Design: Corner/state_machines/terminal_withdrawn_package_locked
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package(office["id"], submitter["id"], doc_type="DEED")
    fixtures.get_success_data(
        api.withdraw_package(pkg["id"], fixtures.make_submitter_headers(submitter["id"]))
    )
    resp = api.begin_examination(pkg["id"], fixtures._examiner())
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def _list(resp):
    from test_helpers import validate_paginated
    return validate_paginated(resp)
