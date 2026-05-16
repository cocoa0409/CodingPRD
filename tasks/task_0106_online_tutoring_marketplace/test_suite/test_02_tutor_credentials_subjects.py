"""Tutor onboarding, credentials, verification posture, and subject tags.

Covers PRD §3.1 (tutor + credentials + posture computation) and §3.2
(subject tag propose / approve / delete).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_DEFAULTS,
    TEST_USERS,
    add_approved_subject,
    advance_clock_by,
    advance_clock_to,
    approve_credential,
    approve_subject,
    assert_credential,
    assert_subject_tag,
    assert_tutor,
    book_session,
    confirm_session,
    create_adult_student,
    create_tutor,
    create_tutor_payload,
    iso_offset,
    iso_utc,
    make_tutor_headers,
    make_verifier_headers,
    parse_iso,
    patch_tutor_payload,
    propose_subject,
    propose_subject_payload,
    reject_credential,
    server_now_dt,
    setup_verified_tutor_with_subject,
    submit_credential,
    submit_credential_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Tutor creation
# ===========================================================================
class TestTutorCreate:
    def test_create_tutor_returns_unverified(self, api):
        """PRD §3.1: "new tutors begin in UNVERIFIED."

        Claim: POST /tutoring/tutors returns a tutor with
        verification_status=UNVERIFIED, version=1, computed counters
        at 0, empty subject_tags.
        """
        tutor = create_tutor()
        assert_tutor(tutor)
        assert tutor["verification_status"] == "UNVERIFIED"
        assert tutor["version"] == 1
        assert tutor["payout_balance_cents"] == 0
        assert tutor["lifetime_completed_sessions"] == 0
        assert tutor["subject_tags"] == []

    def test_create_tutor_trial_exceeds_hourly_rejected(self, api,
                                                       admin_headers):
        """PRD §3.1: "a trial_rate_cents between 0 and hourly_rate_cents
        inclusive — the trial rate cannot exceed the standard rate."

        Claim: trial_rate_cents > hourly_rate_cents returns
        ERR_VALIDATION.
        """
        res = api.create_tutor(
            create_tutor_payload(
                hourly_rate_cents=2000, trial_rate_cents=3000,
            ),
            admin_headers,
        )
        validate_error(res, "ERR_VALIDATION")

    def test_create_tutor_hourly_rate_below_min_rejected(self, api,
                                                        admin_headers):
        """PRD §3.1: "an hourly_rate_cents between 1000 and 50000
        (i.e. $10/hr through $500/hr)."

        Claim: hourly_rate_cents=999 returns ERR_VALIDATION.
        """
        res = api.create_tutor(
            create_tutor_payload(
                hourly_rate_cents=999, trial_rate_cents=999,
            ),
            admin_headers,
        )
        validate_error(res, "ERR_VALIDATION")

    def test_create_tutor_hourly_rate_above_max_rejected(self, api,
                                                        admin_headers):
        """PRD §3.1: "an hourly_rate_cents between 1000 and 50000."

        Claim: hourly_rate_cents=50001 returns ERR_VALIDATION.
        """
        res = api.create_tutor(
            create_tutor_payload(
                hourly_rate_cents=50_001, trial_rate_cents=1000,
            ),
            admin_headers,
        )
        validate_error(res, "ERR_VALIDATION")


# ===========================================================================
# Credentials and verification posture
# ===========================================================================
class TestCredentialsAndPosture:
    def test_submit_credential_moves_tutor_to_pending_review(self, api):
        """PRD §3.1: "Any credential submission for a tutor currently
        in UNVERIFIED flips the tutor from UNVERIFIED to PENDING_REVIEW".

        Claim: first credential submission moves the tutor to
        PENDING_REVIEW.
        """
        tutor = create_tutor()
        submit_credential(tutor=tutor, credential_type="GOVERNMENT_ID")
        refreshed = validate_success(
            api.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
        )
        assert refreshed["verification_status"] == "PENDING_REVIEW"

    def test_subsequent_submission_does_not_change_state(self, api):
        """PRD §3.1: "subsequent submissions do not re-trigger this
        transition."

        Claim: submitting a second credential while in PENDING_REVIEW
        leaves verification_status at PENDING_REVIEW.
        """
        tutor = create_tutor()
        submit_credential(tutor=tutor, credential_type="GOVERNMENT_ID")
        # Re-fetch to confirm PENDING_REVIEW.
        refreshed = validate_success(
            api.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
        )
        assert refreshed["verification_status"] == "PENDING_REVIEW"
        submit_credential(tutor=refreshed, credential_type="DEGREE")
        again = validate_success(
            api.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
        )
        assert again["verification_status"] == "PENDING_REVIEW"

    def test_verifier_cannot_be_tutor_on_approve(self, api):
        """PRD §3.1: "require the verifier's X-User-ID to differ from
        the credential's tutor_id (ERR_SEGREGATION_VIOLATION)."

        Claim: verifier-id equal to tutor-id returns
        ERR_SEGREGATION_VIOLATION on approve.
        """
        tutor = create_tutor()
        credential = submit_credential(
            tutor=tutor, credential_type="GOVERNMENT_ID",
        )
        # Verifier headers minted with tutor's id collide intentionally.
        res = api.approve_credential(
            tutor["id"], credential["id"],
            make_verifier_headers(tutor["id"]),
        )
        validate_error(res, "ERR_SEGREGATION_VIOLATION")

    def test_approve_credential_requires_submitted_state(self, api):
        """PRD §3.1: "Both operations require the credential to be in
        SUBMITTED (any other state yields ERR_INVALID_STATE)".

        Claim: approving an already-APPROVED credential returns
        ERR_INVALID_STATE.
        """
        tutor = create_tutor()
        credential = submit_credential(
            tutor=tutor, credential_type="GOVERNMENT_ID",
        )
        approved = approve_credential(tutor=tutor, credential=credential)
        assert approved["status"] == "APPROVED"
        # Second approve attempt:
        res = api.approve_credential(
            tutor["id"], credential["id"], TEST_USERS["verifier_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_critical_rejection_moves_tutor_to_rejected(self, api):
        """PRD §3.1: "if any credential of type GOVERNMENT_ID or
        BACKGROUND_CHECK is in REJECTED, the tutor is REJECTED."

        Claim: rejecting a GOVERNMENT_ID credential drives the tutor's
        posture to REJECTED.
        """
        tutor = create_tutor()
        cred = submit_credential(
            tutor=tutor, credential_type="GOVERNMENT_ID",
        )
        rejected = reject_credential(tutor=tutor, credential=cred)
        assert rejected["status"] == "REJECTED"
        refreshed = validate_success(
            api.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
        )
        assert refreshed["verification_status"] == "REJECTED"

    def test_both_critical_approved_drives_verified(self, api):
        """PRD §3.1: "if this set contains both GOVERNMENT_ID and
        BACKGROUND_CHECK, the tutor is VERIFIED."

        Claim: approving GOVERNMENT_ID + BACKGROUND_CHECK yields
        verification_status=VERIFIED.

        # difficulty: dual_variant_calc/verification_posture_provisional_vs_final_on_tutor
        """
        tutor = create_tutor()
        gov = submit_credential(
            tutor=tutor, credential_type="GOVERNMENT_ID",
        )
        bg = submit_credential(
            tutor=tutor, credential_type="BACKGROUND_CHECK",
        )
        approve_credential(tutor=tutor, credential=gov)
        approve_credential(tutor=tutor, credential=bg)
        refreshed = validate_success(
            api.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
        )
        assert refreshed["verification_status"] == "VERIFIED"

    def test_only_government_id_approved_stays_pending_review(self, api):
        """PRD §3.1: "if any credential is still in SUBMITTED, the
        tutor is PENDING_REVIEW."

        Claim: approving only GOVERNMENT_ID while BACKGROUND_CHECK is
        SUBMITTED leaves the tutor in PENDING_REVIEW (not VERIFIED).
        """
        tutor = create_tutor()
        gov = submit_credential(
            tutor=tutor, credential_type="GOVERNMENT_ID",
        )
        submit_credential(
            tutor=tutor, credential_type="BACKGROUND_CHECK",
        )
        approve_credential(tutor=tutor, credential=gov)
        refreshed = validate_success(
            api.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
        )
        assert refreshed["verification_status"] == "PENDING_REVIEW"

    def test_degree_alone_does_not_verify(self, api):
        """PRD §3.1: "DEGREE and TEACHING_LICENSE are tracked but do
        not gate VERIFIED status."

        Claim: approving DEGREE only (no GOVERNMENT_ID / no
        BACKGROUND_CHECK) leaves the tutor below VERIFIED.
        """
        tutor = create_tutor()
        d = submit_credential(tutor=tutor, credential_type="DEGREE")
        approve_credential(tutor=tutor, credential=d)
        refreshed = validate_success(
            api.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
        )
        assert refreshed["verification_status"] != "VERIFIED"


# ===========================================================================
# Admin suspend / reinstate
# ===========================================================================
class TestSuspendReinstate:
    def test_admin_suspend_verified_tutor(self, api, admin_headers):
        """PRD §3.1: "A VERIFIED tutor moves to SUSPENDED ... when a
        PlatformAdmin explicitly suspends the tutor."

        Claim: admin /suspend on a VERIFIED tutor returns the row in
        SUSPENDED state.
        """
        from test_helpers import make_tutor_verified
        tutor, _, _ = make_tutor_verified()
        res = api.suspend_tutor(tutor["id"], admin_headers)
        body = validate_success(res)
        assert body["verification_status"] == "SUSPENDED"

    def test_reinstate_requires_posture_verified(self, api, admin_headers):
        """PRD §3.1: "A SUSPENDED tutor can be returned to VERIFIED
        only by a PlatformAdmin reinstate action, and only if the
        verification posture computation again yields VERIFIED".

        Claim: reinstate succeeds for a SUSPENDED tutor whose
        credentials still satisfy posture=VERIFIED.
        """
        from test_helpers import make_tutor_verified
        tutor, _, _ = make_tutor_verified()
        api.suspend_tutor(tutor["id"], admin_headers)
        res = api.reinstate_tutor(tutor["id"], admin_headers)
        body = validate_success(res)
        assert body["verification_status"] == "VERIFIED"


# ===========================================================================
# SubjectTag
# ===========================================================================
class TestSubjectTags:
    def test_propose_subject_tag_initial_state(self, api):
        """PRD §3.2: "The tag row carries the owning tutor_id and
        starts in PROPOSED."

        Claim: POST /subjects returns a tag in PROPOSED state.
        """
        tutor = create_tutor()
        tag = propose_subject(tutor=tutor, subject_code="MATH_ALGEBRA")
        assert_subject_tag(tag)
        assert tag["status"] == "PROPOSED"
        assert tag["tutor_id"] == tutor["id"]
        assert tag["subject_code"] == "MATH_ALGEBRA"

    def test_subject_code_unique_per_tutor(self, api):
        """PRD §3.2: "the (tutor_id, subject_code) pair must be unique".

        Claim: a second proposal for the same subject_code on the same
        tutor returns ERR_VALIDATION.
        """
        tutor = create_tutor()
        propose_subject(tutor=tutor, subject_code="MATH_GEOMETRY")
        res = api.propose_subject(
            tutor["id"],
            propose_subject_payload(subject_code="MATH_GEOMETRY"),
            make_tutor_headers(tutor["id"]),
        )
        validate_error(res, "ERR_VALIDATION")

    def test_approve_subject_segregation(self, api):
        """PRD §3.2: "the verifier's X-User-ID is different from the
        tutor's id (ERR_SEGREGATION_VIOLATION otherwise)."

        Claim: verifier-id equal to tutor-id on subject approve returns
        ERR_SEGREGATION_VIOLATION.
        """
        from test_helpers import make_tutor_verified
        tutor, _, _ = make_tutor_verified()
        tag = propose_subject(tutor=tutor, subject_code="MATH_STATISTICS")
        res = api.approve_subject(
            tutor["id"], tag["id"], make_verifier_headers(tutor["id"]),
        )
        validate_error(res, "ERR_SEGREGATION_VIOLATION")

    def test_approve_subject_appends_to_subject_tags_cache(self, api):
        """PRD §3.2: "On approval, the subject_code is appended to the
        tutor's denormalized subject_tags cache."

        Claim: after approve, tutor.subject_tags contains the code.
        """
        from test_helpers import make_tutor_verified
        tutor, _, _ = make_tutor_verified()
        tag = propose_subject(tutor=tutor, subject_code="PHYS_MECHANICS")
        approve_subject(tutor=tutor, subject=tag)
        refreshed = validate_success(
            api.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
        )
        assert "PHYS_MECHANICS" in refreshed["subject_tags"]

    def test_delete_approved_tag_with_active_session_rejected(self, api):
        """PRD §3.2: "but only if there is no Session for that
        (tutor_id, subject_code) pair in any of REQUESTED, CONFIRMED,
        or IN_PROGRESS — otherwise the delete is rejected with
        ERR_INVALID_STATE."

        Claim: deleting an APPROVED tag while a REQUESTED Session on
        that subject exists returns ERR_INVALID_STATE.
        """
        from test_helpers import make_tutor_verified
        tutor, _, _ = make_tutor_verified()
        tag = add_approved_subject(tutor=tutor, subject_code="HIST_WORLD")
        # Re-fetch tutor so its subject_tags cache includes HIST_WORLD.
        tutor = validate_success(
            api.get_tutor(tutor["id"], TEST_USERS["admin_headers"]),
        )
        student = create_adult_student()
        book_session(tutor=tutor, student=student, subject_code="HIST_WORLD")
        res = api.delete_subject(
            tutor["id"], tag["id"], make_tutor_headers(tutor["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_delete_proposed_tag_unconditional(self, api):
        """PRD §3.2: "Deletion of a PROPOSED tag is unconditional and
        transitions it directly to REMOVED."

        Claim: deleting a PROPOSED tag returns 204 No Content.
        """
        tutor = create_tutor()
        tag = propose_subject(tutor=tutor, subject_code="ARTS_DRAWING")
        res = api.delete_subject(
            tutor["id"], tag["id"], make_tutor_headers(tutor["id"]),
        )
        assert res.status_code == 204, (
            f"DELETE on PROPOSED tag must return 204, got {res.status_code}"
        )


# ===========================================================================
# OCC on tutor PATCH (PRD §2.7)
# ===========================================================================
class TestTutorPatchOcc:
    def test_patch_with_stale_version_rejected(self, api):
        """PRD §2.7: "When supplied, the server compares it to the
        current version of the target row; mismatch is rejected with
        ERR_VERSION_CONFLICT."

        Claim: PATCH carrying a stale `version` returns
        ERR_VERSION_CONFLICT.
        """
        tutor = create_tutor()
        # First patch advances version.
        first = validate_success(api.patch_tutor(
            tutor["id"],
            patch_tutor_payload(display_name="Renamed Once"),
            make_tutor_headers(tutor["id"]),
        ))
        assert first["version"] == 2
        # Now PATCH with stale version=1.
        res = api.patch_tutor(
            tutor["id"],
            patch_tutor_payload(display_name="Renamed Twice", version=1),
            make_tutor_headers(tutor["id"]),
        )
        validate_error(res, "ERR_VERSION_CONFLICT")

    def test_patch_without_version_skips_check(self, api):
        """PRD §2.7: "When omitted, the server skips the check and
        proceeds."

        Claim: PATCH without `version` field still succeeds even if
        the row has been mutated since the test last read it.
        """
        tutor = create_tutor()
        res = validate_success(api.patch_tutor(
            tutor["id"],
            patch_tutor_payload(display_name="No-OCC Patch"),
            make_tutor_headers(tutor["id"]),
        ))
        assert res["display_name"] == "No-OCC Patch"
        assert res["version"] == 2
