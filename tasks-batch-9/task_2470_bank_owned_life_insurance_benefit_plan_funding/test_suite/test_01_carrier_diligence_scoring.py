"""Carrier due diligence: the financial strength score and the information-request loop."""
import pytest
from test_helpers import validate_error, validate_success
from test_helpers.fixtures import (
    ANALYST,
    RISK,
    file_capital_position,
    onboard_carrier,
    open_diligence_review,
    submit_diligence_review,
)


PINNACLE = {
    "legal_name": "Pinnacle Life",
    "naic_code": "62011",
    "am_best_rating": "A_PLUS",
    "statutory_surplus_usd": 400_000_000.00,
    "domicile_state": "NY",
}

QUARRY = {
    "legal_name": "Quarry Mutual Life",
    "naic_code": "62012",
    "am_best_rating": "A_MINUS",
    "statutory_surplus_usd": 1_500_000_000.00,
    "domicile_state": "NJ",
}

CASCADE = {
    "legal_name": "Cascade Assurance",
    "naic_code": "62013",
    "am_best_rating": "A_PLUS",
    "statutory_surplus_usd": 400_000_000.00,
    "domicile_state": "WA",
}


class TestFinancialStrengthScoreAtTheApprovalBoundary:
    def test_score_of_exactly_sixty_five_is_approved_and_authorizes_the_carrier(self, api):
        """A weighted score landing exactly on the threshold is approved.

        An A_PLUS carrier with 400,000,000.00 of surplus and no exposure scores
        90 rating points, 0 surplus points and 100.0 concentration points,
        because "`surplus_points` rewards balance-sheet size in
        half-billion-dollar steps: divide the carrier's `statutory_surplus_usd`
        by 500,000,000, discard any fractional part of that quotient, multiply
        the resulting whole number of steps by 10, and cap the product at 100".
        "The three components are then weighted — half the weight on
        `rating_points`, three tenths on `surplus_points`, one fifth on
        `concentration_points` — and the weighted total is rounded half up to a
        whole number to give `financial_strength_score`." Approval then applies
        "the score threshold, requiring `financial_strength_score` to be at
        least 65", and on success "drives the carrier `PENDING_DILIGENCE →
        AUTHORIZED`, sets the carrier's `last_approved_review_year` to the
        file's `review_year`".

        Design: Difficulty/boundary_precision_check/financial_strength_score_exactly_at_min_approval_score
        """
        file_capital_position(api)
        carrier = onboard_carrier(api, **PINNACLE)
        review = open_diligence_review(api, carrier["id"], review_year=2026)

        submitted = submit_diligence_review(api, review["id"])
        assert submitted["rating_points"] == 90, "A_PLUS is a straight 90-point lookup"
        assert submitted["surplus_points"] == 0, (
            "400,000,000.00 of surplus is less than one half-billion-dollar step"
        )
        assert submitted["concentration_points"] == pytest.approx(100.0, abs=0.01), (
            "an unexposed carrier keeps the full concentration component"
        )
        assert submitted["financial_strength_score"] == 65, (
            "0.50*90 + 0.30*0 + 0.20*100.0 rounds half up to 65"
        )

        approved = validate_success(api.approve_diligence_review(review["id"], RISK))
        assert approved["status"] == "APPROVED"
        assert approved["decided_by_user_id"] == "risk-1"
        assert approved["financial_strength_score"] == 65

        carrier_after = validate_success(api.get_carrier(carrier["id"], RISK))
        assert carrier_after["status"] == "AUTHORIZED", (
            "approval at exactly the threshold authorizes the carrier"
        )
        assert carrier_after["last_approved_review_year"] == 2026

    def test_score_of_sixty_four_is_refused_and_leaves_the_carrier_pending(self, api):
        """One point below the threshold is refused and nothing advances.

        An A_MINUS carrier with 1,500,000,000.00 of surplus scores 70 rating
        points and 30 surplus points, so the weighted total is 64 — and
        approval is guarded by "the score threshold, requiring
        `financial_strength_score` to be at least 65, with a score of 64 or
        below refused as `ERR_FINANCIAL_STRENGTH_BELOW_MINIMUM` (HTTP 422)".
        A refused request changes nothing, so the file stays UNDER_REVIEW and
        the carrier stays where a newly onboarded carrier begins, which is
        "`PENDING_DILIGENCE` with `watch_list_flag` false".

        Design: Difficulty/boundary_precision_check/financial_strength_score_exactly_at_min_approval_score
        """
        file_capital_position(api)
        carrier = onboard_carrier(api, **QUARRY)
        review = open_diligence_review(api, carrier["id"], review_year=2026)

        submitted = submit_diligence_review(api, review["id"])
        assert submitted["rating_points"] == 70, "A_MINUS is a straight 70-point lookup"
        assert submitted["surplus_points"] == 30, (
            "1,500,000,000.00 of surplus is exactly three half-billion steps"
        )
        assert submitted["financial_strength_score"] == 64, (
            "0.50*70 + 0.30*30 + 0.20*100.0 rounds half up to 64"
        )

        validate_error(
            api.approve_diligence_review(review["id"], RISK),
            "ERR_FINANCIAL_STRENGTH_BELOW_MINIMUM",
            422,
        )

        review_after = validate_success(api.get_diligence_review(review["id"], RISK))
        assert review_after["status"] == "UNDER_REVIEW", (
            "a refused approval leaves the file awaiting decision"
        )
        assert review_after["decided_by_user_id"] is None

        carrier_after = validate_success(api.get_carrier(carrier["id"], RISK))
        assert carrier_after["status"] == "PENDING_DILIGENCE"
        assert carrier_after["last_approved_review_year"] is None


class TestInformationRequestCycleCap:
    def test_third_information_request_is_refused_once_the_count_reaches_two(self, api):
        """The submit and send-back cycle runs twice and then refuses.

        "A `RiskOfficer` who wants more from the analyst before deciding sends
        the file back, advancing `UNDER_REVIEW → INFO_REQUESTED` and
        incrementing `info_request_count` by 1. That operator-driven loop is
        capped at two rounds: if `info_request_count` has already reached 2,
        the request is refused with `ERR_INFO_REQUEST_LIMIT_REACHED`
        (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/diligence_info_request_cycle_capped_at_two_rounds
        """
        file_capital_position(api)
        carrier = onboard_carrier(api, **CASCADE)
        review = open_diligence_review(api, carrier["id"], review_year=2026)
        review_id = review["id"]

        first_submit = validate_success(api.submit_diligence_review(review_id, ANALYST))
        assert first_submit["status"] == "UNDER_REVIEW"
        assert first_submit["info_request_count"] == 0

        first_send_back = validate_success(api.request_diligence_info(review_id, RISK))
        assert first_send_back["status"] == "INFO_REQUESTED"
        assert first_send_back["info_request_count"] == 1

        second_submit = validate_success(api.submit_diligence_review(review_id, ANALYST))
        assert second_submit["status"] == "UNDER_REVIEW", (
            "the same submit action re-advances a file that has been sent back"
        )

        second_send_back = validate_success(api.request_diligence_info(review_id, RISK))
        assert second_send_back["status"] == "INFO_REQUESTED"
        assert second_send_back["info_request_count"] == 2

        third_submit = validate_success(api.submit_diligence_review(review_id, ANALYST))
        assert third_submit["status"] == "UNDER_REVIEW"

        validate_error(
            api.request_diligence_info(review_id, RISK),
            "ERR_INFO_REQUEST_LIMIT_REACHED",
            409,
        )

    def test_capped_review_keeps_its_count_score_and_carrier_posture(self, api):
        """After the cap the file is left awaiting a decision, not sent back again.

        "The cycle `UNDER_REVIEW → INFO_REQUESTED → UNDER_REVIEW` may therefore
        run at most twice before the officer must either approve or decline."
        The refused send-back changes nothing, and because "Nothing may be
        placed with a carrier in `PENDING_DILIGENCE`" the carrier is still
        awaiting its authorization.

        Design: Difficulty/non_linear_state_machine/diligence_info_request_cycle_capped_at_two_rounds
        """
        file_capital_position(api)
        carrier = onboard_carrier(api, **CASCADE)
        review = open_diligence_review(api, carrier["id"], review_year=2026)
        review_id = review["id"]

        validate_success(api.submit_diligence_review(review_id, ANALYST))
        validate_success(api.request_diligence_info(review_id, RISK))
        validate_success(api.submit_diligence_review(review_id, ANALYST))
        validate_success(api.request_diligence_info(review_id, RISK))
        validate_success(api.submit_diligence_review(review_id, ANALYST))
        validate_error(
            api.request_diligence_info(review_id, RISK),
            "ERR_INFO_REQUEST_LIMIT_REACHED",
            409,
        )

        review_after = validate_success(api.get_diligence_review(review_id, RISK))
        assert review_after["status"] == "UNDER_REVIEW", (
            "the refused send-back leaves the file awaiting a decision"
        )
        assert review_after["info_request_count"] == 2, (
            "the refused request does not increment the capped counter"
        )
        assert review_after["financial_strength_score"] == 65, (
            "every submit recomputes the score from the carrier as it stands"
        )
        assert review_after["submitted_by_user_id"] == "analyst-1"
        assert review_after["decided_by_user_id"] is None

        carrier_after = validate_success(api.get_carrier(carrier["id"], RISK))
        assert carrier_after["status"] == "PENDING_DILIGENCE"
