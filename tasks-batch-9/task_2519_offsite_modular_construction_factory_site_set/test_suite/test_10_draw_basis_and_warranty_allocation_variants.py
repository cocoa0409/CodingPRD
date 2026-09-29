"""Two calculations that each run one of two genuinely different variants.

A draw's ``basis_mode`` decides which modules the lender's money is drawn
against, and a defect claim's status decides whether responsibility is presumed
from the phase the defect was discovered in or re-derived from inspection and
site evidence. Both pairs of variants can reach materially different answers
from identical underlying state, so each variant is exercised separately and
then the divergence itself is asserted.
"""

import pytest

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_cents,
    assert_module_dimensions,
    assert_two_decimal_value,
)
from test_helpers.test_users import (
    LENDER_DRAW_ADMINISTRATOR,
    TRANSPORT_COORDINATOR,
    WARRANTY_ADJUDICATOR,
)

WIP_UNIT_VALUE_CENTS = f.FACTORY_WIP_UNIT_VALUE_CENTS  # 8_750_000


@pytest.fixture
def one_delivered_and_one_partly_built_module(api):
    """M-01 delivered to site; M-02 still on the line at station 2 of 6."""
    world = fx.world_delivered_module(
        api, package_overrides={"field_scope_items_open": 2}
    )
    fx.add_module(world, "M-02", 2)
    fx.schedule_slot(world, "M-02", "2026-09-03T14:00:00Z")
    fx.advance_stations(world, "M-02", 2)
    return world


def test_work_in_progress_basis_prices_every_module_still_on_the_plant_books(
    one_delivered_and_one_partly_built_module,
):
    """PRD §3.9: "Under `WIP_DEPOSIT`, the basis is every module of the project whose `production_status` is `SLOTTED`, `IN_LINE` or `LINE_COMPLETE` and whose `qc_status` is not `HOLD`; each such module contributes its station-progress earned value as defined in §3.4 — the plant's `wip_unit_value_cents` pro-rated by completed stations — and a module that has never left the plant contributes normally."
    PRD §3.9: "`basis_module_count` is the number of modules in the basis and `basis_earned_cents` is the sum of those already-rounded per-module terms."
    PRD §3.9: "Under `WIP_DEPOSIT`, `requested_cents` is `basis_earned_cents` multiplied by the project's `deposit_pct` — 20 percent of work in progress by default — rounded half up to a whole cent."

    Design: Difficulty/dual_variant_calc/draw_basis_variant_divergence_wip_deposit_vs_milestone_set
    """
    world = one_delivered_and_one_partly_built_module
    draw = validate_success(
        world.api.create_draw_request(
            f.draw_request_payload(world.project_id, world.agency_id, "WIP_DEPOSIT", 1),
            LENDER_DRAW_ADMINISTRATOR,
        ),
        201,
    )

    assert draw["basis_module_count"] == 2
    assert_cents(draw["basis_earned_cents"], 11666667, "basis_earned_cents")
    assert_cents(draw["requested_cents"], 2333333, "requested_cents")


def test_milestone_basis_prices_only_the_modules_that_reached_the_site(
    one_delivered_and_one_partly_built_module,
):
    """PRD §3.9: "Under `MILESTONE_SET`, the basis is every module of the project whose `site_status` is `DELIVERED`, `SET` or `CONNECTED`, and each such module contributes the plant's full `wip_unit_value_cents`, ignoring `station_index` entirely."
    PRD §3.9: "Under `MILESTONE_SET`, `requested_cents` is simply `basis_earned_cents`, because milestone draws are funded in full against delivered modules rather than deposited against."

    Design: Difficulty/dual_variant_calc/draw_basis_variant_divergence_wip_deposit_vs_milestone_set
    """
    world = one_delivered_and_one_partly_built_module
    draw = validate_success(
        world.api.create_draw_request(
            f.draw_request_payload(
                world.project_id, world.agency_id, "MILESTONE_SET", 1
            ),
            LENDER_DRAW_ADMINISTRATOR,
        ),
        201,
    )

    assert draw["basis_module_count"] == 1
    assert_cents(draw["basis_earned_cents"], WIP_UNIT_VALUE_CENTS, "basis_earned_cents")
    assert_cents(draw["requested_cents"], WIP_UNIT_VALUE_CENTS, "requested_cents")


def test_the_two_basis_modes_diverge_on_identical_module_state(
    one_delivered_and_one_partly_built_module,
):
    """PRD §3.9: "The two variants diverge sharply: a `LINE_COMPLETE` module still standing at the factory contributes its full unit value under the work-in-progress variant and nothing at all under the milestone variant, while a delivered module contributes the full unit value under both."
    PRD §3.4: "When the module's `production_status` is `SLOTTED`, `IN_LINE` or `LINE_COMPLETE` *and* its `qc_status` is not `HOLD`, the earned value is the plant's `wip_unit_value_cents` multiplied by the module's `station_index`, divided by the plant's `station_count`, and rounded half up to a whole cent."

    Design: Difficulty/dual_variant_calc/draw_basis_variant_divergence_wip_deposit_vs_milestone_set
    """
    world = one_delivered_and_one_partly_built_module
    wip = validate_success(
        world.api.create_draw_request(
            f.draw_request_payload(world.project_id, world.agency_id, "WIP_DEPOSIT", 1),
            LENDER_DRAW_ADMINISTRATOR,
        ),
        201,
    )
    milestone = validate_success(
        world.api.create_draw_request(
            f.draw_request_payload(
                world.project_id, world.agency_id, "MILESTONE_SET", 2
            ),
            LENDER_DRAW_ADMINISTRATOR,
        ),
        201,
    )

    # M-01 is LINE_COMPLETE at station 6 of 6 and DELIVERED, so it contributes
    # the full 8,750,000 unit value to both bases. M-02 is IN_LINE at station 2
    # of 6 and still at the plant, so it contributes 8,750,000 x 2/6 = 2,916,667
    # to the plant-floor basis and nothing to the milestone basis. That single
    # module's station-progress value is the whole divergence.
    assert wip["basis_earned_cents"] - milestone["basis_earned_cents"] == 2916667
    assert wip["basis_module_count"] == 2
    assert milestone["basis_module_count"] == 1

    # The partly built module's own station-progress value is what the two
    # bases disagree about, and only the plant-floor variant counts it.
    assert_cents(
        world.refresh_module("M-02")["wip_earned_cents"], 2916667, "wip_earned_cents"
    )


@pytest.fixture
def transit_defect_claim_on_a_conditionally_released_module(api):
    """A 1,234,567 cent claim raised in transit against a factory-scope module.

    The module carries a CONDITIONAL final-factory inspection at severity 4, so
    both allocation variants have something to work from.
    """
    world = fx.world_line_complete_module(
        api,
        module_overrides={"connection_scope_owner": "FACTORY"},
        package_overrides={"field_scope_items_open": 2},
    )
    in_plant = fx.open_inspection(api, world.module_id(), world.agency_id, "IN_PLANT")
    fx.record_result(api, in_plant["id"], world.agency_id, "PASS")
    final = fx.open_inspection(
        api, world.module_id(), world.agency_id, "FINAL_FACTORY"
    )
    world.inspections["M-01:FINAL_FACTORY"] = fx.record_result(
        api, final["id"], world.agency_id, "CONDITIONAL", 2, 4
    )

    world.shipment = fx.create_shipment(
        api,
        world.project_id,
        ["WA"],
        carrier_code="HVY-1",
        planned_departure_at="2026-09-05T06:00:00Z",
        planned_arrival_at="2026-09-05T16:00:00Z",
    )
    world.shipment = fx.load_module(
        api, world.shipment_id, world.module_id(), world.shipment["version"]
    )
    get_success_data(
        api.record_route_survey(
            world.shipment_id,
            f.route_survey_payload("2026-09-04T12:00:00Z", "2026-09-20T00:00:00Z"),
            TRANSPORT_COORDINATOR,
        )
    )
    get_success_data(
        api.dispatch_shipment(
            world.shipment_id,
            {"departed_at": "2026-09-05T06:00:00Z"},
            TRANSPORT_COORDINATOR,
        )
    )
    world.refresh_module()

    claim = validate_success(
        api.create_defect_claim(
            f.defect_claim_payload(
                world.module_id(),
                "TRANSIT",
                1234567,
                inspection_id=final["id"],
                description="corner shear panel cracked",
            ),
            world.factory_manager,
        ),
        201,
    )
    return world, claim


def test_first_allocation_reads_the_discovery_phase_presumption_alone(
    transit_defect_claim_on_a_conditionally_released_module,
):
    """PRD §3.8: "The presumption table is fixed: a defect discovered in the `FACTORY` phase puts `factory_share_pct` at 100.00, one discovered in `TRANSIT` puts it at 50.00, one discovered in `SITE_SET` puts it at 25.00, and one discovered in `POST_SET` puts it at 0.00."
    PRD §3.8: "`factory_charge_cents` is the claim's `repair_cost_cents` multiplied by `factory_share_pct`, divided by 100, rounded half up to a whole cent."
    PRD §3.8: "`field_charge_cents` is `repair_cost_cents` minus `factory_charge_cents`, which makes the field charge absorb the rounding remainder so that the two charges always sum exactly to the repair cost."
    PRD §3.8: "`responsibility` is `FACTORY` when `factory_share_pct` is exactly 100.00, `FIELD` when it is exactly 0.00, and `SHARED` at every value in between."

    Design: Difficulty/dual_variant_calc/defect_allocation_variant_divergence_presumption_vs_evidence
    """
    world, claim = transit_defect_claim_on_a_conditionally_released_module

    adjudicated = validate_success(
        world.api.adjudicate_defect_claim(
            claim["id"], f.adjudicate_payload(adjudication_note="phase presumption applied"), WARRANTY_ADJUDICATOR
        )
    )

    assert_two_decimal_value(
        adjudicated["factory_share_pct"], 50.00, "factory_share_pct"
    )
    assert_cents(adjudicated["factory_charge_cents"], 617284, "factory_charge_cents")
    assert_cents(adjudicated["field_charge_cents"], 617283, "field_charge_cents")
    assert adjudicated["responsibility"] == "SHARED"
    assert adjudicated["warranty_bucket"] == "SPLIT"
    assert adjudicated["adjudication_round"] == 1


def test_re_allocation_after_a_dispute_discards_the_presumption_for_evidence(
    transit_defect_claim_on_a_conditionally_released_module,
):
    """PRD §3.8: "The factory score gains 6 points when the referenced inspection record's `result` is `FAIL` or `CONDITIONAL`; a further 3 points when that record's `severity_max` is at least 3; and a further 2 points when the module's `defect_count_factory` is strictly greater than its `defect_count_field`."
    PRD §3.8: "Otherwise `factory_share_pct` is the factory score multiplied by 100, divided by the sum of the two scores, rounded half up to two decimal places."
    PRD §3.8: "`warranty_bucket` follows directly: `FACTORY_WARRANTY` when responsibility is `FACTORY`, `FIELD_WARRANTY` when it is `FIELD`, and `SPLIT` when it is `SHARED`."

    Design: Difficulty/dual_variant_calc/defect_allocation_variant_divergence_presumption_vs_evidence
    """
    world, claim = transit_defect_claim_on_a_conditionally_released_module
    validate_success(
        world.api.adjudicate_defect_claim(
            claim["id"], f.adjudicate_payload(), WARRANTY_ADJUDICATOR
        )
    )
    validate_success(
        world.api.dispute_defect_claim(
            claim["id"],
            f.dispute_payload("final inspection already flagged this panel CONDITIONAL"),
            world.factory_manager,
        )
    )

    reallocated = validate_success(
        world.api.adjudicate_defect_claim(
            claim["id"], f.adjudicate_payload(adjudication_note="evidence weighted"), WARRANTY_ADJUDICATOR
        )
    )

    assert_two_decimal_value(
        reallocated["factory_share_pct"], 100.00, "factory_share_pct"
    )
    assert_two_decimal_value(reallocated["field_share_pct"], 0.00, "field_share_pct")
    assert_cents(reallocated["factory_charge_cents"], 1234567, "factory_charge_cents")
    assert_cents(reallocated["field_charge_cents"], 0, "field_charge_cents")
    assert reallocated["responsibility"] == "FACTORY"
    assert reallocated["warranty_bucket"] == "FACTORY_WARRANTY"
    assert reallocated["adjudication_round"] == 2


def test_the_module_defect_counters_are_stamped_after_the_allocation_lands(
    transit_defect_claim_on_a_conditionally_released_module,
):
    """PRD §3.8: "Finally, and strictly *after* the allocation has been computed, the module's counters are updated — `defect_count_factory` increases by 1 when responsibility landed on `FACTORY`, and `defect_count_field` increases by 1 when it landed on `FIELD` — so that an adjudication never feeds its own evidence back into itself."

    Design: Difficulty/dual_variant_calc/defect_allocation_variant_divergence_presumption_vs_evidence
    """
    world, claim = transit_defect_claim_on_a_conditionally_released_module
    validate_success(
        world.api.adjudicate_defect_claim(
            claim["id"], f.adjudicate_payload(), WARRANTY_ADJUDICATOR
        )
    )
    validate_success(
        world.api.dispute_defect_claim(
            claim["id"], f.dispute_payload(), world.factory_manager
        )
    )
    validate_success(
        world.api.adjudicate_defect_claim(
            claim["id"], f.adjudicate_payload(), WARRANTY_ADJUDICATOR
        )
    )

    module = world.refresh_module()
    assert module["defect_count_factory"] == 1
    assert module["defect_count_field"] == 0
    assert_module_dimensions(module, site_status="IN_TRANSIT")
