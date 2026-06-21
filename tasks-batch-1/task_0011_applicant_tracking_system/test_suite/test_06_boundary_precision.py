"""Boundary precision: interview recommendation 4.50 boundary, offer accept at expires_at."""
import pytest
from test_helpers import (
    api_client, validate_error_is_one_of, get_success_data, TEST_USERS,
    set_clock, setup_offer_in_state, setup_interview_with_feedback,
    complete_interview, accept_offer, make_headers,
)


# =========================================================================
# Instance: interview_recommendation_threshold_exact_4_50_strong_hire
# =========================================================================

class TestInterviewRecommendationThresholdExact450StrongHire:
    """Two tests on the 4.50 inclusive lower bound for STRONG_HIRE."""

    def test_score_exactly_4_50_yields_strong_hire(self, api):
        """PRD §3.5: "The lower threshold of each band is inclusive; the
        upper threshold is exclusive, so an `aggregate_score` of exactly
        4.50 falls into `STRONG_HIRE` and an `aggregate_score` of exactly
        3.50 falls into `HIRE`."
        PRD §3.5: "`aggregate_score` of at least 4.50 yields `STRONG_HIRE`;
        at least 3.50 but strictly less than 4.50 yields `HIRE`..."

        Design: Difficulty/boundary_precision_check/interview_recommendation_threshold_exact_4_50_strong_hire
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = setup_interview_with_feedback(
            panel_user_ids=["panelist_a", "panelist_b"],
            scores=[4, 5],
            scheduled_at="2026-09-02T10:00:00Z",
        )
        intv = complete_interview(ctx["interview"]["id"])
        # (4 + 5) / 2 = 4.5 exact → STRONG_HIRE.
        assert intv["aggregate_score"] == pytest.approx(4.50, abs=1e-9), \
            f"Expected aggregate_score=4.50, got {intv['aggregate_score']}"
        assert intv["recommendation"] == "STRONG_HIRE"
        assert intv["status"] == "COMPLETED"

    def test_score_just_below_4_50_yields_hire(self, api):
        """PRD §3.5: "at least 3.50 but strictly less than 4.50 yields `HIRE`"
        PRD §2.6: "Interview aggregate scores are rounded half-up to two
        decimal places."

        Design: Difficulty/boundary_precision_check/interview_recommendation_threshold_exact_4_50_strong_hire
        """
        set_clock("2026-09-01T00:00:00Z")
        # Scores 4, 4, 5 → mean = 13/3 = 4.3333... → round HALF_UP 2dp → 4.33 → HIRE band.
        ctx = setup_interview_with_feedback(
            panel_user_ids=["pa1", "pa2", "pa3"],
            scores=[4, 4, 5],
            scheduled_at="2026-09-03T10:00:00Z",
        )
        intv = complete_interview(ctx["interview"]["id"])
        assert intv["aggregate_score"] == pytest.approx(4.33, abs=1e-9), \
            f"Expected aggregate_score=4.33 (round_half_up 13/3), got {intv['aggregate_score']}"
        assert intv["recommendation"] == "HIRE", \
            f"Expected HIRE (4.33 in [3.50, 4.50)), got {intv['recommendation']}"


# =========================================================================
# Instance: offer_accept_exact_expiry_boundary_revoked
# =========================================================================

class TestOfferAcceptExactExpiryBoundaryRevoked:
    """Two tests on the strict < expires_at boundary for accept."""

    def test_clock_at_expires_at_auto_revokes_extended_offer(self, api,
                                                              recruiter_headers):
        """PRD §3.6: "Accepting an `EXTENDED` offer is permitted only while
        the current instant is strictly less than `expires_at`; if the
        current instant has reached or passed `expires_at`, the accept is
        rejected with `ERR_OFFER_EXPIRED` and the offer is treated as
        `REVOKED`."
        PRD §3.6: "The system itself revokes any `EXTENDED` offer whose
        `expires_at` has been reached or passed; this auto-revoke applies
        the same cascades as a manual revoke."

        Design: Difficulty/boundary_precision_check/offer_accept_exact_expiry_boundary_revoked
        """
        set_clock("2026-10-01T00:00:00Z")
        ctx = setup_offer_in_state(
            "EXTENDED",
            req_overrides={"base_salary_max_cents": 15_000_000},
            base_salary_cents=12_000_000,
        )
        offer = ctx["offer"]
        # Offer extended at 2026-10-01 → expires_at = 2026-10-15.
        # Advance clock to exactly expires_at.
        set_clock("2026-10-15T00:00:00Z")
        offer_after = get_success_data(api_client.get_offer(offer["id"], recruiter_headers))
        assert offer_after["status"] == "REVOKED", \
            f"Expected auto-REVOKED at clock==expires_at, got {offer_after['status']}"

    def test_accept_at_expires_at_returns_expired_or_invalid_state(self, api,
                                                                    recruiter_headers):
        """PRD §3.6: "if the current instant has reached or passed
        `expires_at`, the accept is rejected with `ERR_OFFER_EXPIRED` and
        the offer is treated as `REVOKED`."

        After the clock auto-REVOKEs, a subsequent accept on the now-REVOKED
        offer could surface as either ERR_OFFER_EXPIRED (the rule's named
        error) or ERR_INVALID_STATE (the state-machine path); both are
        faithful PRD readings.

        Design: Difficulty/boundary_precision_check/offer_accept_exact_expiry_boundary_revoked
        """
        set_clock("2026-10-01T00:00:00Z")
        ctx = setup_offer_in_state(
            "EXTENDED",
            req_overrides={"base_salary_max_cents": 15_000_000},
            base_salary_cents=12_000_000,
        )
        cand = ctx["candidate"]
        offer = ctx["offer"]
        set_clock("2026-10-15T00:00:00Z")
        res = api_client.accept_offer(offer["id"],
                                      make_headers(cand["id"], "Candidate"))
        validate_error_is_one_of(res, ["ERR_OFFER_EXPIRED", "ERR_INVALID_STATE"])
