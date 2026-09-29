"""Two derivations whose rounding direction is the whole point.

The spare obligation always rounds up, so any fraction of a module buys a whole
one and the figure reappears in the carrying charge; the control-system headroom
floors the derated port capacity and then rounds the resulting percentage half up.
"""

import pytest

from test_helpers.assertions import assert_cents, assert_contract_fields, assert_project_fields
from test_helpers.constants import (
    CONTRACT_PENDING,
    ENGINEERING_DRAFT,
    PRODUCTION_NOT_STARTED,
)
from test_helpers.factories import FP25_OUT

#: A 2x2 wall of the four-module FP25-OUT family: 4 cabinets, 16 modules and
#: 4 x 0.2048 = 0.8192 square metres.
FOUR_CABINET_GRID = {"cabinet_grid_rows": 2, "cabinet_grid_cols": 2}
FOUR_CABINET_MODULE_COUNT = 16

#: 16 x 200 / 10000 = 0.32 of a module.
FRACTIONAL_SPARE_BP = 200
#: 16 x 625 / 10000 = exactly 1.0000 modules.
EXACT_SPARE_BP = 625
#: 16 x 626 / 10000 = 1.0016 modules.
JUST_OVER_SPARE_BP = 626

#: round(0.8192 x 190000) for the SILVER per-square-metre rate.
SILVER_GROSS_FEE_CENTS = 155648
#: The gross fee plus one and plus two spares at 4500 cents each.
ONE_SPARE_SUBTOTAL_CENTS = 160148
TWO_SPARE_SUBTOTAL_CENTS = 164648
SILVER_RESPONSE_HOURS = 24

#: A 1x1 FP10-IN wall needs ceil(1024 x 10 x 3 x 60 / 1e6) = ceil(1.8432) = 2 Mbps.
REQUIRED_DATA_MBPS = 2

#: A single undertared 320 Mbps port: 2 / 320 x 100 = 0.625, which rounds up.
UNDERATED_PORT_BANDWIDTH_MBPS = 320
UNDERATED_CAPACITY_MBPS = 320
HALF_UP_DATA_LOAD_PCT = 0.63

#: Three 333 Mbps ports halved by a hot backup: 499.5 floors to 499 Mbps.
DERATED_PORT_COUNT = 3
DERATED_PORT_BANDWIDTH_MBPS = 333
DERATED_CAPACITY_MBPS = 499
DERATED_DATA_LOAD_PCT = 0.40

#: Tight enough to separate 0.63 from 0.62 and 0.40 from 0.41.
PCT_EPSILON = 0.001


def _assert_pct(actual, expected, field):
    """Compare a 2-decimal percentage tightly enough to pin its rounding."""
    assert actual is not None, f"{field} must not be null"
    assert actual == pytest.approx(expected, abs=PCT_EPSILON), (
        f"{field}: expected {expected}, got {actual}"
    )


def _three_identical_four_cabinet_walls(plant):
    """One FP25-OUT family and three 2x2 projects, each of 16 modules."""
    model = plant.register_model(FP25_OUT)
    projects = [plant.create_project(model["id"], **FOUR_CABINET_GRID) for _ in range(3)]
    for project in projects:
        assert_project_fields(project, module_count=FOUR_CABINET_MODULE_COUNT)
    return projects


class TestSpareRequirementCeiling:
    """Basis points over the module count, rounded up to a whole module."""

    def test_a_fraction_buys_a_whole_spare_and_an_exact_integer_buys_no_more(self, plant):
        """The spare obligation is `spare_required_count`, computed as the project's
        `module_count` multiplied by `spare_pct_bp`, divided by 10000, and **rounded
        up** to a whole module — a 3% holding on a 700-module wall obliges 21
        modules, and a holding that works out to a fraction obliges the next whole
        module.

        Design: Corner/calculations/spare_requirement_ceils_every_fraction_of_a_module
        """
        first, second, third = _three_identical_four_cabinet_walls(plant)

        fractional = plant.sell_contract(
            first["id"], tier="SILVER", spare_pct_bp=FRACTIONAL_SPARE_BP
        )
        exact = plant.sell_contract(second["id"], tier="SILVER", spare_pct_bp=EXACT_SPARE_BP)
        just_over = plant.sell_contract(
            third["id"], tier="SILVER", spare_pct_bp=JUST_OVER_SPARE_BP
        )

        assert_contract_fields(fractional, spare_required_count=1)
        assert_contract_fields(exact, spare_required_count=1)
        assert_contract_fields(just_over, spare_required_count=2)

    def test_the_ceiled_count_reappears_in_the_carrying_charge(self, plant):
        """Second, the spare carrying charge is `spare_required_count` multiplied by
        4500 cents per held module, and `subtotal_fee_cents` is `gross_fee_cents`
        plus that carrying charge.

        Design: Corner/calculations/spare_requirement_ceils_every_fraction_of_a_module
        """
        first, second, third = _three_identical_four_cabinet_walls(plant)

        fractional = plant.sell_contract(
            first["id"], tier="SILVER", spare_pct_bp=FRACTIONAL_SPARE_BP
        )
        exact = plant.sell_contract(second["id"], tier="SILVER", spare_pct_bp=EXACT_SPARE_BP)
        just_over = plant.sell_contract(
            third["id"], tier="SILVER", spare_pct_bp=JUST_OVER_SPARE_BP
        )

        assert_cents(fractional["gross_fee_cents"], SILVER_GROSS_FEE_CENTS, "gross_fee_cents")
        assert_cents(
            fractional["subtotal_fee_cents"], ONE_SPARE_SUBTOTAL_CENTS, "subtotal_fee_cents"
        )
        _assert_pct(fractional["volume_discount_pct"], 0.00, "volume_discount_pct")
        assert_cents(fractional["annual_fee_cents"], ONE_SPARE_SUBTOTAL_CENTS, "annual_fee_cents")
        assert_cents(
            just_over["subtotal_fee_cents"], TWO_SPARE_SUBTOTAL_CENTS, "subtotal_fee_cents"
        )
        assert_cents(just_over["annual_fee_cents"], TWO_SPARE_SUBTOTAL_CENTS, "annual_fee_cents")
        for contract in (fractional, exact, just_over):
            assert_contract_fields(
                contract,
                contract_state=CONTRACT_PENDING,
                spare_reserved_count=0,
                sla_breach_count=0,
                response_hours=SILVER_RESPONSE_HOURS,
            )
            assert contract["warranty_start_at"] is None


class TestControlSystemHeadroomRounding:
    """One value floors downwards and the next rounds half up."""

    def test_the_load_percentage_rounds_half_up_at_two_decimals(self, plant):
        """`data_load_pct` is `required_data_mbps` divided by
        `effective_capacity_mbps`, multiplied by 100, rounded to 2 decimal places.

        Design: Corner/calculations/data_load_pct_floors_the_capacity_then_rounds_half_up
        """
        model = plant.register_model()

        project = plant.create_project(
            model["id"],
            output_port_count=1,
            port_bandwidth_mbps=UNDERATED_PORT_BANDWIDTH_MBPS,
            redundancy_mode="NONE",
        )

        assert project["required_data_mbps"] == REQUIRED_DATA_MBPS
        assert project["effective_capacity_mbps"] == UNDERATED_CAPACITY_MBPS
        _assert_pct(project["data_load_pct"], HALF_UP_DATA_LOAD_PCT, "data_load_pct")
        assert_project_fields(
            project,
            engineering_state=ENGINEERING_DRAFT,
            production_state=PRODUCTION_NOT_STARTED,
        )

    def test_the_port_capacity_is_floored_after_the_redundancy_derate(self, plant):
        """Port capacity is `output_port_count` multiplied by `port_bandwidth_mbps`
        multiplied by the redundancy derate factor — 1.0 for `NONE`, 0.5 for
        `HOT_BACKUP`, 0.5 for `DUAL_LINK` and 0.75 for `RING` — and then **rounded
        down to a whole Mbps**. Player capacity is `player_count` multiplied by 2500
        Mbps. `effective_capacity_mbps` is the smaller of the floored port capacity
        and the player capacity.

        Design: Corner/calculations/data_load_pct_floors_the_capacity_then_rounds_half_up
        """
        model = plant.register_model()

        project = plant.create_project(
            model["id"],
            output_port_count=DERATED_PORT_COUNT,
            port_bandwidth_mbps=DERATED_PORT_BANDWIDTH_MBPS,
            redundancy_mode="HOT_BACKUP",
        )

        assert project["required_data_mbps"] == REQUIRED_DATA_MBPS
        assert project["effective_capacity_mbps"] == DERATED_CAPACITY_MBPS
        _assert_pct(project["data_load_pct"], DERATED_DATA_LOAD_PCT, "data_load_pct")
        assert_project_fields(
            project,
            engineering_state=ENGINEERING_DRAFT,
            production_state=PRODUCTION_NOT_STARTED,
        )
