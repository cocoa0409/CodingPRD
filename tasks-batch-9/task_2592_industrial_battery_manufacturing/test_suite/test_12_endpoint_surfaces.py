"""Endpoint-surface corners: the charger CRUD chain, the frozen sizing decision,
the accepted-only fleet aggregate, the capacity-test join and the disposition surface."""

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers.api_client import BatteryApiClient
from test_helpers.assertions import (
    assert_close,
    assert_id_sequence,
    assert_sampling_plan,
    created_at_then_id,
    assert_single_resource_envelope,
)
from test_helpers.factories import (
    capacity_test_payload,
    charger_payload,
    disposition_payload,
    plant_payload,
    sizing_decision_payload,
    sizing_request_payload,
    test_chamber_payload as chamber_create_payload,
)
from test_helpers.fixtures import World

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)


def _quote_payload(plant_id: str, application_name: str):
    return sizing_request_payload(
        plant_id,
        application_name=application_name,
        forklift_class="CLASS_II",
        forklift_count=4,
        shifts_per_day=1,
        shift_energy_kwh_per_shift=8.00,
        required_voltage_v=24.0,
        ambient_temp_c=25.0,
        compartment_max_kg=1000.0,
        charge_window_hours=9.00,
        chemistry_preference=C.CHEMISTRY_PREFERENCE_ANY,
    )


def _cheap_charger(world: World):
    return validate_success(
        world.api.create_charger(
            charger_payload(
                "CH-B60",
                chemistry_compatibility=C.CHEMISTRY_LEAD_ACID,
                output_voltage_v=24.0,
                output_amps=60.0,
                price_cents=250000,
                charge_profile="HF_MODULAR",
            ),
            world.fleet,
        ),
        201,
    )


def test_the_charger_catalogue_reads_lists_filters_pages_and_patches(
    api: BatteryApiClient, admin_headers, fleet_headers, warranty_headers
):
    """Three chargers page and filter in the default created_at-then-id order.

    "Chargers may be listed with optional `charge_profile` and `charger_status` filters and read
    individually", the listing being ordered "created_at ASC then id ASC", while "`total_count` is
    the number of rows matching the filters before the page window is applied, and `has_more` is
    true exactly when `offset` plus the number of returned rows is strictly less than
    `total_count`." The catalogue starts open and stays revisable: "A new charger starts
    `AVAILABLE`. A charger may later be discontinued or returned to the catalogue through
    `charger_status`, and its `price_cents` revised at the same time".

    Design: Corner/endpoints/charger_catalogue_supports_read_list_filter_page_and_patch
    """
    validate_success(api.set_clock(C.CLOCK_START, admin_headers), 200)
    ch_z = validate_success(
        api.create_charger(
            charger_payload(
                "CH-Z",
                chemistry_compatibility=C.CHEMISTRY_LEAD_ACID,
                output_voltage_v=24.0,
                output_amps=50.0,
                price_cents=300000,
                charge_profile="FERRO",
            ),
            fleet_headers,
        ),
        201,
    )
    ch_a = validate_success(
        api.create_charger(
            charger_payload(
                "CH-A",
                chemistry_compatibility=C.CHEMISTRY_LEAD_ACID,
                output_voltage_v=24.0,
                output_amps=60.0,
                price_cents=250000,
                charge_profile="HF_MODULAR",
            ),
            fleet_headers,
        ),
        201,
    )
    ch_m = validate_success(
        api.create_charger(
            charger_payload(
                "CH-M",
                chemistry_compatibility=C.CHEMISTRY_LITHIUM_LFP,
                output_voltage_v=25.6,
                output_amps=100.0,
                price_cents=450000,
                charge_profile="LITHIUM_CCCV",
            ),
            fleet_headers,
        ),
        201,
    )

    read_response = api.get_charger(ch_a["id"], fleet_headers)
    one = validate_success(read_response, 200)
    assert_single_resource_envelope(read_response)
    assert one["model_code"] == "CH-A"
    assert_close(one["output_amps"], 60.0, "output_amps", 1)
    assert one["charger_status"] == "AVAILABLE"

    rows, meta = validate_paginated(api.list_chargers(admin_headers))
    assert_id_sequence(rows, created_at_then_id([ch_z, ch_a, ch_m]))
    assert meta["total_count"] == 3

    ferro, ferro_meta = validate_paginated(
        api.list_chargers(admin_headers, {"charge_profile": "FERRO"})
    )
    assert ferro_meta["total_count"] == 1, ferro
    assert ferro[0]["id"] == ch_z["id"]

    page_one, page_one_meta = validate_paginated(
        api.list_chargers(admin_headers, {"limit": 2, "offset": 0})
    )
    assert len(page_one) == 2, page_one
    assert page_one_meta["total_count"] == 3
    assert page_one_meta["has_more"] is True
    page_two, page_two_meta = validate_paginated(
        api.list_chargers(admin_headers, {"limit": 2, "offset": 2})
    )
    assert len(page_two) == 1, page_two
    assert page_two_meta["total_count"] == 3
    assert page_two_meta["offset"] == 2
    assert page_two_meta["has_more"] is False

    patched = validate_success(
        api.update_charger(
            ch_z["id"], {"charger_status": "DISCONTINUED", "price_cents": 275000}, fleet_headers
        ),
        200,
    )
    assert patched["charger_status"] == "DISCONTINUED"
    assert patched["price_cents"] == 275000
    assert patched["version"] == ch_z["version"] + 1
    assert_close(patched["output_amps"], 50.0, "output_amps", 1)
    assert patched["charge_profile"] == "FERRO"

    available, available_meta = validate_paginated(
        api.list_chargers(warranty_headers, {"charger_status": "AVAILABLE"})
    )
    assert available_meta["total_count"] == 2, available
    assert {row["id"] for row in available} == {ch_a["id"], ch_m["id"]}


def test_accepting_a_quote_freezes_the_selection_against_later_catalogue_edits(world: World):
    """The ACCEPT returns the whole request, and discontinuing the charger afterwards changes nothing.

    "The decision moves `request_state` to `ACCEPTED` or `WITHDRAWN` respectively and is otherwise
    inert: the recorded selection and every derived factor are frozen and **never recomputed**, so a
    later price change, charger discontinuation or design retirement cannot alter a quote that has
    already been decided." Neither can the action be replayed: "Either action requires the request to
    be `MATCHED`; a request already `ACCEPTED` or `WITHDRAWN` is refused with
    `ERR_SIZING_REQUEST_STATE_INVALID`, so neither decision can be reversed".

    Design: Corner/endpoints/sizing_decision_is_an_action_endpoint_that_freezes_the_recorded_selection
    """
    charger = _cheap_charger(world)
    quote = validate_success(
        world.api.create_sizing_request(
            _quote_payload(world.plant_id, "Aisle Pickers"), world.fleet
        ),
        201,
    )
    assert quote["request_state"] == C.SIZING_MATCHED

    accepted = validate_success(
        world.api.decide_sizing_request(
            quote["id"],
            sizing_decision_payload("ACCEPT", decision_note="quote accepted by the customer"),
            world.fleet,
        ),
        200,
    )
    assert accepted["request_state"] == C.SIZING_ACCEPTED
    assert accepted["selected_charger_id"] == charger["id"]
    assert accepted["selected_cell_design_id"] == world.design_id
    assert_close(accepted["selected_charge_hours"], 7.13, "selected_charge_hours", 2)
    assert accepted["fleet_capital_cents"] == 2500000

    validate_success(
        world.api.update_charger(
            charger["id"],
            {"charger_status": "DISCONTINUED", "price_cents": 999000},
            world.fleet,
        ),
        200,
    )

    frozen = validate_success(
        world.api.get_sizing_request(quote["id"], world.fleet), 200
    )
    assert frozen["selected_charger_id"] == charger["id"]
    assert_close(frozen["selected_charge_hours"], 7.13, "selected_charge_hours", 2)
    assert frozen["fleet_capital_cents"] == 2500000

    validate_error(
        world.api.decide_sizing_request(
            quote["id"],
            sizing_decision_payload("WITHDRAW", decision_note="too late"),
            world.fleet,
        ),
        E.ERR_SIZING_REQUEST_STATE_INVALID,
    )
    assert (
        validate_success(world.api.get_sizing_request(quote["id"], world.fleet), 200)[
            "request_state"
        ]
        == C.SIZING_ACCEPTED
    )


def test_the_fleet_analysis_aggregates_accepted_quotes_only(world: World):
    """Of three identical quotes only the accepted one contributes to the plant aggregate.

    "The fleet analysis aggregates the plant's accepted sizing quotes and returns
    `accepted_request_count`, the summed `recommended_battery_count` and
    `recommended_charger_count`, the summed `fleet_capital_cents`, and a `lines` array with the
    per-request contributions." A withdrawn quote and an undecided one are therefore invisible to it,
    even though "Sizing requests may be listed with optional `plant_id`, `selected_cell_design_id`,
    `selected_charger_id` and `request_state` filters" still finds them.

    Design: Corner/endpoints/fleet_analysis_is_a_computed_read_over_accepted_requests_only
    """
    _cheap_charger(world)
    quotes = [
        validate_success(
            world.api.create_sizing_request(
                _quote_payload(world.plant_id, f"Aisle Pickers {suffix}"), world.fleet
            ),
            201,
        )
        for suffix in ("A", "B", "C")
    ]
    for quote in quotes:
        assert quote["fleet_capital_cents"] == 2500000

    validate_success(
        world.api.decide_sizing_request(
            quotes[0]["id"], sizing_decision_payload("ACCEPT"), world.fleet
        ),
        200,
    )
    validate_success(
        world.api.decide_sizing_request(
            quotes[1]["id"], sizing_decision_payload("WITHDRAW"), world.fleet
        ),
        200,
    )

    analysis = validate_success(
        world.api.get_fleet_analysis(world.plant_id, world.fleet), 200
    )
    assert analysis["accepted_request_count"] == 1
    assert analysis["recommended_battery_count"] == 4
    assert analysis["recommended_charger_count"] == 2
    assert analysis["fleet_capital_cents"] == 2500000
    assert len(analysis["lines"]) == 1, analysis["lines"]
    assert quotes[0]["id"] in str(analysis["lines"][0])

    again = validate_success(
        world.api.get_fleet_analysis(world.plant_id, world.fleet), 200
    )
    assert again == analysis

    matched, matched_meta = validate_paginated(
        world.api.list_sizing_requests(
            world.fleet, {"plant_id": world.plant_id, "request_state": C.SIZING_MATCHED}
        )
    )
    assert matched_meta["total_count"] == 1, matched
    assert matched[0]["id"] == quotes[2]["id"]


def test_a_capacity_test_joins_an_assembly_to_a_chamber_of_the_same_plant(world: World):
    """A chamber at a second site is refused even though both foreign keys resolve.

    "The chamber must belong to the same plant as the assembly's lot, otherwise
    `ERR_PLANT_SCOPE_MISMATCH`", and a scheduled row starts empty: "A new test initialises
    `test_state` to `SCHEDULED` with `measured_capacity_ah`, `cycles_completed`, `result` and
    `yield_pct` all null." The join is navigable from either side, since "Tests may be listed with
    optional `assembly_id`, `chamber_id`, `recorded_by_worker_id`, `test_type`, `test_state` and
    `result` filters".

    Design: Corner/endpoints/capacity_test_links_an_assembly_and_a_chamber_and_rejects_a_cross_plant_pair
    """
    east = validate_success(
        world.api.create_plant(
            plant_payload(
                name="Eastside Battery Works",
                site_code="PLTEAST",
                licensed_chemistries=[C.CHEMISTRY_LEAD_ACID],
                lead_initial_inventory_kg=5000.000,
            ),
            world.admin,
        ),
        201,
    )
    chamber_a = world.add_chamber()
    chamber_b = validate_success(
        world.api.create_test_chamber(
            chamber_create_payload(east["id"], "TC-EAST"), world.admin
        ),
        201,
    )

    lot = world.lot_in_state(C.LOT_ASSEMBLY, "LOT-X", 9)
    assembly = world.certify_assembly(lot["id"], "ASM-X1")
    world.draw_plan(lot["id"])

    validate_error(
        world.api.create_capacity_test(
            capacity_test_payload(assembly["id"], chamber_b["id"]), world.qa_a
        ),
        E.ERR_PLANT_SCOPE_MISMATCH,
    )

    scheduled = validate_success(
        world.api.create_capacity_test(
            capacity_test_payload(assembly["id"], chamber_a), world.qa_a
        ),
        201,
    )
    assert scheduled["assembly_id"] == assembly["id"]
    assert scheduled["chamber_id"] == chamber_a
    assert scheduled["test_state"] == C.TEST_STATE_SCHEDULED
    for field in ("measured_capacity_ah", "cycles_completed", "result", "yield_pct"):
        assert scheduled[field] is None, f"{field} should open null: {scheduled[field]}"

    orphans, orphan_meta = validate_paginated(
        world.api.list_capacity_tests(world.qa_a, {"chamber_id": chamber_b["id"]})
    )
    assert orphans == [], orphans
    assert orphan_meta["total_count"] == 0

    linked, linked_meta = validate_paginated(
        world.api.list_capacity_tests(world.qa_a, {"assembly_id": assembly["id"]})
    )
    assert linked_meta["total_count"] == 1, linked
    assert linked[0]["id"] == scheduled["id"]


def test_the_disposition_surface_refuses_release_but_admits_quarantine_then_retest(
    world: World,
):
    """One endpoint, four actions: RELEASE is blocked on evidence while QUARANTINE is legal.

    "A shortfall on either sampling requirement -- too few completed tests, or no passing cycle-life
    sample at all -- is `ERR_SAMPLING_INCOMPLETE`, and a lot whose current sampling window holds zero
    completed tests fails there." The same state admits another action, and the retest rebuilds the
    plan by itself: "It increments `retest_count`, zeroes `completed_test_count`, `failed_test_count`
    and `passed_cycle_life_count` so that the tightened plan is judged on fresh evidence, and then
    **immediately redraws the plan itself** under the tightened branch, incrementing
    `sampling_plan_revision` by 1", where tightening means "`sample_size` becomes the smaller of
    twice the clamped size and 20, and `acceptance_number` becomes the tiered value minus 1 but never
    below 0."

    Design: Corner/endpoints/lot_disposition_admits_quarantine_and_retest_but_refuses_release_until_sampling_is_complete
    """
    lot = world.lot_in_state(C.LOT_ASSEMBLY, "LOT-D", 12)
    world.certify_assembly(lot["id"], "ASM-D1")
    plan = world.draw_plan(lot["id"])
    assert_sampling_plan(plan, sample_size=4, acceptance_number=0, revision=1)
    assert plan["process_state"] == C.LOT_TESTING

    validate_error(
        world.api.disposition_lot(
            lot["id"],
            disposition_payload(C.DISPOSITION_RELEASE, "premature release attempt"),
            world.qa_a,
        ),
        E.ERR_SAMPLING_INCOMPLETE,
    )
    assert world.read_lot(lot["id"])["process_state"] == C.LOT_TESTING

    quarantined = world.disposition(
        lot["id"], C.DISPOSITION_QUARANTINE, note="hold pending evidence"
    )
    assert quarantined["process_state"] == C.LOT_QUARANTINED

    retested = world.disposition(
        lot["id"], C.DISPOSITION_RETEST, note="re-open with a tightened plan"
    )
    assert retested["process_state"] == C.LOT_TESTING
    assert retested["retest_count"] == 1
    assert retested["sampling_plan_revision"] == 2

    summary = validate_success(world.api.get_quality_summary(lot["id"], world.qa_a), 200)
    assert summary["sample_size"] == 8
    assert summary["acceptance_number"] == 0
    assert summary["completed_test_count"] == 0
    assert summary["failed_test_count"] == 0
