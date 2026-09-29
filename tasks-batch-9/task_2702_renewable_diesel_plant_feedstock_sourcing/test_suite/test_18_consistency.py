"""Read-after-write on the allocation: every derived field is correct at once.

One allocation is posted and the campaign's reserved mass, blend carbon
intensity and hydrogen requirement, together with the lot's allocated and
remaining mass, are already final on the very next read — and stay identical
across repeated reads, with no settling step in between.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_mass, assert_one_decimal
from test_helpers.test_users import TRADER_HEADERS
from test_helpers.types import ALLOC_RESERVED, FEEDSTOCK_UCO


def test_the_campaign_and_the_lot_are_already_final_on_the_next_read(api):
    """PRD §3.5: "Its effect is immediate and four-sided: the mass is added to the lot's
    `allocated_mass_mt` and subtracted from the lot's `remaining_mass_mt` with the lot's `version`
    bumped; it is added to the campaign's `reserved_mass_mt`; the campaign's
    `blend_ci_gco2e_per_mj` and `required_h2_kg_per_day` are recomputed; and the campaign's
    `version` is bumped."
    PRD §3.5: "The new allocation records the campaign it serves as its `run_id`, starts at status
    `RESERVED`, and carries `line_cost_usd` unset and `release_reason` null."
    PRD §4: "Endpoints that bring a brand-new resource into existence respond with HTTP 201 and
    return that resource"

    Design: Corner/consistency_model/allocation_response_already_carries_the_recomputed_blend
    """
    supplier = fx.verified_supplier(api, feedstock_types=[FEEDSTOCK_UCO])
    lot = fx.accepted_lot(
        api, supplier["id"], mass_mt=500.000, attested_ci_gco2e_per_mj=32.50
    )
    plant = fx.commissioned_unit(api)
    run = fx.make_run(
        api, plant["unit"]["id"], plant["charge"]["id"], target_saf_share_pct=0.00
    )
    rv1 = run["version"]

    created = validate_success(
        api.create_allocation(
            run["id"], f.allocation_payload(lot["id"], 400.000, rv1), TRADER_HEADERS
        ),
        201,
    )
    assert created["run_id"] == run["id"]
    assert created["lot_id"] == lot["id"]
    assert created["status"] == ALLOC_RESERVED, f"got {created['status']}"
    assert_mass(created["mass_mt"], 400.000, "mass_mt")

    first = validate_success(api.get_processing_run(run["id"], TRADER_HEADERS))
    assert_mass(first["reserved_mass_mt"], 400.000, "reserved_mass_mt")
    assert first["blend_ci_gco2e_per_mj"] == 32.50, f"got {first['blend_ci_gco2e_per_mj']}"
    assert_one_decimal(first["required_h2_kg_per_day"], 2560.0, "required_h2_kg_per_day")
    assert first["version"] == rv1 + 1, f"got {first['version']}"

    charged_lot = validate_success(api.get_feedstock_lot(lot["id"], TRADER_HEADERS))
    assert_mass(charged_lot["allocated_mass_mt"], 400.000, "allocated_mass_mt")
    assert_mass(charged_lot["remaining_mass_mt"], 100.000, "remaining_mass_mt")
    assert charged_lot["version"] == lot["version"] + 1, f"got {charged_lot['version']}"

    for _ in range(3):
        again = validate_success(api.get_processing_run(run["id"], TRADER_HEADERS))
        assert again == first, "no derived field settles after the fact"
        lot_again = validate_success(api.get_feedstock_lot(lot["id"], TRADER_HEADERS))
        assert lot_again == charged_lot, "no lot figure settles after the fact"
