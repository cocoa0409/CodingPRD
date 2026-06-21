"""Matching-gift computations: nested-min per-gift cap, the inclusive min-gift
eligibility boundary.

Difficulty queue: combinatorial_formula (match nested min). Corner queue:
cross_cutting rate_threshold_triggers boundary.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, ApiErrorId,
    create_open_campaign, create_donor, create_employer,
    create_acknowledged_gift, open_match_claim, approve_match_claim,
)

CM = TEST_USERS["campaign_manager_headers"]
GA = TEST_USERS["gift_admin_headers"]
DR = TEST_USERS["donor_relations_headers"]


# ---------------------------------------------------------------------------
# Difficulty Rule 2 (mode a) — nested min over three employer inputs
# ---------------------------------------------------------------------------
class TestMatchNestedMin:
    def test_per_gift_cap_binds_over_ratio_product(self, api):
        """PRD §3.6: "The requested amount is computed by applying the employer's
        `match_ratio` to the gift's `amount_cents` and discarding any fractional cent
        (flooring to whole cents), then taking the smaller of that floored product and
        the employer's `max_match_cents`." PRD §3.6: "The remaining cap is the larger
        of zero and the employer's `annual_match_cap_cents` minus that consumed
        amount. The claim's final `matched_amount_cents` is the smaller of its
        `requested_amount_cents` and that remaining cap."

        ratio 0.5 * 100000 = 50000, capped to max_match 30000; annual cap 5000000 is
        not binding -> matched 30000.

        Design: Difficulty/combinatorial_formula/match_amount_nested_min_three_inputs
        """
        camp = create_open_campaign(goal_cents=1000000)
        emp = create_employer(match_ratio=0.5, min_gift_cents=2500,
                              max_match_cents=30000, annual_match_cap_cents=5000000)
        donor = create_donor(employer_id=emp["id"])
        _, g = create_acknowledged_gift(camp["id"], donor["id"], amount_cents=100000)
        claim = open_match_claim(g)
        assert claim["requested_amount_cents"] == 30000, \
            "min(floor(100000*0.5)=50000, max_match=30000) == 30000"
        approve_match_claim(claim["id"])
        paid = validate_success(api.pay_match_claim(claim["id"], GA))
        assert paid["matched_amount_cents"] == 30000, \
            "annual cap not binding -> matched equals the per-gift-capped request"

    def test_ratio_floor_applied_before_cap(self, api):
        """PRD §2.5: "When a ratio is applied to a gift amount, the product is taken
        first and then reduced to a whole number of cents by discarding any fractional
        cent (flooring toward zero) before any cap is applied."

        ratio 0.5 * 12345 = 6172.5 -> floor 6172; below max_match -> requested 6172.

        Design: Difficulty/combinatorial_formula/match_amount_nested_min_three_inputs
        """
        camp = create_open_campaign(goal_cents=1000000)
        emp = create_employer(match_ratio=0.5, min_gift_cents=2500,
                              max_match_cents=1000000, annual_match_cap_cents=5000000)
        donor = create_donor(employer_id=emp["id"])
        _, g = create_acknowledged_gift(camp["id"], donor["id"], amount_cents=12345)
        claim = open_match_claim(g)
        assert claim["requested_amount_cents"] == 6172, \
            "floor(12345*0.5) == 6172, applied before any cap"


# ---------------------------------------------------------------------------
# Corner — rate-threshold inclusive boundary at min_gift_cents
# ---------------------------------------------------------------------------
class TestMatchEligibilityBoundary:
    def test_gift_exactly_at_min_gift_is_eligible(self, api):
        """PRD §3.6: "if the donor lacks an employer, or if the gift's `amount_cents`
        is below that employer's `min_gift_cents`, the claim is rejected with
        `ERR_GIFT_INELIGIBLE_FOR_MATCH` (HTTP 422)."

        A gift exactly AT min_gift_cents is not below it, so the claim is created.

        Design: Corner/cross_cutting_complexity_layers/rate_threshold_match_min_gift_boundary
        """
        camp = create_open_campaign(goal_cents=1000000)
        emp = create_employer(match_ratio=1.0, min_gift_cents=2500,
                              max_match_cents=1000000, annual_match_cap_cents=5000000)
        donor = create_donor(employer_id=emp["id"])
        _, g = create_acknowledged_gift(camp["id"], donor["id"], amount_cents=2500)
        claim = validate_success(api.create_match_claim({"gift_id": g}, GA), expected_status=201)
        assert claim["requested_amount_cents"] == 2500, "floor(2500*1.0) == 2500"
