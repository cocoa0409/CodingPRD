"""Pharmacist re-review: segregation of duties, reviewer assignment, the
revision cycle and its cap, and reject/refund cascade
(PRD §3.6, §2.7).
"""
import pytest

from test_helpers import (
    validate_error,
    validate_success,
    ApiErrorId,
    setup_otc_order_in_review,
    setup_order_in_review,
    setup_approved_prescription_with_order,
    setup_prescription_scenario,
    setup_otc_purchase_scenario,
    create_pharmacist,
    create_two_pharmacists,
    upload_and_approve_prescription,
    place_order,
    pay_order,
    open_pharmacist_review,
    approve_review,
    reject_review,
    request_change,
    resume_review,
    get_order,
    get_review,
    get_audit_logs,
    get_external_events,
    find_audit_logs,
    find_external_events,
    prescription_item,
    order_item,
    open_pharmacist_review_payload,
    approve_review_payload,
    reject_review_payload,
    request_change_payload,
    TEST_USERS,
    make_pharmacist_re_reviewer_headers,
    make_prescription_reviewer_headers,
)


# ---------------------------------------------------------------------------
# Open pharmacist review (PRD §3.6)
# ---------------------------------------------------------------------------

class TestOpenPharmacistReview:
    """PRD §3.6: 'Once an order with a prescription line is in
    dispensing_status PENDING_REVIEW, a PharmacistReReviewer opens a
    second-line review with a payload containing the assigned_pharmacist_id
    of the pharmacist who will conduct the review. This action transitions
    the order's dispensing_status from PENDING_REVIEW to PHARMACIST_REVIEWING,
    creates a fresh PharmacistReview row directly in status IN_REVIEW (the
    nominal PENDING state is not externally observable), and stores the new
    review's id on the order's pharmacist_review_id.'
    """

    def test_open_review_creates_in_review(self, api):
        """PRD §3.6: 'creates a fresh PharmacistReview row directly in
        status IN_REVIEW.'"""
        s = setup_approved_prescription_with_order(api)
        review = open_pharmacist_review(api, s["platform"]["id"],
                                            s["order"], s["rr_pharmacist"])
        assert review["status"] == "IN_REVIEW"
        assert review["assigned_pharmacist_id"] == s["rr_pharmacist"]["id"]

    def test_open_review_drives_dispensing_to_pharmacist_reviewing(self, api):
        """PRD §3.6: 'transitions the order's dispensing_status from
        PENDING_REVIEW to PHARMACIST_REVIEWING.'"""
        s = setup_approved_prescription_with_order(api)
        open_pharmacist_review(api, s["platform"]["id"],
                                  s["order"], s["rr_pharmacist"])
        order_after = get_order(api, s["platform"]["id"], s["order"]["id"])
        assert order_after["dispensing_status"] == "PHARMACIST_REVIEWING"

    def test_open_review_segregation_of_duties_violation(self, api):
        """PRD §3.6: 'The acting pharmacist's X-User-ID must be different from
        the prescription's reviewer_pharmacist_id (otherwise
        ERR_SEGREGATION_OF_DUTIES_VIOLATION).'

        Concretely: PR pharmacist approved the prescription;
        PR pharmacist also tries to open the re-review → SOD violation.
        """
        s = setup_approved_prescription_with_order(api)
        # Use PR pharmacist (the approver) as the second-line reviewer.
        payload = open_pharmacist_review_payload(s["pr_pharmacist"]["id"])
        resp = api.open_pharmacist_review(
            s["platform"]["id"], s["order"]["id"], payload,
            make_pharmacist_re_reviewer_headers(s["pr_pharmacist"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES_VIOLATION.value)

    def test_open_review_not_in_pending_review_rejected(self, api):
        """PRD §3.6: 'The order's dispensing_status must be PENDING_REVIEW
        (otherwise ERR_ORDER_NOT_REVIEWABLE).'

        # difficulty: priority_pair_validation_conflict/state_vs_segregation_of_duties (state half)
        """
        s = setup_otc_purchase_scenario(api)
        order = place_order(api, s["platform"]["id"], s["customer"],
                              items=[order_item(s["drug"]["id"], qty=1, unit_price_cents=1000)])
        # Cancel order so dispensing_status = CANCELLED.
        from test_helpers import cancel_order
        cancel_order(api, s["platform"]["id"], order)
        rr = create_pharmacist(api, s["platform"]["id"])
        payload = open_pharmacist_review_payload(rr["id"])
        resp = api.open_pharmacist_review(
            s["platform"]["id"], order["id"], payload,
            make_pharmacist_re_reviewer_headers(rr["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_REVIEWABLE.value)

    def test_open_review_pharmacist_not_active_rejected(self, api):
        """PRD §3.6: 'The acting pharmacist's qualification_status must be
        ACTIVE (otherwise ERR_PHARMACIST_NOT_ACTIVE).'"""
        s = setup_approved_prescription_with_order(api)
        # Suspend the RR pharmacist.
        api.suspend_pharmacist(s["platform"]["id"], s["rr_pharmacist"]["id"],
                                  TEST_USERS["admin_headers"])
        payload = open_pharmacist_review_payload(s["rr_pharmacist"]["id"])
        resp = api.open_pharmacist_review(
            s["platform"]["id"], s["order"]["id"], payload,
            make_pharmacist_re_reviewer_headers(s["rr_pharmacist"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PHARMACIST_NOT_ACTIVE.value)


# ---------------------------------------------------------------------------
# Approve review (PRD §3.6)
# ---------------------------------------------------------------------------

class TestApproveReview:
    """PRD §3.6: 'The approve action requires the review to be currently
    IN_REVIEW (otherwise ERR_REVIEW_NOT_IN_REVIEW); the request body must
    set both interaction_check_passed and dosage_rationality_passed to true
    (otherwise ERR_REVIEW_CHECKS_FAILED); X-User-ID must equal the review's
    assigned_pharmacist_id (otherwise ERR_REVIEWER_MISMATCH); X-User-ID must
    still be different from the prescription's reviewer_pharmacist_id
    (otherwise ERR_SEGREGATION_OF_DUTIES_VIOLATION); and the acting
    pharmacist must still be ACTIVE (otherwise ERR_PHARMACIST_NOT_ACTIVE).'

    'Approval transitions the review to APPROVED, cascades the order's
    dispensing_status from PHARMACIST_REVIEWING to APPROVED, and appends an
    AuditLog row with action PHARMACIST_REVIEW_APPROVED.'
    """

    def test_approve_review_succeeds_and_cascades_to_order(self, api):
        s = setup_otc_order_in_review(api, paid=True)
        approved = approve_review(api, s["platform"]["id"], s["order"]["id"],
                                       s["review"]["id"], s["rr_pharmacist"])
        assert approved["status"] == "APPROVED"
        order_after = get_order(api, s["platform"]["id"], s["order"]["id"])
        assert order_after["dispensing_status"] == "APPROVED"

    def test_approve_appends_audit_log(self, api):
        """PRD §3.6: 'appends an AuditLog row with action
        PHARMACIST_REVIEW_APPROVED.'"""
        s = setup_otc_order_in_review(api, paid=True)
        approve_review(api, s["platform"]["id"], s["order"]["id"],
                          s["review"]["id"], s["rr_pharmacist"])
        logs = get_audit_logs(api, s["platform"]["id"])
        match = find_audit_logs(logs, subject_id=s["review"]["id"],
                                  action="PHARMACIST_REVIEW_APPROVED")
        assert len(match) == 1

    def test_approve_with_failed_checks_rejected(self, api):
        """PRD §3.6: 'the request body must set both interaction_check_passed
        and dosage_rationality_passed to true (otherwise
        ERR_REVIEW_CHECKS_FAILED).'"""
        s = setup_otc_order_in_review(api, paid=True)
        payload = approve_review_payload(interaction_check_passed=False,
                                              dosage_rationality_passed=True)
        resp = api.approve_pharmacist_review(
            s["platform"]["id"], s["order"]["id"], s["review"]["id"], payload,
            make_pharmacist_re_reviewer_headers(s["rr_pharmacist"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REVIEW_CHECKS_FAILED.value)

    def test_approve_reviewer_mismatch(self, api):
        """PRD §3.6: 'X-User-ID must equal the review's
        assigned_pharmacist_id (otherwise ERR_REVIEWER_MISMATCH).'"""
        s = setup_otc_order_in_review(api, paid=True)
        # Create another pharmacist; use them to attempt approve.
        other = create_pharmacist(api, s["platform"]["id"], full_name="Other RR")
        payload = approve_review_payload()
        resp = api.approve_pharmacist_review(
            s["platform"]["id"], s["order"]["id"], s["review"]["id"], payload,
            make_pharmacist_re_reviewer_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REVIEWER_MISMATCH.value)


# ---------------------------------------------------------------------------
# Reject review (PRD §3.6)
# ---------------------------------------------------------------------------

class TestRejectReview:
    """PRD §3.6: 'The reject action requires the review to be IN_REVIEW
    (otherwise ERR_REVIEW_NOT_IN_REVIEW), decision_notes whose string length
    is at least 10 (otherwise ERR_REVIEW_NOTES_TOO_SHORT), and X-User-ID
    equal to assigned_pharmacist_id (otherwise ERR_REVIEWER_MISMATCH).
    Rejection transitions the review to REJECTED, cascades the order's
    dispensing_status to REJECTED, and — if the order's payment_status was
    PAID — runs the refund cascade (payment_status to REFUNDED, AuditLog
    ORDER_REFUNDED, ExternalEvent order.refunded). It also appends an
    AuditLog row with action PHARMACIST_REVIEW_REJECTED.'
    """

    def test_reject_review_paid_cascades_refund(self, api):
        """PRD §3.6: paid order rejected via review → cascade refund.

        # difficulty: transitive_cascade/review_reject_order_reject_payment_refund
        """
        s = setup_otc_order_in_review(api, paid=True)
        rejected = reject_review(api, s["platform"]["id"], s["order"]["id"],
                                      s["review"]["id"], s["rr_pharmacist"],
                                      decision_notes="interaction risk with concurrent SSRI therapy")
        assert rejected["status"] == "REJECTED"
        order_after = get_order(api, s["platform"]["id"], s["order"]["id"])
        assert order_after["dispensing_status"] == "REJECTED"
        assert order_after["payment_status"] == "REFUNDED"

        # Exactly one order.refunded ExternalEvent (idempotency).
        events = get_external_events(api, s["platform"]["id"])
        match = find_external_events(events, channel="PAYMENT",
                                         event_type="order.refunded",
                                         subject_id=s["order"]["id"])
        assert len(match) == 1, "PRD §2.8: idempotency_key prevents duplicate emission"

    def test_reject_short_notes_rejected(self, api):
        """PRD §3.6: 'decision_notes whose string length is at least 10
        (otherwise ERR_REVIEW_NOTES_TOO_SHORT).'"""
        s = setup_otc_order_in_review(api)
        # 9 char notes → too short.
        resp = api.reject_pharmacist_review(
            s["platform"]["id"], s["order"]["id"], s["review"]["id"],
            reject_review_payload(decision_notes="too short"),
            make_pharmacist_re_reviewer_headers(s["rr_pharmacist"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REVIEW_NOTES_TOO_SHORT.value)

    def test_reject_appends_audit_log(self, api):
        """PRD §3.6: 'appends an AuditLog row with action
        PHARMACIST_REVIEW_REJECTED.'"""
        s = setup_otc_order_in_review(api)
        reject_review(api, s["platform"]["id"], s["order"]["id"],
                         s["review"]["id"], s["rr_pharmacist"],
                         decision_notes="dosage exceeds rationality threshold for this cohort")
        logs = get_audit_logs(api, s["platform"]["id"])
        match = find_audit_logs(logs, subject_id=s["review"]["id"],
                                  action="PHARMACIST_REVIEW_REJECTED")
        assert len(match) == 1


# ---------------------------------------------------------------------------
# Request-change cycle and revision cap (PRD §3.6)
# ---------------------------------------------------------------------------

class TestRevisionCycle:
    """PRD §3.6: 'The request-change action requires the review to be
    IN_REVIEW (otherwise ERR_REVIEW_NOT_IN_REVIEW), decision_notes whose
    string length is at least 10 (otherwise ERR_REVIEW_NOTES_TOO_SHORT), and
    the review's revision_count to be strictly less than the maximum of 2
    revisions (otherwise ERR_REVIEW_MAX_REVISIONS).'
    """

    def test_request_change_then_resume_increments_revision_count(self, api):
        """PRD §3.6: 'Resuming bumps revision_count upward by exactly one.'"""
        s = setup_otc_order_in_review(api)
        request_change(api, s["platform"]["id"], s["order"]["id"],
                          s["review"]["id"], s["rr_pharmacist"],
                          decision_notes="need clarification on dose schedule")
        resumed = resume_review(api, s["platform"]["id"], s["order"]["id"],
                                    s["review"]["id"], s["rr_pharmacist"])
        assert resumed["status"] == "IN_REVIEW"
        assert resumed["revision_count"] == 1

    def test_two_round_trips_then_third_request_change_fails(self, api):
        """PRD §3.6: 'The cycle REQUEST_CHANGE → IN_REVIEW → ... → REQUEST_CHANGE
        may run at most twice before subsequent request-change attempts are
        rejected by the revision cap.'

        # difficulty: non_linear_state_machine/pharmacist_review_request_change_cycle
        """
        s = setup_otc_order_in_review(api)
        pf, order, review, rr = (s["platform"], s["order"], s["review"], s["rr_pharmacist"])

        # First round-trip.
        request_change(api, pf["id"], order["id"], review["id"], rr,
                          decision_notes="first request change reason")
        r1 = resume_review(api, pf["id"], order["id"], review["id"], rr)
        assert r1["status"] == "IN_REVIEW"
        assert r1["revision_count"] == 1

        # Second round-trip.
        request_change(api, pf["id"], order["id"], review["id"], rr,
                          decision_notes="second request change reason")
        r2 = resume_review(api, pf["id"], order["id"], review["id"], rr)
        assert r2["status"] == "IN_REVIEW"
        assert r2["revision_count"] == 2

        # Third request-change → exceeds cap (revision_count must be strictly
        # less than 2 to issue request-change; here revision_count == 2).
        resp = api.request_change_pharmacist_review(
            pf["id"], order["id"], review["id"],
            request_change_payload(decision_notes="third attempt should fail"),
            make_pharmacist_re_reviewer_headers(rr["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REVIEW_MAX_REVISIONS.value)

    def test_resume_when_not_in_request_change_rejected(self, api):
        """PRD §3.6: 'The action requires the review to currently be
        REQUEST_CHANGE (otherwise ERR_REVIEW_NOT_IN_REQUEST_CHANGE).'"""
        s = setup_otc_order_in_review(api)
        # Without first requesting change, attempt resume.
        resp = api.resume_pharmacist_review(
            s["platform"]["id"], s["order"]["id"], s["review"]["id"],
            make_pharmacist_re_reviewer_headers(s["rr_pharmacist"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_REVIEW_NOT_IN_REQUEST_CHANGE.value)


# ---------------------------------------------------------------------------
# Order parallel state dimensions: payment vs dispensing (PRD §3.5, §3.6)
# ---------------------------------------------------------------------------

class TestParallelStateDimensions:
    """PRD §3.5: payment_status (UNPAID → PAID → REFUNDED) and dispensing_status
    (PENDING_REVIEW → ... → DELIVERED) evolve independently. PRD §3.6 reject
    cascade auto-runs refund when paid.

    # difficulty: non_linear_state_machine/order_parallel_payment_and_dispensing_dimensions
    """

    def test_pay_then_open_review_then_reject_cascades_refund(self, api):
        """PRD §3.5 + §3.6: pay (payment dimension) does not change
        dispensing_status; then open-review changes only dispensing_status;
        then review-reject cascades dispensing → REJECTED and payment →
        REFUNDED in one logical step.
        """
        s = setup_otc_order_in_review(api, paid=True)
        # After /pay: payment_status=PAID, dispensing_status=PENDING_REVIEW
        # was satisfied at the moment of pay (paid_before_review=True).
        # After /open-pharmacist-review: payment_status still PAID,
        # dispensing_status=PHARMACIST_REVIEWING.
        order_pre = get_order(api, s["platform"]["id"], s["order"]["id"])
        assert order_pre["payment_status"] == "PAID"
        assert order_pre["dispensing_status"] == "PHARMACIST_REVIEWING"

        # Reject the review with proper notes.
        reject_review(api, s["platform"]["id"], s["order"]["id"],
                         s["review"]["id"], s["rr_pharmacist"],
                         decision_notes="dosage exceeds rationality threshold for this cohort")

        order_post = get_order(api, s["platform"]["id"], s["order"]["id"])
        assert order_post["dispensing_status"] == "REJECTED"
        assert order_post["payment_status"] == "REFUNDED"

        # Both rows in audit: PHARMACIST_REVIEW_REJECTED + ORDER_REFUNDED.
        logs = get_audit_logs(api, s["platform"]["id"])
        rev_rej = find_audit_logs(logs, action="PHARMACIST_REVIEW_REJECTED",
                                     subject_id=s["review"]["id"])
        ord_ref = find_audit_logs(logs, action="ORDER_REFUNDED",
                                     subject_id=s["order"]["id"])
        assert len(rev_rej) == 1
        assert len(ord_ref) == 1
