"""Yield records: APH plug-year handling, provisional-vs-certified divergence,
and the one-decimal rounding clause (PRD §3.5)."""
import pytest

from test_helpers import (
    SAFE_CLOCK,
    assert_yield_record,
    create_farm_with_member,
    create_yield_record_payload,
    create_yield_record_with_observations,
    make_producer_headers,
    set_clock,
    update_and_certify_yield_record,
    validate_success,
)


@pytest.fixture
def specialist(county_specialist_headers):
    return county_specialist_headers


class TestPlugYearDivergence:
    def test_provisional_aph_uses_plug_yield_for_missing_year(self, api, specialist):
        """PRD §3.5: "Each observation contributes an effective yield: when the
        observation carries an actual value and has not been disaster-substituted,
        the effective yield is that actual value; when the observation has been
        disaster-substituted, the effective yield is sixty-five percent of the
        commodity's T-yield; when the observation's actual value is null, the
        effective yield is the commodity's plug yield. The T-yields are 180
        bushels per acre for `CORN`, 50 for `SOYBN`, and 65 for `WHEAT`; the plug
        yields are 135 for `CORN`, 37 for `SOYBN`, and 49 for `WHEAT`. The
        `aph_yield_bu_per_acre` is the sum of the five effective yields divided
        by five, rounded half-up to one decimal place."

        Four observed years at 200.0 plus one null (plug 135) year:
        (200+200+200+200+135)/5 = 187.0.

        Design: Difficulty/dual_variant_calc/provisional_vs_certified_aph_plug_fill_divergence
        """
        set_clock(SAFE_CLOCK)
        farm, producer, _ = create_farm_with_member()
        record = create_yield_record_with_observations(
            farm["id"], yields=(200.0, 200.0, 200.0, 200.0, None)
        )
        fetched = validate_success(api.get_yield_record(record["id"], specialist), 200)
        assert_yield_record(fetched)
        assert fetched["aph_yield_bu_per_acre"] == pytest.approx(187.0), (
            f"provisional APH with one plug year must be 187.0, got "
            f"{fetched['aph_yield_bu_per_acre']}"
        )

    def test_certified_aph_replaces_plug_with_observed_value(self, api, specialist):
        """PRD §3.5: "A provisional APH may contain plug-year values; a certified
        APH replaces plugs with observed values, typically producing a different
        (higher) yield." and "The APH recomputes on yield-record creation, on
        each observation append, on the one-time update, and when a disaster
        approval substitutes yields."

        Filling the plug year (2025) with an observed 200.0 and running the
        one-time update + certification yields (200*5)/5 = 200.0, diverging from
        the provisional 187.0.

        Design: Difficulty/dual_variant_calc/provisional_vs_certified_aph_plug_fill_divergence
        """
        set_clock(SAFE_CLOCK)
        farm, producer, _ = create_farm_with_member()
        record = create_yield_record_with_observations(
            farm["id"], yields=(200.0, 200.0, 200.0, 200.0, None)
        )
        provisional = validate_success(
            api.get_yield_record(record["id"], specialist), 200
        )
        assert provisional["aph_yield_bu_per_acre"] == pytest.approx(187.0)
        # Fill the plug year with observed evidence, then update + certify.
        validate_success(
            api.append_yield_observation(
                record["id"],
                {"crop_year": 2025, "actual_yield_bu_per_acre": 200.0},
                specialist,
            ),
            201,
        )
        certified = update_and_certify_yield_record(record["id"], producer["id"])
        fetched = validate_success(api.get_yield_record(record["id"], specialist), 200)
        assert fetched["yield_status"] == "CERTIFIED"
        assert fetched["aph_yield_bu_per_acre"] == pytest.approx(200.0), (
            f"certified APH with all five years observed must be 200.0, got "
            f"{fetched['aph_yield_bu_per_acre']}"
        )
        assert fetched["aph_yield_bu_per_acre"] != provisional["aph_yield_bu_per_acre"]


class TestAphRoundingOrder:
    def test_uniform_observations_average_exactly(self, api, specialist):
        """PRD §3.5: "The `aph_yield_bu_per_acre` is the sum of the five
        effective yields divided by five, rounded half-up to one decimal place."

        Five uniform 180.0 observations: (180*5)/5 = 180.0 after the pinned
        one-decimal rounding.

        Design: Difficulty/combinatorial_formula/aph_rounding_order_pinned
        """
        set_clock(SAFE_CLOCK)
        farm, producer, _ = create_farm_with_member()
        record = create_yield_record_with_observations(farm["id"])
        validate_success(
            api.trigger_yield_update(record["id"], make_producer_headers(producer["id"])),
            200,
        )
        fetched = validate_success(api.get_yield_record(record["id"], specialist), 200)
        assert fetched["aph_yield_bu_per_acre"] == pytest.approx(180.0), (
            f"APH of five 180.0 observations must be 180.0, got "
            f"{fetched['aph_yield_bu_per_acre']}"
        )

    def test_average_rounds_half_up_to_one_decimal(self, api, specialist):
        """PRD §3.5: "The `aph_yield_bu_per_acre` is the sum of the five
        effective yields divided by five, rounded half-up to one decimal place."

        Observations 180, 180, 180, 180, 181 sum to 901; 901/5 = 180.2 exactly
        at the pinned one-decimal precision.

        Design: Difficulty/combinatorial_formula/aph_rounding_order_pinned
        """
        set_clock(SAFE_CLOCK)
        farm, _producer, _ = create_farm_with_member()
        record = create_yield_record_with_observations(
            farm["id"], yields=(180.0, 180.0, 180.0, 180.0, 181.0)
        )
        fetched = validate_success(api.get_yield_record(record["id"], specialist), 200)
        assert fetched["aph_yield_bu_per_acre"] == pytest.approx(180.2), (
            f"APH of (180,180,180,180,181) must round to 180.2, got "
            f"{fetched['aph_yield_bu_per_acre']}"
        )
