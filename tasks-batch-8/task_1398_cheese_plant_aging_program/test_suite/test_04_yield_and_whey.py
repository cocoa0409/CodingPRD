"""Yield accounting (provisional vs actual variants) and whey-stream
valorization math."""
import pytest

from test_helpers import (
    ApiErrorId,
    make_cheesemaker_headers,
    make_completed_batch,
    validate_error,
    validate_success,
    whey_stream_for_make,
)
from test_helpers.test_users import CM_ALICE, TEST_USERS

CHEESEMAKER = TEST_USERS["cheesemaker_headers"]


class TestYieldVariants:
    def test_provisional_and_actual_yield_values(self, api):
        """PRD §3.5: "Finally `yield_provisional_pct` is the estimated cheese
        mass divided by `liters_committed` and multiplied by one hundred,
        rounded half-up to two decimal places. The actual yield
        `yield_actual_pct` is observed rather than modeled: `green_weight_kg`
        divided by `liters_committed`, multiplied by one hundred, rounded
        half-up to two decimal places."

        Design: Difficulty/dual_variant_calc/cheese_batch_provisional_vs_actual_yield_diverge
        """
        ctx = make_completed_batch(
            variety="CHEDDAR", volume_liters=10000.0, liters_committed=10000.0,
            green_weight_kg=980.0, wheels_produced=10, fat_pct=3.85, protein_pct=3.10,
        )
        batch = validate_success(api.get_cheese_batch(ctx["batch_id"], CHEESEMAKER))
        assert batch["yield_provisional_pct"] == pytest.approx(19.18, abs=0.001), (
            "component-model provisional yield for 10000 L at fat 3.85 / "
            f"protein 3.10 must be 19.18, got {batch['yield_provisional_pct']}"
        )
        assert batch["yield_actual_pct"] == pytest.approx(9.80, abs=0.001), (
            f"observed yield 980.0 / 10000.0 * 100 must be 9.80, got {batch['yield_actual_pct']}"
        )

    def test_provisional_yield_independent_of_green_weight(self, api):
        """PRD §3.5: "The provisional yield is a component-model estimate
        derived from the committed milk."
        PRD §3.5: "For identical inputs the two figures diverge whenever actual
        press and hoop losses differ from the theoretical recovery."

        Design: Difficulty/dual_variant_calc/cheese_batch_provisional_vs_actual_yield_diverge
        """
        ctx = make_completed_batch(
            variety="CHEDDAR", volume_liters=10000.0, liters_committed=10000.0,
            green_weight_kg=1000.0, wheels_produced=10, fat_pct=3.85, protein_pct=3.10,
        )
        batch = validate_success(api.get_cheese_batch(ctx["batch_id"], CHEESEMAKER))
        assert batch["yield_provisional_pct"] == pytest.approx(19.18, abs=0.001), (
            "the provisional component model ignores the recorded green weight"
        )
        assert batch["yield_actual_pct"] == pytest.approx(10.00, abs=0.001)
        assert batch["yield_provisional_pct"] != batch["yield_actual_pct"], (
            "the two yield variants must diverge for these inputs"
        )


class TestWheyValorization:
    def test_whey_split_pinned_evaluation_and_rounding_order(self, api):
        """PRD §3.5: "A `Cheesemaker` records valorization — whey sold into WPC
        or feed channels — by setting `valorized_kg`, and each update
        re-derives the stream in a pinned order: first `disposed_kg` as
        `total_whey_kg` minus `valorized_kg`, then `valorization_rate_pct` as
        `valorized_kg` divided by `total_whey_kg` and multiplied by one
        hundred. Each stored field is rounded half-up to two decimal places in
        that order."

        Design: Difficulty/combinatorial_formula/whey_split_pinned_evaluation_and_rounding_order
        """
        ctx = make_completed_batch(
            variety="CHEDDAR", volume_liters=10000.0, liters_committed=10000.0,
            green_weight_kg=980.0, wheels_produced=10, fat_pct=3.85, protein_pct=3.10,
        )
        whey = validate_success(
            api.update_whey_stream(
                ctx["whey"]["id"], {"valorized_kg": 7000.0},
                make_cheesemaker_headers(CM_ALICE),
            )
        )
        assert whey["total_whey_kg"] == pytest.approx(9020.0)
        assert whey["disposed_kg"] == pytest.approx(2020.0), (
            f"disposed must be 9020.0 - 7000.0, got {whey['disposed_kg']}"
        )
        assert whey["valorization_rate_pct"] == pytest.approx(77.61, abs=0.001), (
            f"rate 7000/9020*100 rounds half-up to 77.61, got {whey['valorization_rate_pct']}"
        )

    def test_whey_valorize_exactly_total_is_permitted(self, api):
        """PRD §3.5: "A valorized amount that would push `disposed_kg` below
        zero is rejected with `ERR_WHEY_OVER_VALORIZED`; valorizing exactly the
        total, leaving zero disposal, is permitted."

        Design: Difficulty/combinatorial_formula/whey_split_pinned_evaluation_and_rounding_order
        """
        ctx = make_completed_batch(
            variety="CHEDDAR", volume_liters=10000.0, liters_committed=10000.0,
            green_weight_kg=980.0, wheels_produced=10, fat_pct=3.85, protein_pct=3.10,
        )
        whey = validate_success(
            api.update_whey_stream(
                ctx["whey"]["id"], {"valorized_kg": 9020.0},
                make_cheesemaker_headers(CM_ALICE),
            )
        )
        assert whey["disposed_kg"] == pytest.approx(0.0)
        assert whey["valorization_rate_pct"] == pytest.approx(100.0), (
            f"valorizing the full total yields rate 100.00, got {whey['valorization_rate_pct']}"
        )

    def test_whey_over_valorization_rejected(self, api):
        """PRD §3.5: "A valorized amount that would push `disposed_kg` below
        zero is rejected with `ERR_WHEY_OVER_VALORIZED`; valorizing exactly the
        total, leaving zero disposal, is permitted."

        Design: Corner/validations/whey_over_valorization_rejected
        """
        ctx = make_completed_batch(
            variety="CHEDDAR", volume_liters=10000.0, liters_committed=10000.0,
            green_weight_kg=980.0, wheels_produced=10, fat_pct=3.85, protein_pct=3.10,
        )
        resp = api.update_whey_stream(
            ctx["whey"]["id"], {"valorized_kg": 9020.01},
            make_cheesemaker_headers(CM_ALICE),
        )
        validate_error(resp, ApiErrorId.ERR_WHEY_OVER_VALORIZED, 422)
