"""Optimistic concurrency tests — Application.version OCC on aid-offer
create and on decide.

Covers Corner-design Section 8 OCC layer.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_admitted_application, setup_admitted_with_fa_profile,
    setup_under_review_application,
    create_aid_offer_payload, decide_payload,
    make_applicant_headers, admissions_headers, fa_officer_headers,
)


# ─── layer_occ_aid_offer_create_stale_application_version ───────────────

def test_aid_offer_create_with_stale_application_version_rejected(api):
    """PRD §2.8: "A POST to the aid-offers collection must carry
    expected_application_version as a non-optional input field, matching
    the target application's current version at the moment the server
    processes the create. If another writer has advanced the application's
    version since the financial aid officer last read it ... the create
    is rejected with ERR_STALE_APPLICATION_VERSION (HTTP 412)"

    Design: Corner/cross_cutting_layers/layer_occ_aid_offer_create_stale_application_version
    """
    applicant, school, admitted, _fa = setup_admitted_with_fa_profile(
        fafsa_efc_cents=1_000_000,
        family_income_cents=5_000_000,
        school_overrides={"name": "OCC-AO"},
    )
    # Capture the version observed at ADMITTED — this will be the stale
    # value once another writer advances Application.version.
    stale_version = admitted["version"]

    # Applicant declines the offer → Application advances to
    # DECLINED_OFFER and version increments per PRD §2.7. (We can also
    # advance the version through other transitions; decline_offer is
    # the simplest because it has no further preconditions beyond
    # ADMITTED.)
    get_success_data(api.decline_offer(
        admitted["id"], make_applicant_headers(applicant["id"])))

    # Stale aid-offer-create — the version field is now out of date.
    res = api.create_aid_offer(
        create_aid_offer_payload(
            admitted["id"], expected_application_version=stale_version,
            cost_of_attendance_cents=6_000_000,
            variant="FEDERAL",
            grant_cents=500_000, loan_cents=500_000, work_study_cents=0),
        fa_officer_headers())
    validate_error(res, "ERR_STALE_APPLICATION_VERSION")


def test_aid_offer_create_after_accept_offer_stale_version(api):
    """PRD §2.8: "the canonical case is that the officer reads Application
    v=5 in ADMITTED, then between the read and the create the applicant
    accepts the offer (advancing version to 6 and the status to
    ENROLLED) — the create is rejected with ERR_STALE_APPLICATION_VERSION
    (HTTP 412)"

    Design: Corner/cross_cutting_layers/layer_occ_aid_offer_create_stale_application_version
    """
    applicant, school, admitted, _fa = setup_admitted_with_fa_profile(
        fafsa_efc_cents=1_000_000,
        family_income_cents=5_000_000,
        school_overrides={"name": "OCC-CANON"},
    )
    stale_version = admitted["version"]
    # Applicant accepts → Application.version advances per PRD §2.7
    # ("every affected row has its updated_at refreshed and its version
    # incremented").
    get_success_data(api.accept_offer(
        admitted["id"], make_applicant_headers(applicant["id"])))

    # Stale aid-offer-create — should be rejected with 412 per PRD §2.8.
    # (We can attempt this create even though the app is now ENROLLED;
    # OCC fires regardless of which transition advanced the version.)
    res = api.create_aid_offer(
        create_aid_offer_payload(
            admitted["id"], expected_application_version=stale_version,
            cost_of_attendance_cents=6_000_000,
            variant="FEDERAL",
            grant_cents=500_000, loan_cents=500_000, work_study_cents=0),
        fa_officer_headers())
    validate_error(res, "ERR_STALE_APPLICATION_VERSION")


# ─── layer_occ_decide_stale_application_version ─────────────────────────

def test_second_decide_with_stale_application_version_rejected(api):
    """PRD §2.8: "If two admissions officers both pull Application v=2 in
    UNDER_REVIEW, the first writes decision=ADMIT (advancing version to
    v=3 and status to ADMITTED), and the second sends decision=WAITLIST
    still carrying expected_application_version=2, the second request is
    rejected with ERR_STALE_APPLICATION_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_layers/layer_occ_decide_stale_application_version
    """
    _, _, _, reviewed = setup_under_review_application(plan="REGULAR")
    stale_version = reviewed["version"]

    # First decide succeeds, bumping version.
    validate_success(api.decide_application(
        reviewed["id"],
        decide_payload("ADMIT", stale_version),
        admissions_headers()), 200)

    # Second decide with the same (now stale) expected_application_version
    # is rejected per PRD §2.8.
    res = api.decide_application(
        reviewed["id"],
        decide_payload("WAITLIST", stale_version),
        admissions_headers())
    validate_error(res, "ERR_STALE_APPLICATION_VERSION")
