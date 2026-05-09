"""Tests for PRD §3.2 — Listing creation, submit, approve, reject,
return-for-revision, delist; including version-pinning re-validation at
approve time and the cascading Vehicle ASSESSED→LISTED.
"""

import pytest

from test_helpers import (
    advance_assessment_to_onsite,
    api_client,
    assert_listing,
    create_draft_assessment,
    create_draft_listing,
    create_listing_payload,
    finalize_assessment,
    make_seller_headers,
    onsite_findings_payload,
    register_seller,
    register_vehicle,
    setup_active_listing,
    setup_finalized_assessment,
    setup_listing_under_review,
    submit_listing,
    validate_error,
    validate_success,
    vin_history,
)


# ──────────────────────────────────────────────────────────
# §3.2 Listing creation: pinned report must be FINALIZED
# ──────────────────────────────────────────────────────────


def test_create_listing_with_unfinalized_assessment_rejected(api):
    """PRD §3.2: "The pinned report must be FINALIZED at creation time and at
    submit time; otherwise the operation is rejected with
    ERR_ASSESSMENT_NOT_FINALIZED."
    """
    seller = register_seller()
    vehicle = register_vehicle(seller)
    draft = create_draft_assessment(vehicle, vin_history_records=vin_history(maintenance=1))
    # Listing creation against a DRAFT (non-FINALIZED) assessment.
    res = api.create_listing(
        create_listing_payload(vehicle["id"], draft["id"], sale_mode="FIXED_PRICE"),
        make_seller_headers(seller["id"]),
    )
    validate_error(res, "ERR_ASSESSMENT_NOT_FINALIZED")


def test_create_listing_succeeds_with_finalized_assessment(api):
    """PRD §3.2: "Once a vehicle has at least one FINALIZED AssessmentReport,
    the seller may create a Listing." Initial state is DRAFT with
    NOT_RUN doc_check_status.
    """
    seller, vehicle, assessment = setup_finalized_assessment()
    listing = create_draft_listing(seller, vehicle, assessment)
    assert_listing(listing)
    assert listing["status"] == "DRAFT"
    assert listing["doc_check_status"] == "NOT_RUN"
    assert listing["active_bid_id"] is None
    assert listing["reservation_buyer_id"] is None


# ──────────────────────────────────────────────────────────
# §3.2 Listing submission: photos >= 6, attestation true, FINALIZED
# ──────────────────────────────────────────────────────────


def test_submit_with_fewer_than_six_photos_rejected(api):
    """PRD §3.2: "Three preconditions must hold: the photo_urls array must
    contain at least 6 entries, the documents_authentic_flag must be true,
    and the pinned AssessmentReport must still be FINALIZED. Photo or
    attestation insufficiency is rejected with ERR_LISTING_DOCS_INSUFFICIENT."
    """
    seller, vehicle, assessment = setup_finalized_assessment()
    # Listing with only 3 photos.
    listing = create_draft_listing(
        seller,
        vehicle,
        assessment,
        photo_urls=["https://x.example/1", "https://x.example/2", "https://x.example/3"],
    )
    res = api.submit_listing(listing["id"], make_seller_headers(seller["id"]))
    validate_error(res, "ERR_LISTING_DOCS_INSUFFICIENT")


def test_submit_with_documents_authentic_false_rejected(api):
    """PRD §3.2: "Three preconditions must hold: the photo_urls array must
    contain at least 6 entries, the documents_authentic_flag must be true,
    and the pinned AssessmentReport must still be FINALIZED."
    PRD §3.2: "Photo or attestation insufficiency is rejected with
    ERR_LISTING_DOCS_INSUFFICIENT".
    """
    seller, vehicle, assessment = setup_finalized_assessment()
    listing = create_draft_listing(
        seller, vehicle, assessment, documents_authentic_flag=False
    )
    res = api.submit_listing(listing["id"], make_seller_headers(seller["id"]))
    validate_error(res, "ERR_LISTING_DOCS_INSUFFICIENT")


def test_submit_pins_assessment_report_version(api):
    """PRD §3.2: "On success, the listing's assessment_report_version is set
    to the current version of the pinned report — this version-pinning
    becomes the contract that the listing approve step revalidates."
    """
    seller, vehicle, assessment, listing = setup_listing_under_review()
    assert listing["status"] == "UNDER_REVIEW"
    assert listing["assessment_report_version"] == assessment["version"]


# ──────────────────────────────────────────────────────────
# §3.2 Approve: cascades vehicle, sets doc_check_status PASS
# ──────────────────────────────────────────────────────────


def test_approve_cascades_vehicle_to_listed(api, admin_headers):
    """PRD §3.2: "Approving advances the listing from UNDER_REVIEW to ACTIVE,
    sets doc_check_status to PASS, and cascades the underlying vehicle from
    ASSESSED to LISTED."
    """
    seller, vehicle, _, listing = setup_active_listing()
    refreshed = validate_success(api.get_listing(listing["id"], admin_headers), 200)
    assert refreshed["status"] == "ACTIVE"
    assert refreshed["doc_check_status"] == "PASS"
    veh_after = validate_success(api.get_vehicle(vehicle["id"], admin_headers), 200)
    assert veh_after["vehicle_status"] == "LISTED"


def test_approve_with_stale_assessment_version_rejected(api):
    """PRD §3.2: "Approval requires that doc_check_status end up as PASS
    and — critically — that the pinned assessment_report_version still equal
    the current version of the pinned AssessmentReport; if a newer report has
    been finalised in the meantime (or any other version-bumping mutation
    occurred on the pinned report), the approve step is rejected with
    ERR_ASSESSMENT_VERSION_STALE."

    PRD §3.1: "Whenever a newer report is finalised, every prior report for
    the same vehicle that was in FINALIZED is moved to SUPERSEDED."

    Note: a SUPERSEDED report is no longer FINALIZED, so PRD §3.2's
    re-validation at approve time may reject either with the version-stale
    error_id or with the assessment-not-finalized error_id depending on
    which check the implementer evaluates first. Both readings are
    PRD-faithful, so the test accepts either.
    """
    seller, vehicle, assessment, listing = setup_listing_under_review()
    # Finalize a *new* report for the same vehicle — supersedes the pinned one.
    new_draft = create_draft_assessment(
        vehicle, vin_history_records=vin_history(maintenance=2)
    )
    new_onsite = advance_assessment_to_onsite(new_draft)
    finalize_assessment(
        new_onsite,
        onsite=onsite_findings_payload(mileage_km_observed=vehicle["declared_mileage_km"]),
    )
    # Now the pinned assessment is SUPERSEDED. Approve must reject.
    from prd_bench_local_runner.testing import validate_error_is_one_of

    res = api.approve_listing(
        listing["id"], {"X-User-ID": "00000000-0000-4000-8000-00000000ad01", "X-User-Role": "PlatformAdmin"}
    )
    validate_error_is_one_of(
        res, ["ERR_ASSESSMENT_VERSION_STALE", "ERR_ASSESSMENT_NOT_FINALIZED"]
    )


# ──────────────────────────────────────────────────────────
# §3.2 Reject and return-for-revision
# ──────────────────────────────────────────────────────────


def test_reject_sets_doc_check_status_fail(api, admin_headers):
    """PRD §3.2: "Rejecting takes the listing from UNDER_REVIEW to REJECTED
    and sets doc_check_status to FAIL."
    """
    seller, vehicle, assessment, listing = setup_listing_under_review()
    rejected = validate_success(api.reject_listing(listing["id"], admin_headers), 200)
    assert rejected["status"] == "REJECTED"
    assert rejected["doc_check_status"] == "FAIL"


def test_return_for_revision_moves_back_to_draft(api, admin_headers):
    """PRD §3.2: "Returning for revision takes the listing from UNDER_REVIEW
    back to DRAFT with no field side-effects beyond the standard updated_at
    and version bump, allowing the seller to refresh photos or correct
    attestations before re-submitting."
    """
    seller, vehicle, assessment, listing = setup_listing_under_review()
    returned = validate_success(
        api.return_listing_for_revision(listing["id"], admin_headers), 200
    )
    assert returned["status"] == "DRAFT"


# ──────────────────────────────────────────────────────────
# §3.2 Delist
# ──────────────────────────────────────────────────────────


def test_delist_active_listing_succeeds_and_cascades_vehicle(api, admin_headers):
    """PRD §3.2: "A successful delist transitions the listing from ACTIVE to
    DELISTED, cancels any QUEUED reservations and releases their deposits,
    and — if no other listing for the same vehicle is in UNDER_REVIEW,
    ACTIVE, or RESERVED — cascades the vehicle from LISTED back to ASSESSED."
    """
    seller, vehicle, _, listing = setup_active_listing(sale_mode="FIXED_PRICE")
    res = api.delist_listing(listing["id"], make_seller_headers(seller["id"]))
    delisted = validate_success(res, 200)
    assert delisted["status"] == "DELISTED"
    veh = validate_success(api.get_vehicle(vehicle["id"], admin_headers), 200)
    assert veh["vehicle_status"] == "ASSESSED"


# ──────────────────────────────────────────────────────────
# §2.5 Optimistic Concurrency
# ──────────────────────────────────────────────────────────


def test_stale_version_on_listing_returns_version_conflict(api):
    """PRD §2.5: "Mutating endpoints accept an optional version field in the
    request body. When supplied, the server compares it to the current
    persisted version for the target resource: a match performs the mutation
    and increments version by 1; a mismatch — meaning another writer has
    already advanced the row — is rejected with ERR_VERSION_CONFLICT and
    HTTP 409."
    """
    seller, vehicle, assessment, listing = setup_listing_under_review()
    # The listing's current version equals what was returned by submit. Try
    # to approve with an obviously stale version.
    stale_version = listing["version"] - 1 if listing["version"] > 1 else 0
    res = api.approve_listing(
        listing["id"],
        {"X-User-ID": "00000000-0000-4000-8000-00000000ad01", "X-User-Role": "PlatformAdmin"},
        payload={"version": stale_version},
    )
    validate_error(res, "ERR_VERSION_CONFLICT")
