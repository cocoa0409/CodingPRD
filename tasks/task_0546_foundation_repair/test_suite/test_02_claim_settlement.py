"""Claim settlement calculation (PRD §3.8): FULL vs PRORATED coverage variants."""
from test_helpers import (
    setup_claim_under_review,
    setup_missed_visit_claim_under_review,
    api_client,
    get_success_data,
)
from test_helpers.fixtures import ADJUSTER


class TestProratedSettlement:
    def test_prorated_coverage_variant_after_one_missed_visit(self, api):
        """PRD §3.8: "The coverage percentage starts at 1.00 and is reduced by 0.10
        (`MISSED_PENALTY`) for each maintenance visit on the warranty that is in `MISSED`
        status, but never falls below a floor of 0.50 (`COVERAGE_FLOOR`)"
        PRD §3.8: "when there is at least one missed visit the reduced-and-floored
        percentage applies and the variant is `PRORATED`."

        Design: Difficulty/dual_variant_calc/claim_settlement_full_vs_prorated
        """
        ctx = setup_missed_visit_claim_under_review(reported_settlement_inches=1.5)
        claim = get_success_data(api_client.approve_claim(ctx["claim"]["id"], ADJUSTER))
        assert claim["coverage_variant"] == "PRORATED", claim

    def test_prorated_settlement_cents_after_one_missed_visit(self, api):
        """PRD §3.8: "The number of piers needed is the `reported_settlement_inches` divided
        by 0.5 inches per pier (`INCHES_PER_PIER`), rounded up to the next whole pier."
        PRD §3.8: "The `settlement_cents` is the full cost multiplied by that coverage
        percentage, rounded half-up to a whole cent"

        Design: Difficulty/dual_variant_calc/claim_settlement_full_vs_prorated
        """
        ctx = setup_missed_visit_claim_under_review(reported_settlement_inches=1.5)
        claim = get_success_data(api_client.approve_claim(ctx["claim"]["id"], ADJUSTER))
        # ceil(1.5/0.5)=3 piers * 150000 = 450000 full; * 0.90 (one missed) = 405000.
        assert claim["settlement_cents"] == 405000, claim


class TestFullSettlement:
    def test_full_variant_zero_missed_visits(self, api):
        """PRD §3.8: "when there are no missed visits the coverage percentage is 1.00, the
        settlement equals the full cost, and the variant is `FULL`"

        Design: Corner/calculations/claim_settlement_full_variant_zero_missed
        """
        ctx = setup_claim_under_review(reported_settlement_inches=1.5)
        claim = get_success_data(api_client.approve_claim(ctx["claim"]["id"], ADJUSTER))
        # No missed visits -> FULL: 3 piers * 150000 = 450000.
        assert claim["coverage_variant"] == "FULL", claim
        assert claim["settlement_cents"] == 450000, claim
