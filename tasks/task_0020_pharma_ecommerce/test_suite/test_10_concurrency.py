"""Concurrency: race conditions on prescriptions, reviews, orders, and
shipments (PRD §2.5, §3.4, §3.5, §3.6).
"""
import pytest

from test_helpers import (
    validate_error_is_one_of,
    ApiErrorId,
    setup_otc_purchase_scenario,
    setup_otc_order_in_review,
    setup_approved_prescription_with_order,
    setup_prescription_scenario,
    upload_prescription,
    place_order,
    pay_order,
    cancel_order,
    open_pharmacist_review,
    setup_basic_platform,
    create_pharmacist,
    create_drug,
    create_otc_drug_on_shelf,
    run_race,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    open_pharmacist_review_payload,
    approve_review_payload,
    reject_review_payload,
    prescription_item,
    order_item,
    TEST_USERS,
    make_admin_headers,
    make_customer_headers,
    make_prescription_reviewer_headers,
    make_pharmacist_re_reviewer_headers,
)


# ---------------------------------------------------------------------------
# Prescription approve race (PRD §3.4)
# ---------------------------------------------------------------------------

class TestPrescriptionApproveRace:
    """PRD §3.4: 'Two simultaneous approvals on the same prescription
    serialize on Prescription.status (first writer wins); the loser
    receives ERR_PRESCRIPTION_NOT_IN_REVIEW.'
    """

    def test_two_approvals_one_wins(self, api):
        s = setup_prescription_scenario(api)
        rx = upload_prescription(
            api, s["platform"]["id"], s["customer"],
            drug_items=[prescription_item(s["drug"]["id"], qty=1)],
            issued_at="2025-01-01T00:00:00.000Z", validity_days=30,
        )
        pr = s["pr_pharmacist"]
        headers = make_prescription_reviewer_headers(pr["id"])

        results = run_race(
            lambda: api.approve_prescription(s["platform"]["id"], rx["id"], headers),
            lambda: api.approve_prescription(s["platform"]["id"], rx["id"], headers),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # PRD §3.4 explicitly names ERR_PRESCRIPTION_NOT_IN_REVIEW for the loser.
        loser_status = outcome["failures"][0].status_code
        loser_body = outcome["failures"][0].json()
        assert loser_body["data"]["error_id"] == ApiErrorId.ERR_PRESCRIPTION_NOT_IN_REVIEW.value, \
            f"Expected loser error_id ERR_PRESCRIPTION_NOT_IN_REVIEW, got {loser_body['data']['error_id']}"


# ---------------------------------------------------------------------------
# Open-pharmacist-review race (PRD §3.6)
# ---------------------------------------------------------------------------

class TestOpenReviewRace:
    """PRD §3.6: 'Two PharmacistReReviewer operators racing to open a
    re-review on the same order serialize first-writer-wins on the order's
    pharmacist_review_id field; the loser receives ERR_REVIEW_ALREADY_OPEN.'
    """

    def test_two_open_review_one_wins(self, api):
        s = setup_approved_prescription_with_order(api)
        # Create two distinct second-line pharmacists (must be distinct from
        # the prescription reviewer for SOD).
        rr1 = s["rr_pharmacist"]
        rr2 = create_pharmacist(api, s["platform"]["id"], full_name="RR2 racing")
        # Ensure rr2 != PR (pr_pharmacist).
        assert rr2["id"] != s["pr_pharmacist"]["id"]

        headers1 = make_pharmacist_re_reviewer_headers(rr1["id"])
        headers2 = make_pharmacist_re_reviewer_headers(rr2["id"])
        payload1 = open_pharmacist_review_payload(rr1["id"])
        payload2 = open_pharmacist_review_payload(rr2["id"])

        results = run_race(
            lambda: api.open_pharmacist_review(s["platform"]["id"],
                                                  s["order"]["id"], payload1, headers1),
            lambda: api.open_pharmacist_review(s["platform"]["id"],
                                                  s["order"]["id"], payload2, headers2),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # PRD §3.6 names ERR_REVIEW_ALREADY_OPEN explicitly for the loser.
        loser_body = outcome["failures"][0].json()
        assert loser_body["data"]["error_id"] == ApiErrorId.ERR_REVIEW_ALREADY_OPEN.value, \
            f"Expected ERR_REVIEW_ALREADY_OPEN, got {loser_body['data']['error_id']}"


# ---------------------------------------------------------------------------
# Pay/cancel race (PRD §3.5)
# ---------------------------------------------------------------------------
# Test deleted: STEP 1b unique-derivability failure.
# PRD §3.5 simultaneously asserts (a) "A pay/cancel race on the same
# PENDING_REVIEW order serializes ... exactly one operation wins, and
# the loser receives ERR_ORDER_NOT_PAYABLE" and (b) "Cancellation drives
# dispensing_status to CANCELLED; if the order was PAID, the refund
# cascade ... runs". A faithful PRD reader can implement two divergent
# behaviours: (A) cancel-on-PAID rejects → race "exactly one wins" but
# pay-then-cancel cannot run refund cascade (contradicting (b)); or
# (B) cancel-on-PAID succeeds with refund cascade → pay-then-cancel
# legitimately yields BOTH 200 (contradicting (a)). The race-clause
# assertion is therefore not uniquely derivable from PRD when sequential
# pay-then-cancel is also held PRD-legitimate. Other tests that target
# only the §3.5 cancel-of-paid clause remain.


# ---------------------------------------------------------------------------
# Drug shelve/off-shelve race (PRD §3.2)
# ---------------------------------------------------------------------------

class TestShelveRace:
    """PRD §3.2: 'Two simultaneous shelve/off-shelve calls on the same drug
    serialize on Drug.status: the first writer wins, and the loser
    observes the post-write state and is rejected with
    ERR_DRUG_NOT_PENDING_REVIEW.'
    """

    def test_two_shelves_on_pending_drug_one_wins(self, api):
        pf, vendor = setup_basic_platform(api)
        drug = create_drug(api, pf["id"], vendor["id"])  # PENDING_REVIEW
        admin = TEST_USERS["admin_headers"]

        results = run_race(
            lambda: api.shelve_drug(pf["id"], drug["id"], admin),
            lambda: api.shelve_drug(pf["id"], drug["id"], admin),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser_body = outcome["failures"][0].json()
        assert loser_body["data"]["error_id"] == ApiErrorId.ERR_DRUG_NOT_PENDING_REVIEW.value, \
            f"Expected ERR_DRUG_NOT_PENDING_REVIEW, got {loser_body['data']['error_id']}"


# ---------------------------------------------------------------------------
# Pharmacist review approve/reject race (PRD §3.6)
# ---------------------------------------------------------------------------

class TestReviewApproveRejectRace:
    """PRD §3.6: 'Two pharmacist-review action endpoints racing on the same
    review serialize on PharmacistReview.status via the version field;
    exactly one transition wins, and the loser receives
    ERR_REVIEW_NOT_IN_REVIEW.'
    """

    def test_approve_vs_reject_exactly_one_wins(self, api):
        s = setup_otc_order_in_review(api, paid=True)
        rr = s["rr_pharmacist"]
        headers = make_pharmacist_re_reviewer_headers(rr["id"])

        results = run_race(
            lambda: api.approve_pharmacist_review(
                s["platform"]["id"], s["order"]["id"], s["review"]["id"],
                approve_review_payload(), headers,
            ),
            lambda: api.reject_pharmacist_review(
                s["platform"]["id"], s["order"]["id"], s["review"]["id"],
                reject_review_payload(decision_notes="dosage exceeds rationality threshold here"),
                headers,
            ),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser_body = outcome["failures"][0].json()
        # PRD §3.6 names ERR_REVIEW_NOT_IN_REVIEW for the loser.
        assert loser_body["data"]["error_id"] == ApiErrorId.ERR_REVIEW_NOT_IN_REVIEW.value, \
            f"Expected ERR_REVIEW_NOT_IN_REVIEW, got {loser_body['data']['error_id']}"
