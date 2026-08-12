"""Credit-monitoring cost aggregation — pinned rounding order
(difficulty rule combinatorial_formula; corner endpoints.computed_read)."""
from test_helpers import (
    TEST_USERS,
    assert_cost_summary,
    create_incident_confirmed,
    create_issued_offer,
    get_success_data,
    validate_success,
)

IC = TEST_USERS["incident_commander_headers"]
PC = TEST_USERS["privacy_counsel_headers"]


class TestCostSummary:
    def test_per_offer_round_then_sum(self, api):
        """PRD §3.9: "For each offer on the incident in any status, the
        per-offer cost is computed first and rounded to integer cents before
        any summation. ... If the offer is still `ISSUED`, its cost is the
        base multiplied by one tenth (a 10 percent reservation fee), rounded
        half-up to integer cents. The total cost is the sum of these per-offer
        rounded integer-cent values across all offers on the incident; the
        sum itself is never rounded."

        With 3 ISSUED offers at term=12, unit=999: per-offer base=11988;
        reservation = round_half_up(11988 * 0.10) = round_half_up(1198.8) =
        1199. Pinned sum = 3 * 1199 = 3597 (sum-then-round would give
        round_half_up(3596.4) = 3596).

        Design: Difficulty/combinatorial_formula/credit_monitoring_cost_per_offer_then_sum_mode_b
        """
        ctx = create_incident_confirmed(subject_count=3)
        inc = ctx["incident"]
        subjects = ctx["subjects"]
        for s in subjects:
            create_issued_offer(inc, s, term_months=12, unit_cost_cents=999)
        resp = api.get_cost_summary(inc["id"], IC)
        data = validate_success(resp)
        assert_cost_summary(data)
        assert data["credit_monitoring_cost_cents"] == 3597
        assert data["offer_count"] == 3

    def test_zero_offers_returns_zero_aggregate(self, api):
        """PRD §3.9: "The computed read returns both the total in
        `credit_monitoring_cost_cents` and the number of offers considered in
        `offer_count`." With zero offers the sum over an empty set is 0 and
        offer_count is 0.

        Design: Corner/endpoints/cost_summary_computed_read_returns_aggregates
        """
        from test_helpers import create_incident
        inc = create_incident()
        resp = api.get_cost_summary(inc["id"], IC)
        data = validate_success(resp)
        assert data["credit_monitoring_cost_cents"] == 0
        assert data["offer_count"] == 0
