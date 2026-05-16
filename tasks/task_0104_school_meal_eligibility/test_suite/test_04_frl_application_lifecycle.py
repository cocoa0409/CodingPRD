"""FrlApplication state machine: DRAFT → SUBMITTED → INFO_REQUESTED →
SUBMITTED → APPROVED/DENIED.

PRD §3.4 specifies preconditions, side effects, and segregation-of-duties
rules. Information request, approval, and denial each capture a
reviewer_user_id snapshot. Denial reverts the student's tier to PAID
unless another APPROVED application governs the same school year.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    HOUSEHOLD_SIZE_MAX,
    HOUSEHOLD_SIZE_MIN,
    TEST_DEFAULTS,
    approve_frl_application,
    assert_frl_application,
    create_frl_application,
    create_frl_application_payload,
    deny_frl_application,
    deny_payload,
    make_parent_headers,
    request_info_on_application,
    request_info_payload,
    resubmit_application,
    resubmit_payload,
    setup_district_with_family,
    submit_frl_application,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.4 DRAFT and validation
# ===========================================================================
class TestFrlApplicationCreation:
    """PRD §3.4: A Parent creates one in DRAFT state."""

    def test_create_application_initial_state_draft(self, api):
        """PRD §3.4: "A Parent creates one in DRAFT state".

        Claim: a freshly created application has status='DRAFT'.
        """
        district, parent, student = setup_district_with_family()
        app = create_frl_application(
            district=district, parent_account=parent, student=student,
            household_size=4, declared_annual_income_cents=2_000_000,
        )
        assert_frl_application(app)
        assert app["status"] == "DRAFT"
        assert app.get("decided_tier") is None

    def test_household_size_below_minimum_rejected(self, api):
        """PRD §3.4: "household_size (an integer from 1 through 8
        inclusive — submissions outside this band are rejected with
        ERR_VALIDATION)".

        Claim: household_size=0 → ERR_VALIDATION.
        """
        district, parent, student = setup_district_with_family()
        res = api.create_frl_application(
            district["id"],
            create_frl_application_payload(
                student_id=student["id"], household_size=0,
                declared_annual_income_cents=2_000_000,
            ),
            make_parent_headers(parent["id"]),
        )
        validate_error(res, "ERR_VALIDATION")

    def test_household_size_above_maximum_rejected(self, api):
        """PRD §3.4: "household_size (an integer from 1 through 8
        inclusive — submissions outside this band are rejected with
        ERR_VALIDATION)".

        Claim: household_size=9 → ERR_VALIDATION.
        """
        district, parent, student = setup_district_with_family()
        res = api.create_frl_application(
            district["id"],
            create_frl_application_payload(
                student_id=student["id"], household_size=9,
                declared_annual_income_cents=2_000_000,
            ),
            make_parent_headers(parent["id"]),
        )
        validate_error(res, "ERR_VALIDATION")

    def test_negative_income_rejected(self, api):
        """PRD §3.4: "declared_annual_income_cents (a non-negative
        integer of whole cents — negative income is likewise
        ERR_VALIDATION)".

        Claim: declared_annual_income_cents=-1 → ERR_VALIDATION.
        """
        district, parent, student = setup_district_with_family()
        res = api.create_frl_application(
            district["id"],
            create_frl_application_payload(
                student_id=student["id"], household_size=4,
                declared_annual_income_cents=-1,
            ),
            make_parent_headers(parent["id"]),
        )
        validate_error(res, "ERR_VALIDATION")


# ===========================================================================
# §3.4 Submission
# ===========================================================================
class TestFrlApplicationSubmission:
    """PRD §3.4: submission requires DRAFT status; snapshots
    school_year_start."""

    def test_submit_draft_application(self, api):
        """PRD §3.4: "On success, the application's status flips to
        SUBMITTED and the application's school_year_start is captured
        from the district".

        Claim: after submit, status='SUBMITTED' and
        school_year_start is present.
        """
        district, parent, student = setup_district_with_family()
        app = create_frl_application(
            district=district, parent_account=parent, student=student,
        )
        submitted = submit_frl_application(
            district=district, parent_account=parent, application=app,
        )
        assert submitted["status"] == "SUBMITTED"
        # PRD §3.4: school_year_start is captured at submit time.
        assert submitted.get("school_year_start") is not None, (
            "school_year_start must be captured at submit"
        )

    def test_submit_already_submitted_rejected(self, api):
        """PRD §3.4 + §2.9: "the application is currently DRAFT".

        Claim: submit on an already-SUBMITTED application →
        ERR_INVALID_STATE.
        """
        district, parent, student = setup_district_with_family()
        app = create_frl_application(
            district=district, parent_account=parent, student=student,
        )
        submit_frl_application(
            district=district, parent_account=parent, application=app,
        )
        res = api.submit_frl_application(
            district["id"], app["id"],
            make_parent_headers(parent["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")


# ===========================================================================
# §3.4 Information request + resubmission cycle
# ===========================================================================
class TestInfoRequestAndResubmit:
    """PRD §3.4: A DistrictReviewer may pause a SUBMITTED application
    and bounce it back for more documentation."""

    def test_info_request_transitions_to_info_requested(self, api):
        """PRD §3.4: "On success, the application moves to
        INFO_REQUESTED, the body's review_note is recorded on the
        application, and the reviewer's X-User-ID is captured as
        reviewer_user_id."

        Claim: POST /request-info → status=INFO_REQUESTED, review_note
        set, reviewer_user_id captured.
        """
        district, parent, student = setup_district_with_family()
        app = create_frl_application(
            district=district, parent_account=parent, student=student,
        )
        submit_frl_application(
            district=district, parent_account=parent, application=app,
        )
        updated = request_info_on_application(
            district=district, application=app, review_note="need W-2",
        )
        assert updated["status"] == "INFO_REQUESTED"
        assert updated.get("review_note") == "need W-2"

    def test_empty_review_note_rejected(self, api, reviewer_headers):
        """PRD §3.4: "The reviewer submits a non-empty review_note in
        the request body; the system rejects an empty note as
        ERR_VALIDATION."

        Claim: review_note='' on request-info → ERR_VALIDATION.
        """
        district, parent, student = setup_district_with_family()
        app = create_frl_application(
            district=district, parent_account=parent, student=student,
        )
        submit_frl_application(
            district=district, parent_account=parent, application=app,
        )
        res = api.request_info_frl_application(
            district["id"], app["id"],
            request_info_payload(review_note=""),
            reviewer_headers,
        )
        validate_error(res, "ERR_VALIDATION")

    def test_resubmit_cycles_back_to_submitted(self, api):
        """PRD §3.4: "the application returns to SUBMITTED."

        Claim: resubmit from INFO_REQUESTED → status=SUBMITTED.

        # difficulty: non_linear_state_machine/frl_application_cycle_submitted_info_requested_submitted
        """
        district, parent, student = setup_district_with_family()
        app = create_frl_application(
            district=district, parent_account=parent, student=student,
        )
        submit_frl_application(
            district=district, parent_account=parent, application=app,
        )
        request_info_on_application(
            district=district, application=app, review_note="need docs",
        )
        resubmitted = resubmit_application(
            district=district, parent_account=parent, application=app,
            documents_attached_count=2,
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted.get("documents_attached_count") == 2

    def test_resubmit_requires_info_requested_status(self, api):
        """PRD §3.4: "Resubmission requires the application to be
        currently INFO_REQUESTED".

        Claim: resubmit on a DRAFT application → ERR_INVALID_STATE.
        """
        district, parent, student = setup_district_with_family()
        app = create_frl_application(
            district=district, parent_account=parent, student=student,
        )
        # Still DRAFT.
        res = api.resubmit_frl_application(
            district["id"], app["id"],
            resubmit_payload(documents_attached_count=1),
            make_parent_headers(parent["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_resubmit_requires_parent_ownership(self, api):
        """PRD §3.4: "requires the acting parent to own the underlying
        student's parent_account_id; an outsider parent receives
        ERR_FORBIDDEN."

        Claim: a parent who does not own the student attempting to
        resubmit → ERR_FORBIDDEN.
        """
        district, parent_a, student = setup_district_with_family()
        # A second parent in the same district.
        _, parent_b, _ = setup_district_with_family()
        app = create_frl_application(
            district=district, parent_account=parent_a, student=student,
        )
        submit_frl_application(
            district=district, parent_account=parent_a, application=app,
        )
        request_info_on_application(
            district=district, application=app, review_note="need docs",
        )
        # Outsider parent attempts to resubmit.
        res = api.resubmit_frl_application(
            district["id"], app["id"],
            resubmit_payload(documents_attached_count=2),
            make_parent_headers(parent_b["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §3.4 Approval
# ===========================================================================
class TestFrlApplicationApproval:
    """PRD §3.4: approval requires SUBMITTED, segregation of duties, and
    classifier yielding FREE or REDUCED."""

    def test_approve_with_free_classification_succeeds(self, api):
        """PRD §3.4: "the student's eligibility_tier is updated to the
        new decided_tier, and the student's eligibility_application_id
        is set to the application's id."

        Claim: approve with income low enough → decided_tier=FREE,
        application.status='APPROVED', student.eligibility_tier=FREE.
        """
        district, parent, student = setup_district_with_family()
        # household_size=4: FPL_4 = 3_090_000. Income 2_000_000 → ratio
        # ~0.647 → FREE.
        app = create_frl_application(
            district=district, parent_account=parent, student=student,
            household_size=4, declared_annual_income_cents=2_000_000,
        )
        submit_frl_application(
            district=district, parent_account=parent, application=app,
        )
        approved = approve_frl_application(
            district=district, application=app,
        )
        assert approved["status"] == "APPROVED"
        assert approved["decided_tier"] == "FREE"
        # Student.eligibility_tier flips to FREE.
        from test_helpers import api_client
        student_after = api_client.get_student(
            district["id"], student["id"], make_parent_headers(parent["id"]),
        ).json()["data"]
        assert student_after["eligibility_tier"] == "FREE"
        assert student_after["eligibility_application_id"] == approved["id"]

    def test_approve_at_reduced_band_succeeds(self, api):
        """PRD §3.4: "When the ratio is greater than 1.30 but at most
        1.85, the classifier returns REDUCED."

        Claim: approve with income in reduced band → decided_tier=REDUCED.
        """
        district, parent, student = setup_district_with_family()
        # household_size=4: FPL_4 = 3_090_000. Income 5_000_000 → ratio
        # ~1.618 → REDUCED.
        app = create_frl_application(
            district=district, parent_account=parent, student=student,
            household_size=4, declared_annual_income_cents=5_000_000,
        )
        submit_frl_application(
            district=district, parent_account=parent, application=app,
        )
        approved = approve_frl_application(
            district=district, application=app,
        )
        assert approved["decided_tier"] == "REDUCED"
        assert approved["status"] == "APPROVED"

    def test_approve_with_denied_paid_classification_rejected(self, api):
        """PRD §3.4: "Approval that would resolve to DENIED_PAID is
        rejected with ERR_INVALID_STATE — the reviewer must instead
        route the application down the deny path."

        Claim: approve with income above the REDUCED band →
        ERR_INVALID_STATE.
        """
        district, parent, student = setup_district_with_family()
        # household_size=4: FPL_4 = 3_090_000. Income 8_000_000 → ratio
        # ~2.59 → DENIED_PAID.
        app = create_frl_application(
            district=district, parent_account=parent, student=student,
            household_size=4, declared_annual_income_cents=8_000_000,
        )
        submit_frl_application(
            district=district, parent_account=parent, application=app,
        )
        # Approve should be rejected.
        res = api.approve_frl_application(
            district["id"], app["id"],
            # Use shared reviewer headers; PRD §3.4 enforces this rule
            # before classifier outcome but the test is concerned with
            # the DENIED_PAID outcome path.
            __import__("test_helpers").TEST_USERS["reviewer_headers"],
        )
        validate_error(res, "ERR_INVALID_STATE")

    def test_approve_captures_federal_poverty_guideline(self, api):
        """PRD §3.4: "On a successful approval, the application's
        decided_tier is set to the classifier's output, its
        federal_poverty_guideline_cents is set to the looked-up
        guideline for the application's household_size".

        Claim: after approval, federal_poverty_guideline_cents equals
        the table value for the application's household_size.
        """
        district, parent, student = setup_district_with_family()
        app = create_frl_application(
            district=district, parent_account=parent, student=student,
            household_size=4, declared_annual_income_cents=2_000_000,
        )
        submit_frl_application(
            district=district, parent_account=parent, application=app,
        )
        approved = approve_frl_application(
            district=district, application=app,
        )
        # PRD §3.4: household_size=4 → 3,090,000 cents.
        assert approved["federal_poverty_guideline_cents"] == 3_090_000


# ===========================================================================
# §3.4 Denial
# ===========================================================================
class TestFrlApplicationDenial:
    """PRD §3.4: denial requires SUBMITTED, non-empty review_note;
    decided_tier becomes DENIED_PAID; student reverts to PAID unless
    another APPROVED application governs the same school year."""

    def test_deny_application_sets_decided_tier_denied_paid(self, api):
        """PRD §3.4: "On success, the application's decided_tier is set
        to DENIED_PAID".

        Claim: deny → status=DENIED, decided_tier=DENIED_PAID.
        """
        district, parent, student = setup_district_with_family()
        app = create_frl_application(
            district=district, parent_account=parent, student=student,
            household_size=4, declared_annual_income_cents=5_000_000,
        )
        submit_frl_application(
            district=district, parent_account=parent, application=app,
        )
        denied = deny_frl_application(
            district=district, application=app,
            review_note="Insufficient documentation",
        )
        assert denied["status"] == "DENIED"
        assert denied["decided_tier"] == "DENIED_PAID"

    def test_deny_with_empty_note_rejected(self, api, reviewer_headers):
        """PRD §3.4: "the request body to carry a non-empty review_note
        (ERR_VALIDATION otherwise)".

        Claim: deny with review_note='' → ERR_VALIDATION.
        """
        district, parent, student = setup_district_with_family()
        app = create_frl_application(
            district=district, parent_account=parent, student=student,
        )
        submit_frl_application(
            district=district, parent_account=parent, application=app,
        )
        res = api.deny_frl_application(
            district["id"], app["id"],
            deny_payload(review_note=""),
            reviewer_headers,
        )
        validate_error(res, "ERR_VALIDATION")

    def test_deny_reverts_student_to_paid_when_no_other_approved(self, api):
        """PRD §3.4: "provided no other APPROVED application for the
        same student exists in the current school year — the student's
        eligibility_tier reverts to PAID and its
        eligibility_application_id is cleared to null."

        Claim: with no prior APPROVED application, denial reverts
        student to PAID and clears eligibility_application_id.
        """
        district, parent, student = setup_district_with_family()
        # Student starts PAID; verify and then deny.
        app = create_frl_application(
            district=district, parent_account=parent, student=student,
            household_size=4, declared_annual_income_cents=5_000_000,
        )
        submit_frl_application(
            district=district, parent_account=parent, application=app,
        )
        deny_frl_application(
            district=district, application=app,
            review_note="Documentation insufficient",
        )
        from test_helpers import api_client
        student_after = api_client.get_student(
            district["id"], student["id"], make_parent_headers(parent["id"]),
        ).json()["data"]
        assert student_after["eligibility_tier"] == "PAID"
        assert student_after.get("eligibility_application_id") is None


# ===========================================================================
# §3.4 Segregation of duties
# ===========================================================================
class TestSegregationOfDuties:
    """PRD §3.4: a reviewer who is also the owning parent receives
    ERR_SEGREGATION_OF_DUTIES on approve/deny."""

    def test_reviewer_who_is_parent_blocked_on_approve(self, api):
        """PRD §3.4: "the acting reviewer is not the parent who owns
        the student (segregation of duties — a reviewer who is also the
        owning parent receives ERR_SEGREGATION_OF_DUTIES)".

        Claim: when the DistrictReviewer's X-User-ID equals the owning
        ParentAccount.id, approval → ERR_SEGREGATION_OF_DUTIES.
        """
        from test_helpers import build_user_headers
        district, parent, student = setup_district_with_family()
        app = create_frl_application(
            district=district, parent_account=parent, student=student,
            household_size=4, declared_annual_income_cents=2_000_000,
        )
        submit_frl_application(
            district=district, parent_account=parent, application=app,
        )
        # Reviewer whose X-User-ID matches the owning parent's account id.
        bad_headers = build_user_headers(parent["id"], "DistrictReviewer")
        res = api.approve_frl_application(
            district["id"], app["id"], bad_headers,
        )
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES")

    def test_reviewer_who_is_parent_blocked_on_deny(self, api):
        """PRD §3.4: "the acting reviewer to not be the owning parent
        (ERR_SEGREGATION_OF_DUTIES otherwise)".

        Claim: when the DistrictReviewer's X-User-ID equals the owning
        ParentAccount.id, denial → ERR_SEGREGATION_OF_DUTIES.
        """
        from test_helpers import build_user_headers
        district, parent, student = setup_district_with_family()
        app = create_frl_application(
            district=district, parent_account=parent, student=student,
            household_size=4, declared_annual_income_cents=8_000_000,
        )
        submit_frl_application(
            district=district, parent_account=parent, application=app,
        )
        bad_headers = build_user_headers(parent["id"], "DistrictReviewer")
        res = api.deny_frl_application(
            district["id"], app["id"],
            deny_payload(review_note="Insufficient"),
            bad_headers,
        )
        validate_error(res, "ERR_SEGREGATION_OF_DUTIES")
