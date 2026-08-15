"""Quality reviews: segregation of duties, begin/close guards, pinned scoring."""
import pytest

from test_helpers import (
    ApiErrorId,
    begin_review,
    close_review,
    create_packet,
    create_physician,
    drive_to_awaiting,
    find_review_for_case,
    get_review,
    list_reviews,
    make_quality_reviewer_headers,
    refuse_case,
    setup_certified_case,
    upload_documents,
    validate_error,
    validate_success,
)


def _refusal_review(patient_ref="PT-QR-1", acuity="EMERGENT", unit="ICU",
                    required_documents=None, upload=(),
                    refusal_category="NO_BED_AVAILABLE",
                    narrative="No ICU bed available tonight; house supervisor "
                              "escalation documented here."):
    """EMTALA_APPLIES case refused once; the auto-opened REFUSAL_RISK review and
    an independent reviewing physician."""
    ws = setup_certified_case(acuity=acuity, unit=unit, rcv_beds=(),
                              patient_ref=patient_ref)
    if required_documents is not None:
        pkt = create_packet(ws["case"]["id"], ws["phys_s"]["id"],
                            required_documents)
        if upload:
            pkt = upload_documents(pkt["id"], ws["phys_s"]["id"],
                                   list(upload), pkt["version"])
        ws["packet"] = pkt
    drive_to_awaiting(ws)
    refuse_case(ws["case"]["id"], ws["phys_r"]["id"], refusal_category,
                narrative)
    phys_q = create_physician("Dr Quality", ws["fac_s"]["id"], "GENERAL")
    review = find_review_for_case(ws["case"]["id"])
    assert review is not None, "refusal of an EMTALA_APPLIES case must open a review"
    return ws, phys_q, review


class TestBeginReview:
    def test_review_begin_twice_rejected(self, api):
        """PRD: "Beginning a review requires it `OPEN` and assigns the calling
        `QualityReviewer` by stamping `reviewer_physician_id` from `X-User-ID` —
        but a caller who is the case's sending or receiving physician is
        rejected with `ERR_REVIEWER_CONFLICT_OF_INTEREST`."

        Design: Corner/state_machines/review_begin_twice_rejected
        """
        ws, phys_q, review = _refusal_review()
        begin_review(review["id"], phys_q["id"])

        resp = api.begin_quality_review(
            review["id"], make_quality_reviewer_headers(phys_q["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        after = get_review(review["id"])
        assert after["status"] == "UNDER_REVIEW"
        assert after["reviewer_physician_id"] == phys_q["id"], (
            "a rejected second begin must not reassign the reviewer"
        )

    def test_reviewer_conflict_of_interest_rejected(self, api):
        """PRD: "When `X-User-Role` is `QualityReviewer`, `X-User-ID` is again
        the `id` of a `Physician`, but segregation of duties applies: the
        reviewer must not be the case's sending or receiving physician, and
        once assigned, only that reviewer may close the review."
        PRD: "Beginning a review requires it `OPEN` and assigns the calling
        `QualityReviewer` by stamping `reviewer_physician_id` from `X-User-ID` —
        but a caller who is the case's sending or receiving physician is
        rejected with `ERR_REVIEWER_CONFLICT_OF_INTEREST`."

        Design: Corner/validations/reviewer_conflict_of_interest_rejected
        """
        ws, phys_q, review = _refusal_review()

        # The case's receiving physician may not review their own refusal.
        resp = api.begin_quality_review(
            review["id"], make_quality_reviewer_headers(ws["phys_r"]["id"]))
        validate_error(resp, ApiErrorId.ERR_REVIEWER_CONFLICT_OF_INTEREST, 403)

        begun = begin_review(review["id"], phys_q["id"])
        assert begun["status"] == "UNDER_REVIEW"
        assert begun["reviewer_physician_id"] == phys_q["id"]


class TestCloseReview:
    def test_review_close_findings_too_short_rejected(self, api):
        """PRD: "Closing requires the review `UNDER_REVIEW`, the caller to be
        the assigned reviewer (`ERR_NOT_REVIEWER`), `findings` of at least 30
        characters (`ERR_FINDINGS_TOO_SHORT`), and an `outcome` of
        `CONCURRENCE`, `MINOR_VARIANCE`, `MAJOR_VARIANCE`, or
        `SENTINEL_EVENT`."

        Design: Corner/validations/review_close_findings_too_short_rejected
        """
        ws, phys_q, review = _refusal_review(
            acuity="URGENT", unit="TELEMETRY", patient_ref="PT-FND-1",
            refusal_category="CAPACITY_EXCEEDED",
            narrative="Capacity exceeded across all monitored units; refusal "
                      "documented per policy.")
        begin_review(review["id"], phys_q["id"])

        resp = api.close_quality_review(
            review["id"], {"outcome": "CONCURRENCE", "findings": "looks fine"},
            make_quality_reviewer_headers(phys_q["id"]))
        validate_error(resp, ApiErrorId.ERR_FINDINGS_TOO_SHORT, 400)

        after = get_review(review["id"])
        assert after["status"] == "UNDER_REVIEW"
        assert after["composite_score"] is None, "no scores before a valid close"

    def test_review_close_by_non_reviewer_rejected(self, api):
        """PRD: "When `X-User-Role` is `QualityReviewer`, `X-User-ID` is again
        the `id` of a `Physician`, but segregation of duties applies: the
        reviewer must not be the case's sending or receiving physician, and
        once assigned, only that reviewer may close the review."
        PRD: "Closing requires the review `UNDER_REVIEW`, the caller to be the
        assigned reviewer (`ERR_NOT_REVIEWER`), `findings` of at least 30
        characters (`ERR_FINDINGS_TOO_SHORT`), and an `outcome` of
        `CONCURRENCE`, `MINOR_VARIANCE`, `MAJOR_VARIANCE`, or
        `SENTINEL_EVENT`."

        Design: Corner/validations/review_close_by_non_reviewer_rejected
        """
        ws, phys_q1, review = _refusal_review(patient_ref="PT-NR-1")
        phys_q2 = create_physician("Dr Quality Two", ws["fac_r"]["id"], "GENERAL")
        begin_review(review["id"], phys_q1["id"])

        resp = api.close_quality_review(
            review["id"],
            {"outcome": "CONCURRENCE",
             "findings": "Attempted close by a reviewer who is not the assignee."},
            make_quality_reviewer_headers(phys_q2["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_REVIEWER, 403)

        after = get_review(review["id"])
        assert after["status"] == "UNDER_REVIEW"
        assert after["reviewer_physician_id"] == phys_q1["id"]


class TestCompositeScoring:
    def _closed_review(self):
        """REFUSAL_RISK review closed on a case with 1 of 3 packet documents,
        one refusal, no notifications, no holds, and no arrival."""
        ws, phys_q, review = _refusal_review(
            acuity="URGENT", unit="TELEMETRY", patient_ref="PT-QR-1",
            required_documents=["H_AND_P", "LABS", "MED_RECONCILIATION"],
            upload=["H_AND_P"],
            narrative="No monitored telemetry bed available for the next six "
                      "hours; documented per policy.")
        begin_review(review["id"], phys_q["id"])
        closed = close_review(
            review["id"], phys_q["id"], "MINOR_VARIANCE",
            "Refusal documentation adequate; capacity escalation pathway was "
            "followed correctly.")
        return review, closed

    def test_close_computes_pinned_composite_score(self, api):
        """PRD: "Each of the three dimensions is first rounded half-up to zero
        decimal places and stored in that rounded integer form; only then is
        `composite_score` computed as the weighted sum of the stored integers —
        40 percent timeliness, 35 percent documentation, 25 percent protocol —
        rounded half-up to two decimal places."
        PRD: "Weighting the unrounded dimensions and rounding once is a
        different calculation and is not the specified behavior."

        Design: Difficulty/combinatorial_formula/quality_composite_dimension_rounding_order_pinned
        """
        review, closed = self._closed_review()
        assert closed["id"] == review["id"]
        assert closed["trigger"] == "REFUSAL_RISK"
        assert closed["status"] == "CLOSED"
        # 0.40*0 + 0.35*33 + 0.25*80 = 31.55; sum-then-round would give 31.67.
        assert closed["composite_score"] == pytest.approx(31.55, abs=0.001)

    def test_close_stores_integer_rounded_dimensions(self, api):
        """PRD: "`timeliness_score` starts at 100 and sheds a quarter point for
        every minute the case's `door_to_arrival_minutes` ran past a four-hour
        target, floored at 0 — and is 0 outright when the case never produced
        an outcome."
        PRD: "`documentation_score` is the percentage of the packet's
        `required_documents` present in `received_documents` — 100 times the
        size of the intersection divided by the size of `required_documents` —
        defined as 100 when no documents were required and 0 when no packet
        exists."
        PRD: "`protocol_score` starts at 100, deducts 20 per refusal on the
        case, 30 when any of the case's notifications is `is_late`, and 40 when
        any of the case's holds ended `EXPIRED`, floored at 0."
        PRD: "Each of the three dimensions is first rounded half-up to zero
        decimal places and stored in that rounded integer form; only then is
        `composite_score` computed as the weighted sum of the stored integers —
        40 percent timeliness, 35 percent documentation, 25 percent protocol —
        rounded half-up to two decimal places."

        Design: Difficulty/combinatorial_formula/quality_composite_dimension_rounding_order_pinned
        """
        _review, closed = self._closed_review()
        assert closed["timeliness_score"] == 0, "the case never produced an outcome"
        assert closed["documentation_score"] == 33, (
            "100*1/3 = 33.33... stored rounded half-up to 0dp"
        )
        assert closed["protocol_score"] == 80, "100 - 20*1 refusal, no other deductions"
