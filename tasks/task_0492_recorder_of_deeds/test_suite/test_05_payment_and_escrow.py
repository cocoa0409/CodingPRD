"""Payment capture, escrow hold-to-spend conversion, rejection cascade, and the
optimistic-concurrency guard on the document package.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    fixtures,
)


# ===========================================================================
# Difficulty: transitive_cascade / reject_voids_assessment_then_releases_hold
# ===========================================================================
def test_reject_voids_finalized_assessment(api):
    """PRD Section 3.3: "The rejection cascade has three linked effects: a RejectionNotice
    recording the reason_code and detail is created (its cured flag starts false); any
    FINALIZED FeeAssessment for the package is set to VOIDED."

    Rejecting an ASSESSED package sets its FINALIZED FeeAssessment to VOIDED and the
    package to REJECTED.

    Design: Difficulty/transitive_cascade/reject_voids_assessment_then_releases_hold
    """
    office, submitter = fixtures.setup_office_and_submitter(escrow_cents=100000)
    pkg_after, assessment = fixtures.create_assessed_package(
        office["id"], submitter["id"], doc_type="DEED",
        verified_page_count=1, verified_consideration_cents=0,
    )
    fixtures.reject_package(pkg_after["id"], reason_code="LEGAL_DESCRIPTION",
                            detail="metes and bounds incomplete")
    pkg = validate_success(api.get_package(pkg_after["id"], fixtures._clerk()))
    assert pkg["status"] == "REJECTED", f"package must be REJECTED, got {pkg['status']}"
    rows, _meta = validate_paginated(api.list_assessments(pkg_after["id"], fixtures._clerk()))
    voided = [a for a in rows if a["id"] == assessment["id"]]
    assert voided and voided[0]["status"] == "VOIDED", (
        f"finalized assessment must be VOIDED on rejection, got {voided}"
    )


def test_reject_releases_escrow_hold(api):
    """PRD Section 3.3: "voiding that assessment releases its hold, so the submitter's
    escrow_held_cents decreases by that assessment's total_due_cents and
    escrow_available_cents is recomputed."

    After rejecting the only ASSESSED package, the submitter's escrow_held_cents returns
    to 0.

    Design: Difficulty/transitive_cascade/reject_voids_assessment_then_releases_hold
    """
    office, submitter = fixtures.setup_office_and_submitter(escrow_cents=100000)
    pkg_after, _assessment = fixtures.create_assessed_package(
        office["id"], submitter["id"], doc_type="DEED",
        verified_page_count=1, verified_consideration_cents=0,
    )
    fixtures.reject_package(pkg_after["id"], reason_code="LEGAL_DESCRIPTION")
    sub = validate_success(api.get_submitter(submitter["id"], fixtures._clerk()))
    assert sub["escrow_held_cents"] == 0, (
        f"hold must be released to 0 after rejection, got {sub['escrow_held_cents']}"
    )


# ===========================================================================
# Corner: validations / payment_amount_mismatch
# ===========================================================================
def test_payment_amount_mismatch_rejected(api):
    """PRD Section 3.4: "the amount_cents must equal that finalized assessment's
    total_due_cents, or the request is rejected with ERR_PAYMENT_AMOUNT_MISMATCH."

    Paying an ASSESSED package (total 3500) with amount_cents 3499 returns
    ERR_PAYMENT_AMOUNT_MISMATCH.

    Design: Corner/validations/payment_amount_mismatch
    """
    office, submitter = fixtures.setup_office_and_submitter(escrow_cents=100000)
    pkg_after, assessment = fixtures.create_assessed_package(
        office["id"], submitter["id"], doc_type="DEED",
        verified_page_count=1, verified_consideration_cents=0,
    )
    assert assessment["total_due_cents"] == 3500
    resp = api.create_payment(
        pkg_after["id"],
        {"amount_cents": 3499, "method": "ESCROW", "expected_package_version": pkg_after["version"]},
        fixtures.make_submitter_headers(submitter["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)


# ===========================================================================
# Corner: validations / escrow_insufficient
# ===========================================================================
def test_escrow_insufficient_rejected(api):
    """PRD Section 3.4: "when the method is ESCROW, the submitter's settled
    escrow_balance_cents must be at least the amount_cents, or the request is rejected
    with ERR_ESCROW_INSUFFICIENT."

    An ESCROW payment of 3500 with only 1000 settled escrow returns ERR_ESCROW_INSUFFICIENT.

    Design: Corner/validations/escrow_insufficient
    """
    office, submitter = fixtures.setup_office_and_submitter(escrow_cents=1000)
    pkg_after, assessment = fixtures.create_assessed_package(
        office["id"], submitter["id"], doc_type="DEED",
        verified_page_count=1, verified_consideration_cents=0,
    )
    resp = api.create_payment(
        pkg_after["id"],
        {"amount_cents": assessment["total_due_cents"], "method": "ESCROW",
         "expected_package_version": pkg_after["version"]},
        fixtures.make_submitter_headers(submitter["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_ESCROW_INSUFFICIENT)


# ===========================================================================
# Corner: cross_cutting_complexity_layers / occ_stale_package_version_on_assessment
# ===========================================================================
def test_stale_package_version_on_reassessment_rejected(api):
    """PRD Section 2.9: "When an assessment is finalized, the request must carry
    expected_package_version equal to the target package's current version. A
    re-examination legitimately creates a new FINALIZED assessment that supersedes the
    prior one, advancing the package's version; if another writer has advanced that
    version since the client last read it, the finalize is rejected with
    ERR_STALE_PACKAGE_VERSION (HTTP 412)."

    A second assessment that re-uses the pre-first-assessment version is stale -> 412.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_package_version_on_assessment
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package_in_examination(
        office["id"], submitter["id"], grantors=("G",), grantees=("E",),
    )
    stale_version = pkg["version"]
    fixtures.assess_package(pkg["id"], 1, 0, stale_version)  # bumps version
    resp = api.create_assessment(
        pkg["id"],
        {"verified_page_count": 2, "verified_consideration_cents": 0,
         "expected_package_version": stale_version},
        fixtures._examiner(),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_PACKAGE_VERSION)


# ===========================================================================
# Corner: cross_cutting_complexity_layers / occ_stale_package_version_on_payment
# ===========================================================================
def test_stale_package_version_on_payment_rejected(api):
    """PRD Section 2.9: "when a payment is captured, the request must carry
    expected_package_version equal to the package's current version; because a newer
    assessment may have superseded the one the client priced against, a stale package
    version is rejected with ERR_STALE_PACKAGE_VERSION (HTTP 412) rather than letting the
    payment apply to an outdated total."

    Paying with the pre-assessment version (now stale by one) returns ERR_STALE_PACKAGE_VERSION.

    Design: Corner/cross_cutting_complexity_layers/occ_stale_package_version_on_payment
    """
    office, submitter = fixtures.setup_office_and_submitter(escrow_cents=100000)
    pkg = fixtures.create_package_in_examination(
        office["id"], submitter["id"], grantors=("G",), grantees=("E",),
    )
    stale_version = pkg["version"]
    fixtures.assess_package(pkg["id"], 1, 0, stale_version)  # bumps version
    resp = api.create_payment(
        pkg["id"],
        {"amount_cents": 3500, "method": "ESCROW", "expected_package_version": stale_version},
        fixtures.make_submitter_headers(submitter["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_PACKAGE_VERSION)


# ===========================================================================
# Corner: cross_cutting_complexity_layers / version_increments_on_assessment
# ===========================================================================
def test_assessment_increments_package_version_by_one(api):
    """PRD Section 2.4: "The DocumentPackage version field has a second role beyond audit:
    it is the optimistic-concurrency anchor described in Section 2.9, and it is bumped by
    one specifically when an assessment is finalized and when a payment is captured."
    PRD Section 3.3: "the package advances to ASSESSED; and the package's version is
    incremented by one."

    A successful assessment increments version by exactly 1 over expected_package_version.

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_assessment
    """
    office, submitter = fixtures.setup_office_and_submitter()
    pkg = fixtures.create_package_in_examination(
        office["id"], submitter["id"], grantors=("G",), grantees=("E",),
    )
    pre_version = pkg["version"]
    fixtures.assess_package(pkg["id"], 1, 0, pre_version)
    data = validate_success(api.get_package(pkg["id"], fixtures._examiner()))
    assert data["status"] == "ASSESSED", f"status must be ASSESSED, got {data['status']}"
    assert data["version"] == pre_version + 1, (
        f"version must increment to {pre_version + 1}, got {data['version']}"
    )
