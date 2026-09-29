"""The two demand-score variants on one identical Program row."""

import pytest
from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures, make_partner_account_lead_headers


@pytest.fixture
def executed_partnership(api):
    """An EXECUTED partnership with no program yet, clock at the default instant."""
    fixtures.set_clock(api, fixtures.CLOCK_AUG_1)
    return fixtures.create_executed_partnership(api)


class TestDemandScoreVariantsDivergeOnOneProgram:
    def test_screening_variant_scores_the_partner_projection_at_face_value(
        self, api, executed_partnership
    ):
        """The screening variant trusts the partner's own projection.

        PRD: "The **screening** variant takes the effective projection to be
        `projected_annual_enrollments` itself, accepting the partner's unverified number at
        face value, and writes its result to `demand_score_screening`."
        PRD: "Those four component values are added to a raw score, and the raw score is
        multiplied by the modality factor — 1.00 for `ASYNCHRONOUS`, 0.92 for `SYNCHRONOUS`, 0.96
        for `HYBRID` — exactly once, on the summed raw score and never per component."

        Design: Difficulty/dual_variant_calc/demand_score_screening_vs_confirmed_diverge_on_one_program
        """
        ps_id = executed_partnership["id"]
        response = api.create_program(
            factories.program_payload(ps_id),
            headers=make_partner_account_lead_headers(ps_id),
        )
        program = validate_success(response, 201)

        assert program["demand_score_screening"] == pytest.approx(74.50, abs=0.01)
        assert program["status"] == "DRAFT"

    def test_confirmed_variant_caps_the_projection_at_the_prior_year_funnel(
        self, api, executed_partnership
    ):
        """The confirmed variant re-scores the same row against last year's inquiry funnel.

        PRD: "The **confirmed** variant takes the effective projection to be the smaller of
        `projected_annual_enrollments` and the observed funnel converted at a yield of one inquiry
        in ten — that is, `prior_year_inquiry_volume` multiplied by 0.10 and rounded half up to a
        whole number — and writes its result to `demand_score_confirmed`."
        PRD: "Both scores are computed at program creation."
        PRD: "When `total_enrollment_count` is zero the value is null — never 0 — because dividing
        spend by no enrollments has no meaning, and the distinction between "no students yet" and
        "free students" must survive into the response."

        Design: Difficulty/dual_variant_calc/demand_score_screening_vs_confirmed_diverge_on_one_program
        """
        ps_id = executed_partnership["id"]
        response = api.create_program(
            factories.program_payload(ps_id),
            headers=make_partner_account_lead_headers(ps_id),
        )
        program = validate_success(response, 201)

        assert program["demand_score_confirmed"] == pytest.approx(62.00, abs=0.01)
        assert program["demand_score_confirmed"] != program["demand_score_screening"]
        assert program["blended_cac_cents"] is None

    def test_both_variants_survive_a_read_of_the_stored_program(self, api, executed_partnership):
        """Both variants are stored on the one row and readable at the same instant.

        PRD: "Because the confirmed projection can only be lower or equal, identical program
        data yields a confirmed score at or below the screening score, and strictly below it
        whenever last year's inquiry funnel cannot support this year's projection."

        Design: Difficulty/dual_variant_calc/demand_score_screening_vs_confirmed_diverge_on_one_program
        """
        ps_id = executed_partnership["id"]
        created = fixtures.create_program(api, ps_id)

        stored = validate_success(api.get_program(created["id"], headers=make_partner_account_lead_headers(ps_id)))
        assert stored["demand_score_screening"] == pytest.approx(74.50, abs=0.01)
        assert stored["demand_score_confirmed"] == pytest.approx(62.00, abs=0.01)
        assert stored["demand_score_confirmed"] < stored["demand_score_screening"]
