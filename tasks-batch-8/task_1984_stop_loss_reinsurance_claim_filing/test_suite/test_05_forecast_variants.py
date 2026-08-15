"""High-cost claimant forecast: the PURE_EXPERIENCE and CREDIBILITY_WEIGHTED
variants computed from the same plan experience."""
from test_helpers import (
    ADMIN,
    assert_forecast,
    create_plan,
    setup_paid_claim_scenario,
    validate_success,
)


def _plan_with_trailing_claim():
    """Plan + IN_FORCE contract + one member with a 300000_00 trailing PAID
    claim (paid 2026-03-02, inside the trailing 365 days before the default
    logical clock 2026-08-01)."""
    ctx = setup_paid_claim_scenario(
        plan_name="Beta Health", claim_cents=30_000_000,
        service_date="2026-03-01T00:00:00Z", paid_date="2026-03-02T00:00:00Z",
        file_the_notice=False)
    return ctx


class TestForecastVariants:
    def test_pure_experience_projection_uses_only_plan_claims(self, api):
        """PRD §3.9: "Under `PURE_EXPERIENCE`, only the plan's own trailing
        claims speak. The `projected_excess_cents` is the sum over
        projection-set members of the amount by which each member's trailing
        paid total exceeds the next-year specific deductible, counting only
        members whose total exceeds it at all. The `projected_member_count`
        is the number of members whose trailing paid total reaches at least
        the next-year specific deductible."

        Design: Difficulty/dual_variant_calc/forecast_pure_experience_vs_credibility_weighted
        """
        ctx = _plan_with_trailing_claim()
        resp = api.create_forecast(
            {"plan_id": ctx["plan"]["id"], "forecast_basis": "PURE_EXPERIENCE",
             "next_year_specific_deductible_cents": 10_000_000}, ADMIN)
        pure = validate_success(resp, 201)
        assert_forecast(pure)
        # 30_000_000 trailing paid minus the 10_000_000 next-year deductible.
        assert pure["projected_excess_cents"] == 20_000_000, (
            f"Pure-experience excess must be 20000000, got "
            f"{pure['projected_excess_cents']}")
        assert pure["projected_member_count"] == 1

    def test_credibility_weighted_blends_experience_with_manual_rate(self, api):
        """PRD §3.9: "Under `CREDIBILITY_WEIGHTED`, the plan's experience is
        blended with the manual rate through a credibility factor z: the
        member count divided by 500 — the membership size at which experience
        earns full credibility — capped at 1.0 and carried to two decimal
        places. The manual side prices excess at 1,200,000 cents per member
        — a manual rate of $12,000 per member — so the manual-rate excess is
        the member count multiplied by that per-member rate. The projected
        excess is then z multiplied by the pure-experience projection, plus
        one-minus-z multiplied by the manual-rate excess, rounded half-up to
        integer cents. The projected count blends the same way: z multiplied
        by the pure-experience count, plus one-minus-z multiplied by the
        member count multiplied by the manual hit rate of 0.04 — four members
        per hundred — with the result rounded half-up to a whole member."

        Design: Difficulty/dual_variant_calc/forecast_pure_experience_vs_credibility_weighted
        """
        ctx = _plan_with_trailing_claim()
        resp = api.create_forecast(
            {"plan_id": ctx["plan"]["id"], "forecast_basis": "PURE_EXPERIENCE",
             "next_year_specific_deductible_cents": 10_000_000}, ADMIN)
        pure = validate_success(resp, 201)
        resp = api.create_forecast(
            {"plan_id": ctx["plan"]["id"],
             "forecast_basis": "CREDIBILITY_WEIGHTED",
             "next_year_specific_deductible_cents": 10_000_000}, ADMIN)
        cred = validate_success(resp, 201)
        assert_forecast(cred)
        # Projection set has one member: z = 1/500 = 0.002, carried to two
        # decimal places -> 0.00. Excess = 0.00 * 20000000 + 1.00 * 1200000.
        assert cred["projected_excess_cents"] == 1_200_000, (
            f"Credibility-weighted excess must be 1200000, got "
            f"{cred['projected_excess_cents']}")
        # Count: round_half_up(0.00 * 1 + 1.00 * 1 * 0.04) = 0.
        assert cred["projected_member_count"] == 0, (
            f"Credibility-weighted count must round half-up to 0, got "
            f"{cred['projected_member_count']}")
        assert cred["projected_excess_cents"] != pure["projected_excess_cents"], (
            "The two variants must diverge on the same plan experience")


class TestForecastEndpoint:
    def test_forecast_without_claims_projects_zero(self, api):
        """PRD §3.9: "The projection set is the plan's members whose `status`
        is `ACTIVE` and who have at least one `PAID` claim whose `paid_date`
        falls within the trailing twelve months — the 365 days preceding the
        computation instant"
        PRD §4: "Operations that create a new resource return `201 Created`;
        this includes contract renewal, which creates the successor contract,
        and forecast computation, which creates the forecast row."

        Design: Corner/endpoints/forecast_endpoint_creates_entity
        """
        plan = create_plan(plan_name="P", sponsor_tax_id="99-5555555")
        resp = api.create_forecast(
            {"plan_id": plan["id"], "forecast_basis": "PURE_EXPERIENCE",
             "next_year_specific_deductible_cents": 10_000_000}, ADMIN)
        forecast = validate_success(resp, 201)
        assert_forecast(forecast)
        assert forecast["projected_excess_cents"] == 0
        assert forecast["projected_member_count"] == 0
