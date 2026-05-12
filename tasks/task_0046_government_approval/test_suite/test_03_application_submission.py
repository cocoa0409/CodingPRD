"""Application submission validations and the identity-and-payment gate
into UNDER_REVIEW.

Covers PRD §3.4 (Submitting an Application), §3.5 (Identity-and-Payment
Gate), §2.7 (validation priority).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_application,
    create_published_certificate_template,
    create_published_material_template,
    create_department,
    create_matter,
    create_matter_version_draft,
    create_matter_version_payload,
    drive_to_under_review,
    emit_event_payload,
    emit_identity_verified,
    emit_payment_settled,
    get_application,
    get_success_data,
    make_applicant_headers,
    make_catalog_manager_headers,
    make_routing,
    publish_matter_version,
    setup_single_department_published_version,
    setup_application_under_review_single_dept,
    submit_application,
    submit_application_payload,
    submitted_material_entry,
    TEST_USERS,
    unique_applicant_id,
    validate_error,
    validate_success,
)


# ===========================================================================
# Submission referential checks (PRD §3.4)
# ===========================================================================
class TestSubmissionReferentialChecks:
    def test_submit_missing_required_material_yields_err_material_missing(
        self, api,
    ):
        """PRD §3.4: "every entry of the pinned version's
        required_material_template_ids must be covered by exactly one
        matching submitted_materials entry (failure is
        ERR_MATERIAL_MISSING)."

        Claim: submitting an Application with empty submitted_materials
        when the version requires one -> ERR_MATERIAL_MISSING.
        """
        ctx = setup_single_department_published_version(fee_amount_cents=0)
        applicant_id = unique_applicant_id()
        applicant_headers = make_applicant_headers(applicant_id)
        payload = submit_application_payload(
            matter_version_id=ctx["version"]["id"],
            submitted_materials=[],
            channel="ONLINE",
        )
        resp = api.submit_application(payload, applicant_headers)
        validate_error(resp, ApiErrorId.ERR_MATERIAL_MISSING)

    def test_submit_with_unpublished_material_yields_type_mismatch(self, api):
        """PRD §3.4: "each submitted entry's material_template_id must
        reference a MaterialTemplate whose status is PUBLISHED and whose
        material_type matches the submitted material type (failure is
        ERR_MATERIAL_TYPE_MISMATCH)."

        Claim: submitting against a DRAFT material_template_id -> ERR_MATERIAL_TYPE_MISMATCH.
        """
        ctx = setup_single_department_published_version()
        # Create a NEW material that is DRAFT (never published).
        from test_helpers import create_material_template_payload
        draft_resp = api.create_material_template(
            create_material_template_payload(),
            ctx["catalog_manager_headers"],
        )
        draft_material = validate_success(draft_resp, expected_status=201)
        # Submission tries to substitute the DRAFT material in place of
        # the version's published material. The DRAFT id is not in
        # required_material_template_ids; the canonical failure here is
        # ERR_MATERIAL_MISSING (priority 6 < priority 7). To trigger
        # priority 7 cleanly, supply the version's required material PLUS
        # an extra entry referring to the DRAFT id.
        applicant_id = unique_applicant_id()
        applicant_headers = make_applicant_headers(applicant_id)
        payload = submit_application_payload(
            matter_version_id=ctx["version"]["id"],
            submitted_materials=[
                submitted_material_entry(ctx["material_template"]["id"]),
                submitted_material_entry(draft_material["id"]),
            ],
        )
        resp = api.submit_application(payload, applicant_headers)
        # Expect ERR_MATERIAL_TYPE_MISMATCH: the extra entry references
        # a DRAFT (non-PUBLISHED) MaterialTemplate.
        validate_error(resp, ApiErrorId.ERR_MATERIAL_TYPE_MISMATCH)

    def test_submit_online_missing_eform_payload_yields_err_eform_incomplete(
        self, api,
    ):
        """PRD §3.4: "when the channel is ONLINE and any covered template
        carries an e_form_schema, the corresponding e_form_payload must
        include every required key listed in that schema (failure is
        ERR_EFORM_INCOMPLETE)."

        Claim: ONLINE submission with a covered template that has
        e_form_schema requiring "id_number", but e_form_payload omits
        the key -> ERR_EFORM_INCOMPLETE.
        """
        e_form_schema = {"required": ["id_number"]}
        ctx = setup_single_department_published_version(
            e_form_schema=e_form_schema,
        )
        applicant_id = unique_applicant_id()
        applicant_headers = make_applicant_headers(applicant_id)
        payload = submit_application_payload(
            matter_version_id=ctx["version"]["id"],
            submitted_materials=[
                submitted_material_entry(
                    ctx["material_template"]["id"],
                    e_form_payload={"unrelated": "value"},
                )
            ],
            channel="ONLINE",
        )
        resp = api.submit_application(payload, applicant_headers)
        validate_error(resp, ApiErrorId.ERR_EFORM_INCOMPLETE)

    def test_submit_channel_not_in_allowed_yields_err_channel_not_allowed(
        self, api,
    ):
        """PRD §3.4: "the chosen channel must appear in the pinned
        version's channels set (failure is ERR_CHANNEL_NOT_ALLOWED)."

        Claim: a version with channels=['ONLINE'] rejects an OFFLINE
        submission with ERR_CHANNEL_NOT_ALLOWED.
        """
        ctx = setup_single_department_published_version(channels=["ONLINE"])
        applicant_id = unique_applicant_id()
        applicant_headers = make_applicant_headers(applicant_id)
        payload = submit_application_payload(
            matter_version_id=ctx["version"]["id"],
            submitted_materials=[
                submitted_material_entry(ctx["material_template"]["id"])
            ],
            channel="OFFLINE",
        )
        resp = api.submit_application(payload, applicant_headers)
        validate_error(resp, ApiErrorId.ERR_CHANNEL_NOT_ALLOWED)


# ===========================================================================
# Submission default state (PRD §3.4)
# ===========================================================================
class TestSubmissionDefaults:
    def test_zero_fee_version_skips_payment_to_paid(self, api):
        """PRD §3.4: "The application's payment_status begins at PENDING
        unless the pinned version's fee_amount_cents is 0, in which case
        payment_status is set to PAID immediately at create time."

        Claim: a fee=0 submission has payment_status=='PAID' immediately.
        """
        ctx = setup_single_department_published_version(fee_amount_cents=0)
        application, _hdrs, _id = submit_application(ctx=ctx)
        assert_application(application)
        assert application["payment_status"] == "PAID"
        assert application["review_status"] == "SUBMITTED"

    def test_nonzero_fee_starts_payment_pending(self, api):
        """PRD §3.4: "The application's payment_status begins at PENDING
        unless the pinned version's fee_amount_cents is 0."

        Claim: a fee>0 submission has payment_status=='PENDING' at create.
        """
        ctx = setup_single_department_published_version(fee_amount_cents=1000)
        application, _hdrs, _id = submit_application(ctx=ctx)
        assert_application(application)
        assert application["payment_status"] == "PENDING"
        assert application["review_status"] == "SUBMITTED"
        assert application["identity_verified"] is False

    def test_submission_records_applicant_user_id(self, api):
        """PRD §3.4: "A successful submit creates an Application whose
        review_status is SUBMITTED, whose applicant_user_id is the
        X-User-ID of the submitting principal."

        Claim: Application.applicant_user_id equals X-User-ID at submit.
        """
        ctx = setup_single_department_published_version(fee_amount_cents=0)
        applicant_id = unique_applicant_id()
        application, _hdrs, _id = submit_application(
            ctx=ctx, applicant_id=applicant_id,
        )
        assert application["applicant_user_id"] == applicant_id


# ===========================================================================
# Identity + payment gate -> UNDER_REVIEW (PRD §3.5)
# ===========================================================================
class TestIdentityAndPaymentGate:
    def test_identity_event_alone_does_not_advance_review(self, api):
        """PRD §3.5: "An application sits in SUBMITTED until two facts are
        independently true: identity_verified is true and payment_status
        is PAID."

        Claim: emitting only IDENTITY_VERIFIED on a fee>0 application
        leaves review_status==SUBMITTED with identity_verified=true and
        payment_status==PENDING.

        # difficulty: non_linear_state_machine/application_dual_axis_payment_review_parallel_dimensions
        """
        ctx = setup_single_department_published_version(fee_amount_cents=1000)
        application, _hdrs, _id = submit_application(ctx=ctx)
        emit_identity_verified(application["id"])
        refreshed = get_application(application["id"])
        assert refreshed["identity_verified"] is True
        assert refreshed["payment_status"] == "PENDING"
        assert refreshed["review_status"] == "SUBMITTED"

    def test_both_events_drive_under_review(self, api):
        """PRD §3.5: "The instant both prerequisites hold ... the system
        transitions the application from SUBMITTED to UNDER_REVIEW. That
        transition takes a deep copy of MatterVersion.review_routing into
        pinned_routing_snapshot, creates the ReviewTask rows described in
        §3.2, sets clock_started_at to the server's current time."

        Claim: after both IDENTITY_VERIFIED and PAYMENT_SETTLED on a
        fee>0 application, review_status==UNDER_REVIEW, payment_status==PAID,
        clock_started_at set, and pinned_routing_snapshot present.

        # difficulty: non_linear_state_machine/application_dual_axis_payment_review_parallel_dimensions
        """
        ctx = setup_single_department_published_version(fee_amount_cents=1000)
        application, _hdrs, _id = submit_application(ctx=ctx)
        emit_identity_verified(application["id"])
        emit_payment_settled(application["id"])
        refreshed = get_application(application["id"])
        assert refreshed["payment_status"] == "PAID"
        assert refreshed["review_status"] == "UNDER_REVIEW"
        assert refreshed["clock_started_at"] is not None
        assert isinstance(refreshed["pinned_routing_snapshot"], dict)


# ===========================================================================
# Read ownership (PRD §3.12)
# ===========================================================================
class TestApplicationReadOwnership:
    def test_other_applicant_cannot_read_application(self, api):
        """PRD §3.12: "an applicant only sees their own applications."

        Claim: an Applicant whose X-User-ID differs from
        Application.applicant_user_id cannot GET /applications/{id}.
        """
        ctx = setup_application_under_review_single_dept()
        other_applicant_headers = make_applicant_headers(unique_applicant_id())
        resp = api.get_application(ctx["application"]["id"],
                                   other_applicant_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
