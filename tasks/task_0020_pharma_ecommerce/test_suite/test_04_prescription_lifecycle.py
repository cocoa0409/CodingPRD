"""Prescription upload, review, approval rules, and revocation
(PRD §3.4, §2.10).
"""
import pytest

from test_helpers import (
    validate_error,
    validate_success,
    ApiErrorId,
    setup_basic_platform,
    setup_prescription_scenario,
    setup_approved_prescription_with_order,
    create_platform,
    create_vendor,
    create_pharmacist,
    create_customer,
    create_drug,
    create_otc_drug_on_shelf,
    create_prescription_drug_on_shelf,
    create_two_pharmacists,
    upload_prescription,
    upload_and_approve_prescription,
    approve_prescription,
    advance_clock,
    setup_platform_at_clock,
    add_to_denylist,
    place_order,
    get_prescription,
    get_audit_logs,
    get_external_events,
    find_audit_logs,
    find_external_events,
    prescription_item,
    order_item,
    create_prescription_payload,
    TEST_USERS,
    make_admin_headers,
    make_customer_headers,
    make_prescription_reviewer_headers,
)


# ---------------------------------------------------------------------------
# Upload + auto-advance to REVIEW_PENDING (PRD §3.4)
# ---------------------------------------------------------------------------

class TestPrescriptionUpload:
    """PRD §3.4: 'On creation, a fresh Prescription enters status UPLOADED
    and is immediately auto-advanced to REVIEW_PENDING by the system after
    input validation.'
    """

    def test_uploaded_prescription_in_review_pending(self, api):
        """PRD §3.4: 'enters status UPLOADED and is immediately auto-advanced
        to REVIEW_PENDING.'"""
        s = setup_prescription_scenario(api)
        rx = upload_prescription(
            api, s["platform"]["id"], s["customer"],
            drug_items=[prescription_item(s["drug"]["id"], qty=1)],
            issued_at="2025-01-01T00:00:00.000Z",
            validity_days=30,
        )
        assert rx["status"] == "REVIEW_PENDING"

    def test_empty_drug_items_array_rejected(self, api):
        """PRD §3.4: drug_items is a structured array; an empty array fails
        generic input validation as ERR_INVALID_REQUEST.

        # difficulty: boundary_precision_check/empty_drug_items_array_on_prescription_upload
        """
        s = setup_prescription_scenario(api)
        payload = create_prescription_payload(
            s["customer"]["id"], drug_items=[],
            issued_at="2025-01-01T00:00:00.000Z", validity_days=30,
        )
        resp = api.create_prescription(s["platform"]["id"], payload,
                                          make_customer_headers(s["customer"]["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ---------------------------------------------------------------------------
# Approval preconditions (PRD §3.4)
# ---------------------------------------------------------------------------

class TestPrescriptionApproval:
    """PRD §3.4: 'Approval transitions REVIEW_PENDING to APPROVED and sets
    reviewer_pharmacist_id to the reviewer's X-User-ID.'

    The transition has five preconditions:
      1) acting pharmacist's qualification_status must be ACTIVE → ERR_PHARMACIST_NOT_ACTIVE
      2) clock < issued_at + validity_days → ERR_PRESCRIPTION_EXPIRED
      3) prescriber_license_no NOT in denylist → ERR_PRESCRIBER_NOT_QUALIFIED
      4) every drug ON_SHELF and PRESCRIPTION → ERR_DRUG_NOT_PRESCRIBABLE
      5) no contraindication intersection → ERR_CONTRAINDICATION_VIOLATION
    """

    def test_approve_sets_reviewer_pharmacist_id(self, api):
        """PRD §3.4: 'Approval transitions REVIEW_PENDING to APPROVED and
        sets reviewer_pharmacist_id to the reviewer's X-User-ID.'

        Identity threading: PR pharmacist's X-User-ID is the actual Pharmacist.id.
        """
        s = setup_prescription_scenario(api)
        rx = upload_prescription(
            api, s["platform"]["id"], s["customer"],
            drug_items=[prescription_item(s["drug"]["id"], qty=1)],
            issued_at="2025-01-01T00:00:00.000Z", validity_days=30,
        )
        approved = approve_prescription(api, s["platform"]["id"], rx["id"],
                                            s["pr_pharmacist"])
        assert approved["status"] == "APPROVED"
        assert approved["reviewer_pharmacist_id"] == s["pr_pharmacist"]["id"]

    def test_approve_emits_external_event(self, api):
        """PRD §3.4: 'emits an ExternalEvent on channel E_PRESCRIPTION_PLATFORM
        with event_type prescription.approved.'"""
        s = setup_prescription_scenario(api)
        rx = upload_prescription(
            api, s["platform"]["id"], s["customer"],
            drug_items=[prescription_item(s["drug"]["id"], qty=1)],
            issued_at="2025-01-01T00:00:00.000Z", validity_days=30,
        )
        approve_prescription(api, s["platform"]["id"], rx["id"], s["pr_pharmacist"])
        events = get_external_events(api, s["platform"]["id"])
        match = find_external_events(events, channel="E_PRESCRIPTION_PLATFORM",
                                         event_type="prescription.approved",
                                         subject_id=rx["id"])
        assert len(match) >= 1, "Expected prescription.approved ExternalEvent"

    def test_approve_appends_audit_log(self, api):
        """PRD §3.4: 'appends an AuditLog row with action PRESCRIPTION_APPROVED
        and subject_type PRESCRIPTION.'"""
        s = setup_prescription_scenario(api)
        rx = upload_prescription(
            api, s["platform"]["id"], s["customer"],
            drug_items=[prescription_item(s["drug"]["id"], qty=1)],
            issued_at="2025-01-01T00:00:00.000Z", validity_days=30,
        )
        approve_prescription(api, s["platform"]["id"], rx["id"], s["pr_pharmacist"])
        logs = get_audit_logs(api, s["platform"]["id"])
        match = find_audit_logs(logs, subject_id=rx["id"],
                                  subject_type="PRESCRIPTION",
                                  action="PRESCRIPTION_APPROVED")
        assert len(match) == 1

    def test_approve_expired_prescription_rejected(self, api):
        """PRD §3.4: 'current_clock_iso must be strictly less than issued_at
        plus the smaller of validity_days and the per-control-category
        validity-days cap enforced by the server (otherwise
        ERR_PRESCRIPTION_EXPIRED).'"""
        clock = "2025-02-01T00:00:00.000Z"
        s = setup_prescription_scenario(api, clock_iso=clock)
        # issued at 2025-01-01, valid 7 days → expires 2025-01-08; clock=2025-02-01 is past.
        rx = upload_prescription(
            api, s["platform"]["id"], s["customer"],
            drug_items=[prescription_item(s["drug"]["id"], qty=1)],
            issued_at="2025-01-01T00:00:00.000Z", validity_days=7,
        )
        resp = api.approve_prescription(
            s["platform"]["id"], rx["id"],
            make_prescription_reviewer_headers(s["pr_pharmacist"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PRESCRIPTION_EXPIRED.value)

    def test_approve_with_denylisted_prescriber_rejected(self, api):
        """PRD §3.4: 'the prescription's prescriber_license_no must not appear
        on the prescriber denylist (otherwise ERR_PRESCRIBER_NOT_QUALIFIED).'"""
        s = setup_prescription_scenario(api)
        license_no = "LIC-DENIED-001"
        add_to_denylist(api, s["platform"]["id"], license_no, "Test reason")
        rx = upload_prescription(
            api, s["platform"]["id"], s["customer"],
            drug_items=[prescription_item(s["drug"]["id"], qty=1)],
            issued_at="2025-01-01T00:00:00.000Z", validity_days=30,
            prescriber_license_no=license_no,
        )
        resp = api.approve_prescription(
            s["platform"]["id"], rx["id"],
            make_prescription_reviewer_headers(s["pr_pharmacist"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PRESCRIBER_NOT_QUALIFIED.value)

    def test_approve_with_otc_drug_in_drug_items_rejected(self, api):
        """PRD §3.4: 'every drug_id in drug_items must resolve to a Drug
        whose status is ON_SHELF and whose classification is PRESCRIPTION
        (otherwise ERR_DRUG_NOT_PRESCRIBABLE).'"""
        pf, vendor = setup_basic_platform(api)
        otc = create_otc_drug_on_shelf(api, pf["id"], vendor["id"])
        customer = create_customer(api, pf["id"], real_name_verified=True)
        pr, _rr = create_two_pharmacists(api, pf["id"])
        rx = upload_prescription(api, pf["id"], customer,
                                    drug_items=[prescription_item(otc["id"], qty=1)],
                                    issued_at="2025-01-01T00:00:00.000Z",
                                    validity_days=30)
        resp = api.approve_prescription(
            pf["id"], rx["id"],
            make_prescription_reviewer_headers(pr["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DRUG_NOT_PRESCRIBABLE.value)

    def test_approve_with_contraindication_rejected(self, api):
        """PRD §3.4: 'for every drug, the intersection of its contraindications
        array with the customer's special_population_flags must be empty
        (otherwise ERR_CONTRAINDICATION_VIOLATION).'"""
        s = setup_prescription_scenario(
            api,
            drug_overrides={"contraindications": ["PREGNANCY"]},
            customer_overrides={"special_population_flags": ["PREGNANCY"]},
        )
        rx = upload_prescription(
            api, s["platform"]["id"], s["customer"],
            drug_items=[prescription_item(s["drug"]["id"], qty=1)],
            issued_at="2025-01-01T00:00:00.000Z", validity_days=30,
        )
        resp = api.approve_prescription(
            s["platform"]["id"], rx["id"],
            make_prescription_reviewer_headers(s["pr_pharmacist"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CONTRAINDICATION_VIOLATION.value)

    def test_approve_pharmacist_not_active_rejected(self, api):
        """PRD §3.4: 'the acting pharmacist's qualification_status must be
        ACTIVE (otherwise ERR_PHARMACIST_NOT_ACTIVE).'

        PRD §3.3: 'A PlatformAdmin may also suspend a pharmacist directly,
        transitioning ACTIVE to SUSPENDED.'
        """
        s = setup_prescription_scenario(api)
        # Suspend the PR pharmacist.
        api.suspend_pharmacist(s["platform"]["id"], s["pr_pharmacist"]["id"],
                                  TEST_USERS["admin_headers"])
        rx = upload_prescription(
            api, s["platform"]["id"], s["customer"],
            drug_items=[prescription_item(s["drug"]["id"], qty=1)],
            issued_at="2025-01-01T00:00:00.000Z", validity_days=30,
        )
        resp = api.approve_prescription(
            s["platform"]["id"], rx["id"],
            make_prescription_reviewer_headers(s["pr_pharmacist"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PHARMACIST_NOT_ACTIVE.value)


# ---------------------------------------------------------------------------
# Approve idempotency: state check (PRD §3.4)
# ---------------------------------------------------------------------------

class TestApproveStateCheck:
    """PRD §3.4: 'Both approval and rejection require the prescription to
    currently be in REVIEW_PENDING; calling either on a different state
    returns ERR_PRESCRIPTION_NOT_IN_REVIEW.'
    """

    def test_approve_already_approved_rejected(self, api):
        """Calling approve twice → the second call returns ERR_PRESCRIPTION_NOT_IN_REVIEW."""
        s = setup_prescription_scenario(api)
        rx = upload_and_approve_prescription(
            api, s["platform"]["id"], s["customer"], s["pr_pharmacist"],
            drug_items=[prescription_item(s["drug"]["id"], qty=1)],
            issued_at="2025-01-01T00:00:00.000Z", validity_days=30,
        )
        # Now status is APPROVED; second approve must fail.
        resp = api.approve_prescription(
            s["platform"]["id"], rx["id"],
            make_prescription_reviewer_headers(s["pr_pharmacist"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PRESCRIPTION_NOT_IN_REVIEW.value)

    def test_reject_review_pending_prescription(self, api):
        """PRD §3.4: 'Rejection transitions REVIEW_PENDING to REJECTED.'"""
        s = setup_prescription_scenario(api)
        rx = upload_prescription(
            api, s["platform"]["id"], s["customer"],
            drug_items=[prescription_item(s["drug"]["id"], qty=1)],
            issued_at="2025-01-01T00:00:00.000Z", validity_days=30,
        )
        resp = api.reject_prescription(
            s["platform"]["id"], rx["id"],
            make_prescription_reviewer_headers(s["pr_pharmacist"]["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == "REJECTED"


# ---------------------------------------------------------------------------
# Prescription revocation (PRD §3.4)
# ---------------------------------------------------------------------------

class TestPrescriptionRevocation:
    """PRD §3.4: 'A PrescriptionReviewer (or a PlatformAdmin) may revoke an
    approved prescription, transitioning APPROVED to REVOKED, but only if no
    order in PHARMACIST_REVIEWING, APPROVED, DISPENSED, SHIPPED, or DELIVERED
    references the prescription; otherwise the request is rejected with
    ERR_PRESCRIPTION_IN_USE.'
    """

    def test_revoke_with_pending_review_order_succeeds_and_cancels(self, api):
        """PRD §3.4: 'cascades: every order in dispensing_status PENDING_REVIEW
        that references this prescription is moved to dispensing_status
        CANCELLED.'"""
        s = setup_approved_prescription_with_order(api)
        # Order is in PENDING_REVIEW, not in the blocking set; revoke succeeds.
        resp = api.revoke_prescription(
            s["platform"]["id"], s["prescription"]["id"],
            make_prescription_reviewer_headers(s["pr_pharmacist"]["id"]),
        )
        data = validate_success(resp)
        assert data["status"] == "REVOKED"
        # Cascaded order → CANCELLED.
        from test_helpers import get_order
        order_after = get_order(api, s["platform"]["id"], s["order"]["id"])
        assert order_after["dispensing_status"] == "CANCELLED"

    def test_revoke_with_pharmacist_reviewing_order_rejected(self, api):
        """PRD §3.4: 'no order in PHARMACIST_REVIEWING ... references the
        prescription; otherwise the request is rejected with
        ERR_PRESCRIPTION_IN_USE.'"""
        from test_helpers import setup_order_in_review
        s = setup_order_in_review(api)
        resp = api.revoke_prescription(
            s["platform"]["id"], s["prescription"]["id"],
            make_prescription_reviewer_headers(s["pr_pharmacist"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PRESCRIPTION_IN_USE.value)
