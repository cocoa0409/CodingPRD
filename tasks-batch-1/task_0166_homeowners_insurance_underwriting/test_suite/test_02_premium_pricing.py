"""Combinatorial premium pricing: tiered/zoned annual_premium and the pinned
per-component-then-sum rounding order. Queue A — rule combinatorial_formula.
"""
import pytest

from test_helpers import (
    validate_success,
    TEST_USERS,
    make_inspector_headers,
    factories as f,
    fixtures as fx,
)

AGENT = TEST_USERS["agent_headers"]
UW = TEST_USERS["underwriter_headers"]


class TestTieredZonedAnnualPremium:
    def _build_high_zone_submitted(self, api):
        """coverage 450000, FINAL wildfire 76, flood AE, coast 3mi (TIER_3), ded 5%."""
        inspector = fx.create_inspector(buffer_minutes=30, full_name="Hi Zone Insp",
                                         license_state="FL")
        prop = fx.create_property(
            street_address="9 Gulf Blvd", state_code="FL", year_built=2015,
            square_footage=2400, construction_type="MASONRY", roof_age_years=2, stories=2,
        )
        fx.commit_estimate(prop["id"], "COMPONENT")
        ra = fx.create_risk_assessment(
            prop["id"], wildfire_fuel_density=90, slope_grade_pct=80,
            defensible_space_ft=50, flood_zone="AE", distance_to_coast_mi=3,
        )
        insp = fx.schedule_inspection(prop["id"], inspector["id"], 1750100000, 1750103600)
        fx.complete_inspection(insp["id"], inspector["id"])
        app = fx.create_application(prop["id"], 450000, wind_hail_deductible_pct=5)
        app = fx.submit_application(app["id"])
        return ra, app

    def test_tier3_high_wildfire_base_premium(self, api):
        """PRD §3.4: "The base figure is the requested Coverage A multiplied by that
        tier rate. Three zone multipliers are then applied multiplicatively. The
        wildfire multiplier is one plus five thousandths for each point by which the
        wildfire score exceeds 40, applying no surcharge at or below 40 ... The flood
        multiplier depends on the flood zone: 1.0 for `X`, 1.2 for `A`, 1.35 for `AE`,
        and 1.6 for `VE`. The wind/hail multiplier depends on the tier: 1.0 for
        `TIER_1`, 1.18 for `TIER_2`, and 1.4 for `TIER_3`. Multiplying the base figure
        by all three yields the zoned figure. Finally a deductible credit is applied ...
        That result, rounded half up to two decimal places, is the `base_premium`."

        Design: Difficulty/combinatorial_formula/annual_premium_tiered_zone_nonlinear
        """
        ra, app = self._build_high_zone_submitted(api)
        assert ra["wind_hail_tier"] == "TIER_3"
        quote = fx.get_quote_for_application(app["id"])
        assert quote["base_premium"] == 2737.79, (
            f"Expected base_premium 2737.79, got {quote['base_premium']}"
        )

    def test_annual_premium_equals_base_with_no_endorsements(self, api):
        """PRD §3.4: "The quote's `annual_premium` is the sum of the rounded
        `base_premium` and the rounded `endorsement_premium`, assembled in the
        per-component-then-sum order described in Section 2.7."

        Design: Difficulty/combinatorial_formula/annual_premium_tiered_zone_nonlinear
        """
        ra, app = self._build_high_zone_submitted(api)
        quote = fx.get_quote_for_application(app["id"])
        assert quote["annual_premium"] == 2737.79, (
            f"Expected annual_premium 2737.79, got {quote['annual_premium']}"
        )
        app_after = validate_success(api.get_application(app["id"], AGENT))
        assert app_after["quoted_premium"] == 2737.79


class TestPerComponentThenSumRounding:
    def _build_two_endorsement_submitted(self, api):
        prop = fx.create_property(
            street_address="3 Birch St", state_code="CA", year_built=2008,
            square_footage=2000, construction_type="FRAME", roof_age_years=5, stories=1,
        )
        fx.commit_estimate(prop["id"], "COMPONENT")
        fx.create_risk_assessment(
            prop["id"], wildfire_fuel_density=60, slope_grade_pct=40,
            defensible_space_ft=100, flood_zone="X", distance_to_coast_mi=60,
        )
        app = fx.create_application(prop["id"], 300000, wind_hail_deductible_pct=2)
        e1 = fx.create_endorsement(app["id"], "PERIL_ADD", "WATER_BACKUP", 20000)
        e1 = fx.attach_endorsement(e1["id"])
        e2 = fx.create_endorsement(app["id"], "PERIL_ADD", "MOLD", 9000)
        e2 = fx.attach_endorsement(e2["id"])
        app = fx.submit_application(app["id"])
        return app, e1, e2

    def test_endorsement_deltas_each_rounded(self, api):
        """PRD §3.5: "For a peril-add, the delta is positive: the coverage limit
        multiplied by the per-peril rate — 0.004 for `WATER_BACKUP`, 0.003 for
        `SCREENED_ENCLOSURE`, 0.0025 for `ORDINANCE_LAW`, 0.006 for `EARTH_MOVEMENT`,
        and 0.005 for `MOLD` — rounded half up to two decimal places."

        Design: Difficulty/combinatorial_formula/premium_rounding_per_component_then_sum
        """
        app, e1, e2 = self._build_two_endorsement_submitted(api)
        assert e1["premium_delta"] == 80.00, f"WATER_BACKUP 20000*0.004=80.00, got {e1['premium_delta']}"
        assert e2["premium_delta"] == 45.00, f"MOLD 9000*0.005=45.00, got {e2['premium_delta']}"

    def test_annual_premium_per_component_then_sum(self, api):
        """PRD §2.7: "the base portion is rounded to two decimal places to produce
        `base_premium`, the endorsement portion is independently rounded to two decimal
        places to produce `endorsement_premium`, and only then are those two
        already-rounded amounts added together to yield `annual_premium`."

        Design: Difficulty/combinatorial_formula/premium_rounding_per_component_then_sum
        """
        app, e1, e2 = self._build_two_endorsement_submitted(api)
        quote = fx.get_quote_for_application(app["id"])
        assert quote["base_premium"] == 997.50, f"Expected base 997.50, got {quote['base_premium']}"
        assert quote["endorsement_premium"] == 125.00, (
            f"Expected endorsement_premium 125.00, got {quote['endorsement_premium']}"
        )
        assert quote["annual_premium"] == 1122.50, (
            f"Expected annual_premium 1122.50, got {quote['annual_premium']}"
        )
        app_after = validate_success(api.get_application(app["id"], AGENT))
        assert app_after["quoted_premium"] == 1122.50
