"""Consent form review cycle (SUBMITTED -> REJECTED -> SUBMITTED -> VERIFIED)
and the registration review gate on all three required forms being VERIFIED."""
from test_helpers import (
    ApiErrorId,
    add_consent_form,
    create_participant,
    create_registration,
    make_director_headers,
    make_guardian_headers,
    review_consent_form,
    setup_program_with_open_trip,
    validate_error,
    validate_success,
)

DIRECTOR = make_director_headers()
GUARDIAN1 = make_guardian_headers("guardian-1")


def _registration_with_two_verified_forms(api):
    """Registration in DRAFT with PARENTAL_CONSENT and CONDUCT_AGREEMENT
    VERIFIED; the MEDICAL_RELEASE is left to the caller."""
    program, trip = setup_program_with_open_trip()
    participant = create_participant(program["id"], "guardian-1")
    registration = create_registration(trip["id"], participant["id"],
                                       "guardian-1")
    for form_type in ("PARENTAL_CONSENT", "CONDUCT_AGREEMENT"):
        form = add_consent_form(registration["id"], form_type, "guardian-1")
        review_consent_form(form["id"], "VERIFY")
    medical = add_consent_form(registration["id"], "MEDICAL_RELEASE",
                               "guardian-1", medical_notes="bee allergy")
    return registration, medical


class TestConsentFormRejectResubmitCycle:
    def test_rejected_form_blocks_submit_until_resubmitted(self, api):
        """PRD §3.3: "missing or still-rejected paperwork surfaces
        `ERR_REQUIRED_FORMS_INCOMPLETE`."
        PRD §3.3: "a guardian (or director) may resubmit a `REJECTED` form while
        the registration is still in `DRAFT` or `SUBMITTED`, replacing
        `signed_by_name`, `signed_at`, and `medical_notes` from the payload,
        clearing `rejection_reason`, and returning the form to `SUBMITTED`."

        Design: Difficulty/non_linear_state_machine/consent_form_reject_resubmit_cycle
        """
        registration, medical = _registration_with_two_verified_forms(api)

        rejected = review_consent_form(medical["id"], "REJECT",
                                       reason="signature illegible")
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "signature illegible"
        assert rejected["reviewed_by_user_id"] == "director-1"

        # A REJECTED form does not satisfy the submit gate.
        blocked = api.submit_registration(registration["id"], GUARDIAN1)
        validate_error(blocked, ApiErrorId.ERR_REQUIRED_FORMS_INCOMPLETE, 422)

        resubmitted = api.resubmit_consent_form(
            medical["id"],
            {"signed_by_name": "G One", "signed_at": "2026-08-03T09:00:00Z",
             "medical_notes": "bee allergy; epipen carried"},
            GUARDIAN1)
        data = validate_success(resubmitted, 200)
        assert data["status"] == "SUBMITTED", "the cycle re-entered SUBMITTED"
        assert data["rejection_reason"] == "", "rejection_reason cleared"
        assert data["medical_notes"] == "bee allergy; epipen carried"
        assert data["signed_by_name"] == "G One"

    def test_cycle_increments_version_each_lap_and_completes(self, api):
        """PRD §2.5: "`version`: an integer that starts at its initial value on
        creation and increments by exactly 1 on every mutation of the entity".
        PRD §3.3: "The cycle is unbounded" — SUBMITTED -> REJECTED -> SUBMITTED
        -> VERIFIED loops on the same row; "Reviewing with `decision` of `VERIFY`
        requires the form to be `SUBMITTED` ... it moves the form to `VERIFIED`".

        Design: Difficulty/non_linear_state_machine/consent_form_reject_resubmit_cycle
        """
        registration, medical = _registration_with_two_verified_forms(api)
        v0 = medical["version"]

        rejected = review_consent_form(medical["id"], "REJECT",
                                       reason="signature illegible")
        assert rejected["version"] == v0 + 1, "reject is one mutation"

        resubmitted = api.resubmit_consent_form(
            medical["id"],
            {"signed_by_name": "G One", "signed_at": "2026-08-03T09:00:00Z",
             "medical_notes": "bee allergy; epipen carried"},
            GUARDIAN1)
        resub_data = validate_success(resubmitted, 200)
        assert resub_data["version"] == v0 + 2, "resubmit is one mutation"

        verified = api.review_consent_form(medical["id"],
                                           {"decision": "VERIFY"}, DIRECTOR)
        final = validate_success(verified, 200)
        assert final["status"] == "VERIFIED"
        assert final["version"] == v0 + 3, "verify is one mutation"

        # With all three required forms VERIFIED the submit gate now passes.
        submitted = api.submit_registration(registration["id"], GUARDIAN1)
        assert validate_success(submitted, 200)["registration_status"] == \
            "SUBMITTED"


class TestReviewApproveRequiresVerifiedForms:
    def test_approve_blocked_while_required_form_only_submitted(self, api):
        """PRD §3.3: "With `decision` of `APPROVE`, the checks run in priority
        order: registration `SUBMITTED`, trip still `REGISTRATION_OPEN`, the
        segregation-of-duties check, all three required forms `VERIFIED` (a
        merely-submitted form is not enough here), and the participant not
        barred — before the capacity fork."
        PRD §5: `ERR_REQUIRED_FORMS_INCOMPLETE` is HTTP 422.

        Design: Difficulty/cross_entity_state_dependency/review_approve_requires_all_required_consent_forms_verified
        """
        registration, medical = _registration_with_two_verified_forms(api)
        submitted = api.submit_registration(registration["id"], GUARDIAN1)
        assert validate_success(submitted, 200)["registration_status"] == \
            "SUBMITTED"

        # Capacity is not the blocker (30 seats free); the SUBMITTED form is.
        blocked = api.review_registration(registration["id"],
                                          {"decision": "APPROVE"}, DIRECTOR)
        validate_error(blocked, ApiErrorId.ERR_REQUIRED_FORMS_INCOMPLETE, 422)

    def test_approve_succeeds_after_third_form_verified_and_acknowledges_conduct(
            self, api):
        """PRD §3.3: "Reviewing with `decision` of `VERIFY` ... moves the form to
        `VERIFIED`, stamps `reviewed_by_user_id` from the caller, and — when the
        form is a `CONDUCT_AGREEMENT` — flips the registration's
        `conduct_acknowledged` to true."
        PRD §3.3: "If `seats_taken` is below `capacity_youth`, the registration
        becomes `APPROVED` and `seats_taken` is recomputed".

        Design: Difficulty/cross_entity_state_dependency/review_approve_requires_all_required_consent_forms_verified
        """
        program, trip = setup_program_with_open_trip()
        participant = create_participant(program["id"], "guardian-1")
        registration = create_registration(trip["id"], participant["id"],
                                           "guardian-1")
        for form_type in ("PARENTAL_CONSENT", "MEDICAL_RELEASE"):
            form = add_consent_form(registration["id"], form_type, "guardian-1")
            review_consent_form(form["id"], "VERIFY")
        conduct = add_consent_form(registration["id"], "CONDUCT_AGREEMENT",
                                   "guardian-1")
        submitted = api.submit_registration(registration["id"], GUARDIAN1)
        assert validate_success(submitted, 200)["registration_status"] == \
            "SUBMITTED"

        # Flip the last required form; the approval fork becomes reachable.
        review_consent_form(conduct["id"], "VERIFY")
        approved = api.review_registration(registration["id"],
                                           {"decision": "APPROVE"}, DIRECTOR)
        data = validate_success(approved, 200)
        assert data["registration_status"] == "APPROVED"
        assert data["conduct_acknowledged"] is True, (
            "CONDUCT_AGREEMENT verification acknowledges the code of conduct")
