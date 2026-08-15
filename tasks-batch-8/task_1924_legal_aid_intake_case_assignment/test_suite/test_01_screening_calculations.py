"""Screening calculations: dual income-screen variants, priority score inputs,
caps and rounding, household-size precision, and the benefits auto-pass."""
import pytest

from test_helpers import (
    validate_success,
    create_venue_rule,
    create_intake_specialist,
    create_client,
    create_application,
    make_intake_specialist_headers,
)


def _setup_worker_and_app(case_type, client_overrides, base_weight=50, venue="HOUSING_COURT",
                          extended_eligible=True):
    create_venue_rule(county="CountyA", case_type=case_type, venue=venue,
                      priority_base_weight=base_weight,
                      extended_eligible=extended_eligible)
    intake = create_intake_specialist(practice_areas=[case_type])
    client = create_client(intake["id"], **client_overrides)
    app = create_application(intake["id"], client["id"], case_type=case_type)
    return intake, client, app


class TestIncomeScreenVariants:
    def test_income_screen_variants_diverge_on_same_client(self, api):
        """PRD §3.2: "The **standard screen** divides `annual_gross_income_cents`
        by the guideline to produce `gross_poverty_percentage`; the household
        passes when `receives_means_tested_benefits` is true or the resulting
        percentage is at most 125.00 — a value of exactly 125.00 passes — and
        the outcome is stored as `eligibility_determination`, either `ELIGIBLE`
        or `INELIGIBLE`. The **grant screen** substitutes
        `annual_countable_income_cents` to produce `countable_poverty_percentage`;
        it has no benefits auto-pass and renders no verdict at screen time,
        deferring judgment to case opening, where the stored percentage is
        compared against the chosen program's `income_cap_percentage`. Both
        percentages are computed and stored on every screen, even though only
        the standard variant drives `eligibility_determination`."

        Design: Difficulty/dual_variant_calc/income_screen_variants_diverge_on_same_client
        """
        intake, client, app = _setup_worker_and_app(
            "EVICTION_DEFENSE",
            {"full_name": "Cli Variant", "household_size": 1,
             "annual_gross_income_cents": 2_000_000,
             "annual_countable_income_cents": 1_500_000,
             "receives_means_tested_benefits": False},
        )
        resp = api.screen_application(app["id"], make_intake_specialist_headers(intake["id"]))
        data = validate_success(resp)
        # 2,000,000 / 1,506,000 * 100 = 132.8021... -> 132.80 (fails 125.00 cap)
        assert data["gross_poverty_percentage"] == pytest.approx(132.80, abs=0.001)
        # 1,500,000 / 1,506,000 * 100 = 99.6015... -> 99.60
        assert data["countable_poverty_percentage"] == pytest.approx(99.60, abs=0.001)
        assert data["eligibility_determination"] == "INELIGIBLE"

    def test_income_screen_both_variants_stored_on_eligible_client(self, api):
        """PRD §3.2: "Both percentages are computed and stored on every screen,
        even though only the standard variant drives `eligibility_determination`."

        Design: Difficulty/dual_variant_calc/income_screen_variants_diverge_on_same_client
        """
        intake, client, app = _setup_worker_and_app(
            "EVICTION_DEFENSE",
            {"full_name": "Cli Both", "household_size": 1,
             "annual_gross_income_cents": 1_000_000,
             "annual_countable_income_cents": 900_000,
             "receives_means_tested_benefits": False},
        )
        resp = api.screen_application(app["id"], make_intake_specialist_headers(intake["id"]))
        data = validate_success(resp)
        # 1,000,000 / 1,506,000 * 100 = 66.4010... -> 66.40
        assert data["gross_poverty_percentage"] == pytest.approx(66.40, abs=0.001)
        # 900,000 / 1,506,000 * 100 = 59.7609... -> 59.76
        assert data["countable_poverty_percentage"] == pytest.approx(59.76, abs=0.001)
        assert data["eligibility_determination"] == "ELIGIBLE"


class TestPriorityScoreFormula:
    def test_priority_score_zero_factors_multiplier_floor(self, api):
        """PRD §3.2: "It starts from the matching venue rule's
        `priority_base_weight`, an integer from 1 to 100, and multiplies that
        base by a vulnerability multiplier: one plus 0.15 for each of the
        client's `vulnerability_factors`, capped at 1.75 — no factors means a
        multiplier of 1.00, and five or more factors reaches the 1.75 ceiling."

        Design: Difficulty/combinatorial_formula/priority_score_multi_input_nonlinear
        """
        intake, client, app = _setup_worker_and_app(
            "EVICTION_DEFENSE",
            {"full_name": "Cli Zero", "household_size": 1,
             "annual_gross_income_cents": 1_000_000,
             "annual_countable_income_cents": 900_000,
             "receives_means_tested_benefits": False},
            base_weight=50,
        )
        resp = api.screen_application(app["id"], make_intake_specialist_headers(intake["id"]))
        data = validate_success(resp)
        # 50 * 1.00 + 20 = 70.00 exactly
        assert data["priority_score"] == pytest.approx(70.00, abs=0.001)

    def test_priority_score_multi_input_nonlinear(self, api):
        """PRD §3.2: "It starts from the matching venue rule's
        `priority_base_weight`, an integer from 1 to 100, and multiplies that
        base by a vulnerability multiplier: one plus 0.15 for each of the
        client's `vulnerability_factors`, capped at 1.75 — no factors means a
        multiplier of 1.00, and five or more factors reaches the 1.75 ceiling.
        An urgency increment is then added: 20 when the `case_type` is
        `EVICTION_DEFENSE` or `FAMILY_DV`, 10 when it is `BENEFITS_APPEAL`, and
        0 for the other case types. The sum is rounded half-up to two decimal
        places, and anything above 100.00 is capped at 100.00."

        Design: Difficulty/combinatorial_formula/priority_score_multi_input_nonlinear
        """
        intake, client, app = _setup_worker_and_app(
            "EVICTION_DEFENSE",
            {"full_name": "Cli Prio", "household_size": 1,
             "annual_gross_income_cents": 1_000_000,
             "annual_countable_income_cents": 900_000,
             "receives_means_tested_benefits": False,
             "vulnerability_factors": ["ELDERLY", "DISABLED"]},
            base_weight=50,
        )
        resp = api.screen_application(app["id"], make_intake_specialist_headers(intake["id"]))
        data = validate_success(resp)
        # 50 * 1.30 + 20 = 85.00 exactly
        assert data["priority_score"] == pytest.approx(85.00, abs=0.001)

    def test_priority_score_capped_at_100(self, api):
        """PRD §3.2: "The sum is rounded half-up to two decimal places, and
        anything above 100.00 is capped at 100.00."

        Design: Corner/calculations/priority_score_capped_at_100
        """
        intake, client, app = _setup_worker_and_app(
            "FAMILY_DV",
            {"full_name": "Cli Max", "household_size": 1,
             "annual_gross_income_cents": 1_000_000,
             "annual_countable_income_cents": 900_000,
             "receives_means_tested_benefits": False,
             "vulnerability_factors": ["ELDERLY", "DISABLED", "DV_SURVIVOR",
                                       "HOMELESS", "VETERAN"]},
            base_weight=80, venue="FAMILY_COURT",
        )
        resp = api.screen_application(app["id"], make_intake_specialist_headers(intake["id"]))
        data = validate_success(resp)
        # min(100.00, 80 * 1.75 + 20) = min(100.00, 160.00) = 100.00
        assert data["priority_score"] == pytest.approx(100.00, abs=0.001)

    def test_priority_urgency_tiers_applied(self, api):
        """PRD §3.2: "An urgency increment is then added: 20 when the
        `case_type` is `EVICTION_DEFENSE` or `FAMILY_DV`, 10 when it is
        `BENEFITS_APPEAL`, and 0 for the other case types."

        Design: Corner/calculations/priority_urgency_tiers_applied
        """
        create_venue_rule(county="CountyA", case_type="BENEFITS_APPEAL",
                          venue="ADMIN_TRIBUNAL", priority_base_weight=40,
                          extended_eligible=False)
        create_venue_rule(county="CountyA", case_type="CONSUMER_DEBT",
                          venue="MUNICIPAL_COURT", priority_base_weight=30,
                          extended_eligible=False)
        intake = create_intake_specialist(practice_areas=["BENEFITS_APPEAL"])
        client = create_client(intake["id"], full_name="Cli Tier")
        headers = make_intake_specialist_headers(intake["id"])
        app_b = create_application(intake["id"], client["id"], case_type="BENEFITS_APPEAL",
                                   opposing_party_name="Agency")
        app_c = create_application(intake["id"], client["id"], case_type="CONSUMER_DEBT",
                                   opposing_party_name="Collector")
        data_b = validate_success(api.screen_application(app_b["id"], headers))
        data_c = validate_success(api.screen_application(app_c["id"], headers))
        # 40 * 1.00 + 10 = 50.00 ; 30 * 1.00 + 0 = 30.00
        assert data_b["priority_score"] == pytest.approx(50.00, abs=0.001)
        assert data_c["priority_score"] == pytest.approx(30.00, abs=0.001)


class TestPovertyPrecisionAndBenefits:
    def test_poverty_percentage_household_three_precision(self, api):
        """PRD §3.2: "for a household, the guideline is 1,506,000 cents
        ($15,060.00) for the first household member plus 538,000 cents
        ($5,380.00) for each additional member, and each percentage is the
        relevant income in cents divided by the household's guideline in cents,
        multiplied by one hundred, and rounded half-up to two decimal places."

        Design: Corner/calculations/poverty_percentage_household_three_precision
        """
        intake, client, app = _setup_worker_and_app(
            "BENEFITS_APPEAL",
            {"full_name": "Cli H3", "household_size": 3,
             "annual_gross_income_cents": 3_000_000,
             "annual_countable_income_cents": 2_900_000,
             "receives_means_tested_benefits": False},
            base_weight=40, venue="ADMIN_TRIBUNAL", extended_eligible=False,
        )
        resp = api.screen_application(app["id"], make_intake_specialist_headers(intake["id"]))
        data = validate_success(resp)
        # guideline = 1,506,000 + 2 * 538,000 = 2,582,000; 3,000,000/2,582,000*100 = 116.189...
        assert data["gross_poverty_percentage"] == pytest.approx(116.19, abs=0.001)
        assert data["eligibility_determination"] == "ELIGIBLE"

    def test_income_percentage_exactly_at_125_cap(self, api):
        """PRD §3.2: "the household passes when `receives_means_tested_benefits`
        is true or the resulting percentage is at most 125.00 — a value of
        exactly 125.00 passes — and the outcome is stored as
        `eligibility_determination`, either `ELIGIBLE` or `INELIGIBLE`."

        Design: Difficulty/boundary_precision_check/income_percentage_exactly_at_125_cap
        """
        create_venue_rule(county="CountyA", case_type="EVICTION_DEFENSE",
                          venue="HOUSING_COURT", priority_base_weight=50,
                          extended_eligible=True)
        intake = create_intake_specialist(practice_areas=["EVICTION_DEFENSE"])
        headers = make_intake_specialist_headers(intake["id"])
        # 1,882,500 / 1,506,000 * 100 = 125.00 exactly
        client_a = create_client(intake["id"], full_name="Cli Edge",
                                 annual_gross_income_cents=1_882_500,
                                 annual_countable_income_cents=1_882_500)
        client_b = create_client(intake["id"], full_name="Cli Over",
                                 annual_gross_income_cents=1_882_651,
                                 annual_countable_income_cents=1_882_651)
        app_a = create_application(intake["id"], client_a["id"],
                                   case_type="EVICTION_DEFENSE", opposing_party_name="L1")
        app_b = create_application(intake["id"], client_b["id"],
                                   case_type="EVICTION_DEFENSE", opposing_party_name="L2")
        data_a = validate_success(api.screen_application(app_a["id"], headers))
        data_b = validate_success(api.screen_application(app_b["id"], headers))
        assert data_a["gross_poverty_percentage"] == pytest.approx(125.00, abs=0.001)
        assert data_a["eligibility_determination"] == "ELIGIBLE"
        # 1,882,651 / 1,506,000 * 100 = 125.0100... -> 125.01
        assert data_b["gross_poverty_percentage"] == pytest.approx(125.01, abs=0.001)
        assert data_b["eligibility_determination"] == "INELIGIBLE"

    def test_income_percentage_one_cent_over_cap_flips_verdict(self, api):
        """PRD §3.2: "the household passes when `receives_means_tested_benefits`
        is true or the resulting percentage is at most 125.00 — a value of
        exactly 125.00 passes — and the outcome is stored as
        `eligibility_determination`, either `ELIGIBLE` or `INELIGIBLE`."

        Design: Difficulty/boundary_precision_check/income_percentage_exactly_at_125_cap
        """
        create_venue_rule(county="CountyA", case_type="FAMILY_DV",
                          venue="FAMILY_COURT", priority_base_weight=60,
                          extended_eligible=True)
        intake = create_intake_specialist(practice_areas=["FAMILY_DV"])
        headers = make_intake_specialist_headers(intake["id"])
        # household 2: guideline = 2,044,000; 125.00% = 2,555,000 exactly
        client_at = create_client(intake["id"], full_name="Cli AtCap", household_size=2,
                                  annual_gross_income_cents=2_555_000,
                                  annual_countable_income_cents=2_555_000)
        app_at = create_application(intake["id"], client_at["id"],
                                    case_type="FAMILY_DV", opposing_party_name="X")
        data_at = validate_success(api.screen_application(app_at["id"], headers))
        assert data_at["gross_poverty_percentage"] == pytest.approx(125.00, abs=0.001)
        assert data_at["eligibility_determination"] == "ELIGIBLE"

    def test_benefits_autopass_threshold_override(self, api):
        """PRD §3.2: "the household passes when `receives_means_tested_benefits`
        is true or the resulting percentage is at most 125.00 — a value of
        exactly 125.00 passes — and the outcome is stored as
        `eligibility_determination`, either `ELIGIBLE` or `INELIGIBLE`."

        Design: Corner/cross_cutting_complexity_layers/benefits_autopass_threshold_override
        """
        create_venue_rule(county="CountyA", case_type="EVICTION_DEFENSE",
                          venue="HOUSING_COURT", priority_base_weight=50,
                          extended_eligible=True)
        intake = create_intake_specialist(practice_areas=["EVICTION_DEFENSE"])
        headers = make_intake_specialist_headers(intake["id"])
        client_a = create_client(intake["id"], full_name="Cli NoBen",
                                 annual_gross_income_cents=5_000_000,
                                 annual_countable_income_cents=5_000_000,
                                 receives_means_tested_benefits=False)
        client_b = create_client(intake["id"], full_name="Cli Ben",
                                 annual_gross_income_cents=5_000_000,
                                 annual_countable_income_cents=5_000_000,
                                 receives_means_tested_benefits=True)
        app_a = create_application(intake["id"], client_a["id"],
                                   case_type="EVICTION_DEFENSE", opposing_party_name="L1")
        app_b = create_application(intake["id"], client_b["id"],
                                   case_type="EVICTION_DEFENSE", opposing_party_name="L2")
        data_a = validate_success(api.screen_application(app_a["id"], headers))
        data_b = validate_success(api.screen_application(app_b["id"], headers))
        # 5,000,000 / 1,506,000 * 100 = 332.0053... -> 332.01
        assert data_a["gross_poverty_percentage"] == pytest.approx(332.01, abs=0.001)
        assert data_b["gross_poverty_percentage"] == pytest.approx(332.01, abs=0.001)
        assert data_a["eligibility_determination"] == "INELIGIBLE"
        assert data_b["eligibility_determination"] == "ELIGIBLE"
