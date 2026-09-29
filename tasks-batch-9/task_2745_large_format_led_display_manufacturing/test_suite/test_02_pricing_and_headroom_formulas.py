"""Multi-stage money and bandwidth formulas whose stage ordering is pinned.

Three orderings are exercised here: a ceiling nested inside a minimum, a
per-cabinet rounding that must precede the multiplication by cabinet count, and
a discount tier that is read exactly once off an intermediate subtotal.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers.api_errors import ERR_DATA_LOAD_EXCEEDS_CAPACITY
from test_helpers.assertions import (
    assert_2dp,
    assert_4dp,
    assert_cents,
    assert_contract_fields,
    assert_project_fields,
)
from test_helpers.constants import CONTRACT_PENDING
from test_helpers.factories import FP25_OUT, project_payload, service_contract_payload

#: The exact per-cabinet list value of one FP25-OUT cabinet, 0.2048 sqm at
#: 1234567 cents per square metre, is 252839.3216 cents. The only surcharge on a
#: RETAIL wall with no redundancy is 5%, so the exact surcharged line is
#: 265481.28768 cents, which rounds to a 265481 cent line.
FP25_RETAIL_CABINET_LINE_CENTS = 265481

#: Twenty-five rounded lines. Summing the exact lines first and rounding once at
#: the end would instead give 6637032 cents.
FP25_RETAIL_25_CABINET_CENTS = 6637025
FP25_RETAIL_25_CABINET_SUM_THEN_ROUND_CENTS = 6637032


def _outdoor_retail_wall(model_id, cols, rows, **overrides):
    """A fine-pitch RETAIL wall of the given grid size, viewed from 2.5 metres."""
    payload = {
        "customer_name": "Mall Atrium",
        "install_environment": "RETAIL",
        "site_region_code": "NAW",
        "cabinet_grid_cols": cols,
        "cabinet_grid_rows": rows,
        "min_viewing_distance_m": 2.5,
        "target_brightness_nits": 5000,
        "redundancy_mode": "NONE",
        "output_port_count": 1,
        "port_bandwidth_mbps": 1000,
        "color_depth_bits": 10,
        "refresh_rate_hz": 60,
        "player_count": 1,
    }
    payload.update(overrides)
    return project_payload(model_id, **payload)


class TestControlSystemHeadroomNesting:
    """An inner ceiling feeds an outer minimum before the ratio is rounded."""

    def test_a_wall_that_saturates_its_links_exactly_is_accepted(self, plant):
        """A load of more than 100.00 percent is refused with
        `ERR_DATA_LOAD_EXCEEDS_CAPACITY`; a load of exactly 100.00 percent is
        accepted, because a wall that saturates its links precisely is a
        legitimate — if tight — design.

        Design: Difficulty/combinatorial_formula/project_data_load_pct_nested_min_ceil_floor
        """
        model = plant.register_model(FP25_OUT)

        response = plant.api.create_project(
            _outdoor_retail_wall(model["id"], 2, 2, port_bandwidth_mbps=236),
            plant.engineer,
        )

        project = validate_success(response, 201)
        assert_project_fields(project, cabinet_count=4, module_count=16)
        assert_4dp(project["total_area_sqm"], 0.8192, "total_area_sqm")
        assert project["required_data_mbps"] == 236, (
            "four FP25-OUT cabinets are 131072 pixels, so the raw requirement is "
            "235.9296 Mbps and the ceiling is 236"
        )
        assert project["effective_capacity_mbps"] == 236, (
            "one port of 236 Mbps derated by 1.0 is below the 2500 Mbps a single "
            "player can drive"
        )
        assert_2dp(project["data_load_pct"], 100.00, "data_load_pct")

    def test_one_mbps_short_of_saturation_is_refused(self, plant):
        """`required_data_mbps` is the total pixel count multiplied by
        `color_depth_bits`, multiplied by 3 for the three colour channels,
        multiplied by `refresh_rate_hz`, divided by one million to convert bits
        per second into Mbps, and then **rounded up to the next whole Mbps**.

        Design: Difficulty/combinatorial_formula/project_data_load_pct_nested_min_ceil_floor
        """
        model = plant.register_model(FP25_OUT)

        response = plant.api.create_project(
            _outdoor_retail_wall(model["id"], 2, 2, port_bandwidth_mbps=235),
            plant.engineer,
        )

        validate_error(response, ERR_DATA_LOAD_EXCEEDS_CAPACITY, 422)


class TestHardwarePriceLineRounding:
    """Each cabinet line is rounded before the wall total is formed."""

    def test_a_twenty_five_cabinet_wall_sums_rounded_lines(self, plant):
        """Multiply the exact per-cabinet list value by that multiplier and
        **round the per-cabinet line to whole cents first**; only then multiply
        the rounded line by `cabinet_count` to obtain `contract_amount_cents`.

        Design: Difficulty/combinatorial_formula/contract_amount_round_per_cabinet_then_sum
        """
        model = plant.register_model(FP25_OUT)

        project = validate_success(
            plant.api.create_project(
                _outdoor_retail_wall(
                    model["id"],
                    5,
                    5,
                    customer_name="Concourse Wall",
                    output_port_count=2,
                ),
                plant.engineer,
            ),
            201,
        )

        assert_project_fields(project, cabinet_count=25, module_count=100)
        assert_4dp(project["total_area_sqm"], 5.1200, "total_area_sqm")
        assert_cents(
            project["contract_amount_cents"],
            FP25_RETAIL_25_CABINET_CENTS,
            "contract_amount_cents",
        )
        assert project["required_data_mbps"] == 1475
        assert project["effective_capacity_mbps"] == 2000
        assert_2dp(project["data_load_pct"], 73.75, "data_load_pct")

    def test_summing_exact_lines_and_rounding_once_is_the_wrong_total(self, plant):
        """Summing exact per-cabinet amounts and rounding once at the end is a
        different — and wrong — number.

        Design: Difficulty/combinatorial_formula/contract_amount_round_per_cabinet_then_sum
        """
        model = plant.register_model(FP25_OUT)

        one_cabinet = validate_success(
            plant.api.create_project(
                _outdoor_retail_wall(model["id"], 1, 1), plant.engineer
            ),
            201,
        )
        twenty_five_cabinets = validate_success(
            plant.api.create_project(
                _outdoor_retail_wall(
                    model["id"],
                    5,
                    5,
                    customer_name="Concourse Wall",
                    output_port_count=2,
                ),
                plant.engineer,
            ),
            201,
        )

        assert_cents(
            one_cabinet["contract_amount_cents"],
            FP25_RETAIL_CABINET_LINE_CENTS,
            "contract_amount_cents",
        )
        assert (
            twenty_five_cabinets["contract_amount_cents"]
            != FP25_RETAIL_25_CABINET_SUM_THEN_ROUND_CENTS
        ), (
            "6637032 cents is what a single end-of-wall rounding produces; the "
            "seven cent divergence only shows up once the lines are multiplied"
        )
        assert_cents(
            twenty_five_cabinets["contract_amount_cents"],
            FP25_RETAIL_CABINET_LINE_CENTS * 25,
            "contract_amount_cents",
        )


class TestServiceFeeDiscountTier:
    """The discount tier is chosen from the subtotal and never revisited."""

    def _six_by_six_retail_wall(self, plant):
        model = plant.register_model(FP25_OUT)
        return validate_success(
            plant.api.create_project(
                _outdoor_retail_wall(
                    model["id"],
                    6,
                    6,
                    customer_name="Stadium Ribbon Retailer",
                    output_port_count=5,
                ),
                plant.engineer,
            ),
            201,
        )

    def test_the_spare_carrying_charge_carries_the_subtotal_over_the_break(self, plant):
        """Third — and this is the step implementers get wrong — the volume
        discount tier is selected **from `subtotal_fee_cents`, exactly once**:
        `volume_discount_pct` is 0.00 when the subtotal is below 2000000 cents,
        0.04 when it is below 5000000 cents, 0.07 when it is below 10000000
        cents, and 0.10 otherwise.

        Design: Difficulty/combinatorial_formula/service_contract_fee_discount_tier_from_subtotal_only
        """
        project = self._six_by_six_retail_wall(plant)
        assert_project_fields(project, cabinet_count=36, module_count=144)
        assert_2dp(project["data_load_pct"], 84.96, "data_load_pct")
        assert_cents(project["contract_amount_cents"], 9557316, "contract_amount_cents")

        contract = validate_success(
            plant.api.create_service_contract(
                service_contract_payload(
                    project["id"], tier="GOLD", spare_pct_bp=400, term_months=60
                ),
                plant.service,
            ),
            201,
        )

        assert_contract_fields(
            contract,
            contract_state=CONTRACT_PENDING,
            response_hours=8,
            spare_required_count=6,
            tier="GOLD",
        )
        assert_cents(contract["gross_fee_cents"], 1975910, "gross_fee_cents")
        assert_cents(contract["subtotal_fee_cents"], 2002910, "subtotal_fee_cents")
        assert_2dp(contract["volume_discount_pct"], 0.04, "volume_discount_pct")
        assert_cents(contract["annual_fee_cents"], 1922794, "annual_fee_cents")

    def test_the_tier_is_not_re_derived_from_the_post_discount_fee(self, plant):
        """The tier is never re-evaluated against the post-discount fee, even
        when the discount pushes the fee back below the boundary it just
        crossed.

        Design: Difficulty/combinatorial_formula/service_contract_fee_discount_tier_from_subtotal_only
        """
        project = self._six_by_six_retail_wall(plant)

        contract = validate_success(
            plant.api.create_service_contract(
                service_contract_payload(
                    project["id"], tier="GOLD", spare_pct_bp=400, term_months=60
                ),
                plant.service,
            ),
            201,
        )

        assert contract["volume_discount_pct"] != 0.00, (
            "a gross fee of 1975910 cents alone would have earned nothing, but "
            "the tier is read off the 2002910 cent subtotal"
        )
        assert contract["annual_fee_cents"] != contract["subtotal_fee_cents"], (
            "the selected discount must actually be applied"
        )
        assert contract["annual_fee_cents"] < contract["subtotal_fee_cents"]
        assert (
            contract["subtotal_fee_cents"]
            == contract["gross_fee_cents"] + contract["spare_required_count"] * 4500
        )
