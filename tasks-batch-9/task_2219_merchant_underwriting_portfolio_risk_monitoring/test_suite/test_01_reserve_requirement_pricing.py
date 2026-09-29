"""Reserve requirement determination: the two competing methodologies and the clamp."""

from __future__ import annotations

from test_helpers import (
    add_beneficial_owner,
    advance_to_underwriting,
    api_client,
    create_assessment,
    create_category_rule,
    create_draft_application,
    read_application,
    record_verification,
    screen_owner,
    set_clock,
    submit_application,
)


def _application_in_underwriting(api, **overrides):
    """Walk a fresh application from DRAFT to UNDERWRITING and return (id, version)."""
    owner_pct = overrides.pop("owner_pct", 80.00)
    application = create_draft_application(api, **overrides)
    application_id = application["id"]
    owner = add_beneficial_owner(
        api, application_id, full_name="Rosa Lind", ownership_pct=owner_pct
    )
    submit_application(api, application_id)
    record_verification(api, application_id)
    screen_owner(api, owner["id"])
    advanced = advance_to_underwriting(api, application_id)
    assert advanced["state"] == "UNDERWRITING"
    return application_id, advanced["version"]


class TestCompetingReserveMethodologies:
    """One application, priced twice, under the two declared methods."""

    def test_lag_weighted_prices_delivery_lag_and_ignores_the_declared_ratio(self):
        """Under LAG_WEIGHTED the delivery lag drives the uplift and the declared ratio is dead.

        PRD 3.4: "Under `LAG_WEIGHTED` - the forward-looking view, which prices exposure to
        goods not yet shipped - `lag_uplift_bps` is 150 basis points for every started week of
        delivery lag: take `avg_delivery_lag_days` divided by 7, round that quotient **up** to
        the next whole number, and multiply by 150. `chargeback_uplift_bps` is 0, and
        `declared_chargeback_ratio_bps` is ignored entirely."

        Design: Difficulty/dual_variant_calc/credit_assessment_lag_vs_chargeback_method_diverge
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")
        application_id, version = _application_in_underwriting(
            api,
            legal_business_name="Cascade Optics LLC",
            mcc_code="5732",
            requested_monthly_volume_cents=30_000_000,
            average_ticket_cents=12_000,
            avg_delivery_lag_days=21,
            declared_chargeback_ratio_bps=20,
            prior_processing_history_months=24,
            credit_score=610,
        )

        assessment = create_assessment(api, application_id, version, "LAG_WEIGHTED")

        assert assessment["assessment_sequence"] == 1
        assert assessment["credit_band"] == "C"
        assert assessment["base_reserve_bps"] == 900
        assert assessment["thin_file_uplift_bps"] == 0
        assert assessment["mcc_uplift_bps"] == 0
        assert assessment["lag_uplift_bps"] == 450
        assert assessment["chargeback_uplift_bps"] == 0
        assert assessment["reserve_pct_bps"] == 1350
        assert assessment["exposure_estimate_cents"] == 21_000_000
        assert assessment["reserve_cap_cents"] == 24_300_000
        assert assessment["reserve_type"] == "CAPPED"

    def test_chargeback_weighted_prices_the_declared_ratio_and_ignores_the_lag(self):
        """The same stored inputs under CHARGEBACK_WEIGHTED yield a different price and type.

        PRD 3.4: "Under `CHARGEBACK_WEIGHTED` - the historical view, which prices realised
        dispute experience - `chargeback_uplift_bps` is `declared_chargeback_ratio_bps`
        multiplied by 3, truncated **down** to a whole number. `lag_uplift_bps` is 0, and
        `avg_delivery_lag_days` is ignored entirely."

        Design: Difficulty/dual_variant_calc/credit_assessment_lag_vs_chargeback_method_diverge
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")
        application_id, version = _application_in_underwriting(
            api,
            legal_business_name="Cascade Optics LLC",
            mcc_code="5732",
            requested_monthly_volume_cents=30_000_000,
            average_ticket_cents=12_000,
            avg_delivery_lag_days=21,
            declared_chargeback_ratio_bps=20,
            prior_processing_history_months=24,
            credit_score=610,
        )

        lag_assessment = create_assessment(api, application_id, version, "LAG_WEIGHTED")
        refreshed = read_application(api, application_id)
        cbw_assessment = create_assessment(
            api, application_id, refreshed["version"], "CHARGEBACK_WEIGHTED"
        )

        assert cbw_assessment["assessment_sequence"] == 2
        assert cbw_assessment["lag_uplift_bps"] == 0
        assert cbw_assessment["chargeback_uplift_bps"] == 60
        assert cbw_assessment["reserve_pct_bps"] == 960
        assert cbw_assessment["exposure_estimate_cents"] == 1_000_000
        assert cbw_assessment["reserve_cap_cents"] == 2_000_000
        assert cbw_assessment["reserve_type"] == "ROLLING"

        # The two methods disagree on all three priced quantities.
        assert cbw_assessment["reserve_pct_bps"] != lag_assessment["reserve_pct_bps"]
        assert cbw_assessment["exposure_estimate_cents"] != lag_assessment["exposure_estimate_cents"]
        assert cbw_assessment["reserve_cap_cents"] != lag_assessment["reserve_cap_cents"]
        assert cbw_assessment["reserve_type"] != lag_assessment["reserve_type"]

    def test_the_latest_assessment_repins_the_application_reserve_terms(self):
        """After the second run the application carries the second method's terms.

        PRD 3.4: "Creating the assessment re-pins four fields on the application, so the
        committee always reads the terms of the latest run: `current_assessment_method`,
        `current_reserve_pct_bps`, `current_reserve_cap_cents` and `current_reserve_type` all
        take their values from the assessment with the greatest `assessment_sequence`."

        Design: Difficulty/dual_variant_calc/credit_assessment_lag_vs_chargeback_method_diverge
        """
        api = api_client
        set_clock(api, "2026-08-01T00:00:00Z")
        application_id, version = _application_in_underwriting(
            api,
            legal_business_name="Cascade Optics LLC",
            mcc_code="5732",
            requested_monthly_volume_cents=30_000_000,
            average_ticket_cents=12_000,
            avg_delivery_lag_days=21,
            declared_chargeback_ratio_bps=20,
            prior_processing_history_months=24,
            credit_score=610,
        )

        create_assessment(api, application_id, version, "LAG_WEIGHTED")
        after_lag = read_application(api, application_id)
        assert after_lag["current_reserve_pct_bps"] == 1350
        assert after_lag["current_reserve_type"] == "CAPPED"
        assert after_lag["current_assessment_method"] == "LAG_WEIGHTED"

        create_assessment(api, application_id, after_lag["version"], "CHARGEBACK_WEIGHTED")
        after_cbw = read_application(api, application_id)
        assert after_cbw["current_reserve_pct_bps"] == 960
        assert after_cbw["current_reserve_cap_cents"] == 2_000_000
        assert after_cbw["current_reserve_type"] == "ROLLING"
        assert after_cbw["current_assessment_method"] == "CHARGEBACK_WEIGHTED"


class TestReservePercentageClamp:
    """Four additive uplifts over a band D base, clamped at the declared ceiling."""

    def _restricted_high_risk_application(self, api):
        set_clock(api, "2026-08-01T00:00:00Z")
        create_category_rule(
            api,
            "7995",
            category="Betting and lottery",
            disposition="RESTRICTED_REVIEW",
            reserve_uplift_bps=400,
        )
        return _application_in_underwriting(
            api,
            legal_business_name="Riverbend Gaming LLC",
            mcc_code="7995",
            requested_monthly_volume_cents=10_000_000,
            average_ticket_cents=4_000,
            avg_delivery_lag_days=45,
            declared_chargeback_ratio_bps=30,
            prior_processing_history_months=3,
            credit_score=580,
            owner_pct=100.00,
        )

    def test_the_component_uplifts_sum_past_the_ceiling_and_the_result_is_clamped(self):
        """1500 + 300 + 400 + 1050 is 3250, and `reserve_pct_bps` is published as 2500.

        PRD 3.4: "Add five components together: `base_reserve_bps`, `lag_uplift_bps`,
        `chargeback_uplift_bps`, `thin_file_uplift_bps` and `mcc_uplift_bps`. Take the greater
        of that sum and a floor of 100 basis points, then take the lesser of the result and a
        ceiling of 2500 basis points; the result is `reserve_pct_bps`."

        Design: Difficulty/combinatorial_formula/reserve_pct_upper_clamp_over_four_additive_uplifts
        """
        api = api_client
        application_id, version = self._restricted_high_risk_application(api)

        application = read_application(api, application_id)
        assert application["mcc_disposition"] == "RESTRICTED_REVIEW"

        assessment = create_assessment(api, application_id, version, "LAG_WEIGHTED")

        assert assessment["credit_band"] == "D"
        assert assessment["base_reserve_bps"] == 1500
        assert assessment["thin_file_uplift_bps"] == 300
        assert assessment["mcc_uplift_bps"] == 400
        assert assessment["lag_uplift_bps"] == 1050
        assert assessment["chargeback_uplift_bps"] == 0
        assert assessment["reserve_pct_bps"] == 2500

    def test_the_cap_takes_the_lesser_of_six_monthly_holds_and_twice_the_exposure(self):
        """Exposure 10000000 caps the six-month hold of 15000000 at that same 15000000.

        PRD 3.4: "First compute the monthly hold: `requested_monthly_volume_cents` multiplied
        by `reserve_pct_bps`, divided by 10000, rounded half up **once** to whole cents. Then
        multiply that rounded integer by 6 cap months. `reserve_cap_cents` is the lesser of that
        six-month figure and twice `exposure_estimate_cents`."

        Design: Difficulty/combinatorial_formula/reserve_pct_upper_clamp_over_four_additive_uplifts
        """
        api = api_client
        application_id, version = self._restricted_high_risk_application(api)

        assessment = create_assessment(api, application_id, version, "LAG_WEIGHTED")

        assert assessment["exposure_estimate_cents"] == 10_000_000
        assert assessment["reserve_cap_cents"] == 15_000_000
        assert assessment["reserve_type"] == "CAPPED"
