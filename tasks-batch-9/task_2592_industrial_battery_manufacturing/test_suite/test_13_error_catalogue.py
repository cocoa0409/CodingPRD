"""Error-catalogue corners: each family of refusals is reachable and distinct.

The four instances translated here walk the auth/schema/404 family, the
wrong-state family, the two selector refusals and the run/test lifecycle
refusals, checking that codes which look interchangeable are not.
"""

from test_helpers import api_errors as E
from test_helpers import constants as C
from test_helpers.api_client import BatteryApiClient
from test_helpers.assertions import (
    assert_assembly_axes,
    assert_close,
    assert_envelope,
    assert_lot_counters,
)
from test_helpers.factories import (
    advance_payload,
    capacity_result_payload,
    capacity_test_payload,
    charger_payload,
    complete_run_payload,
    cycle_life_result_payload,
    formation_run_payload,
    lead_design_payload,
    plant_payload,
    production_lot_payload,
    review_action_payload,
    rework_payload,
    sizing_request_payload,
    torque_verification_payload,
    worker_payload,
)
from test_helpers.fixtures import World
from test_helpers.test_users import headers_without_role

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

GHOST_IDS = [f"00000000-0000-0000-0000-0000000000{n:02x}" for n in range(1, 13)]


def test_the_auth_role_schema_and_not_found_codes_are_each_reachable(
    api: BatteryApiClient, admin_headers, warranty_headers
):
    """Four gates and eleven not-found codes, none of them collapsed into a generic one.

    "If either header is absent, empty, or `X-User-Role` names anything other than one of the seven
    roles enumerated below, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)." Above the
    404 family sits tier 7: "path identifier existence, validated left to right, yielding whichever
    of `ERR_PLANT_NOT_FOUND`, `ERR_WORKER_NOT_FOUND`, `ERR_CELL_DESIGN_NOT_FOUND`,
    `ERR_LOT_NOT_FOUND`, `ERR_FORMATION_RUN_NOT_FOUND`, `ERR_ASSEMBLY_NOT_FOUND`,
    `ERR_CAPACITY_TEST_NOT_FOUND`, `ERR_SIZING_REQUEST_NOT_FOUND` or `ERR_BATTERY_UNIT_NOT_FOUND`
    matches the unresolved segment. Formation bays, test chambers and chargers addressed by path id
    yield `ERR_FORMATION_BAY_NOT_FOUND`, `ERR_TEST_CHAMBER_NOT_FOUND` and `ERR_CHARGER_NOT_FOUND`
    respectively." Every refusal is shaped alike: "The `meta` object for error responses contains
    only `api_request_id` and `api_request_timestamp`."

    Design: Corner/errors/auth_validation_and_not_found_codes_are_each_triggerable
    """
    validate_success(api.set_clock(C.CLOCK_START, admin_headers), 200)
    ghost = plant_payload(
        name="Ghost Works",
        site_code="PLTGHOST",
        licensed_chemistries=[C.CHEMISTRY_LEAD_ACID],
        monthly_lead_emission_permit_g=1000.00,
        lead_initial_inventory_kg=10.000,
    )

    anonymous = api.create_plant(ghost, headers_without_role())
    validate_error(anonymous, E.ERR_UNAUTHENTICATED)
    body = assert_envelope(anonymous, "error")
    assert set(body["meta"]) == {
        "api_request_id",
        "api_request_timestamp",
    }, f"error meta must carry exactly two keys: {body['meta']}"
    assert set(body["data"]) == {
        "error_id",
        "message",
    }, f"error data must carry error_id and message: {body['data']}"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]

    validate_error(api.create_plant(ghost, warranty_headers), E.ERR_ROLE_NOT_PERMITTED)
    validate_error(
        api.create_plant(
            plant_payload(
                name="Ghost Works",
                site_code="PLTGHOST",
                permit_status="PENDING_RENEWAL_TYPO",
            ),
            admin_headers,
        ),
        E.ERR_VALIDATION,
    )
    validate_error(
        api.create_worker(
            worker_payload(GHOST_IDS[0], "Nobody", "PRODUCTION"), admin_headers
        ),
        E.ERR_PLANT_NOT_FOUND,
    )

    lookups = [
        (api.get_plant, E.ERR_PLANT_NOT_FOUND),
        (api.get_worker, E.ERR_WORKER_NOT_FOUND),
        (api.get_cell_design, E.ERR_CELL_DESIGN_NOT_FOUND),
        (api.get_formation_bay, E.ERR_FORMATION_BAY_NOT_FOUND),
        (api.get_test_chamber, E.ERR_TEST_CHAMBER_NOT_FOUND),
        (api.get_production_lot, E.ERR_LOT_NOT_FOUND),
        (api.get_battery_assembly, E.ERR_ASSEMBLY_NOT_FOUND),
        (api.get_formation_run, E.ERR_FORMATION_RUN_NOT_FOUND),
        (api.get_capacity_test, E.ERR_CAPACITY_TEST_NOT_FOUND),
        (api.get_charger, E.ERR_CHARGER_NOT_FOUND),
        (api.get_sizing_request, E.ERR_SIZING_REQUEST_NOT_FOUND),
        (api.get_battery_unit, E.ERR_BATTERY_UNIT_NOT_FOUND),
    ]
    for (getter, expected), ghost_id in zip(lookups, GHOST_IDS):
        validate_error(getter(ghost_id, admin_headers), expected)

    rows, meta = validate_paginated(api.list_plants(admin_headers))
    assert rows == [], rows
    assert meta["total_count"] == 0


def test_eight_wrong_state_refusals_answer_eight_distinct_codes(world: World):
    """A DRAFT design, a PENDING assembly and a LOT_TESTING lot each refuse in two ways.

    "`ERR_DESIGN_STATE_INVALID` guards `PATCH /cell-designs/{id}` and `POST
    /cell-designs/{id}/review-actions`" while the lot surface answers a different code entirely:
    "`ERR_DESIGN_NOT_APPROVED` guards `POST /production-lots`." The assembly pair splits the same
    way -- "Reworking a `PENDING` assembly whose axes have not both been decided, or a `CERTIFIED`
    one, is refused with `ERR_ASSEMBLY_STATE_INVALID`" against "The assembly's
    `certification_status` must be `CERTIFIED`; a `PENDING`, `REJECTED` or `REVOKED` assembly is
    refused with `ERR_ASSEMBLY_NOT_CERTIFIED`". The remaining four are the structural cross-check
    ("it must equal exactly twice the assembly's `module_count`, and any other value is refused with
    `ERR_CONNECTION_COUNT_MISMATCH`"), the once-per-generation lock ("A second attempt to record an
    axis that already holds a `PASS` or `FAIL` verdict is refused with
    `ERR_ASSEMBLY_AXIS_ALREADY_RECORDED`, regardless of which verdict is already there and
    regardless of what the new reading would say"), the backwards hop ("`to_state` must be the
    immediate successor of the current state") and the empty window ("The end must be strictly after
    the start, otherwise `ERR_WINDOW_INVALID`").

    Design: Corner/errors/state_invalid_and_evidence_codes_are_each_triggerable
    """
    chamber_id = world.add_chamber()
    draft = world.draft_design(
        lead_design_payload(
            "CD-DRAFT",
            plate_type=C.PLATE_FLAT_PASTED,
            nominal_capacity_ah=400.0,
            rated_cycles=1200,
            warranty_months=48,
            pack_weight_kg=850.0,
            lead_content_kg=280.000,
            formation_charge_factor=1.40,
            list_price_cents=420000,
        )
    )
    lot = world.lot_in_state(C.LOT_ASSEMBLY, "LOT-S", 12)
    pending = world.add_assembly(lot["id"], "ASM-S1")

    validate_error(
        world.api.review_cell_design(
            draft["id"], review_action_payload("APPROVE"), world.eng_b
        ),
        E.ERR_DESIGN_STATE_INVALID,
    )
    validate_error(
        world.api.create_production_lot(
            production_lot_payload(world.plant_id, draft["id"], "LOT-DRAFT", 12),
            world.sup_a,
        ),
        E.ERR_DESIGN_NOT_APPROVED,
    )
    validate_error(
        world.api.rework_assembly(pending["id"], rework_payload(), world.sup_a),
        E.ERR_ASSEMBLY_STATE_INVALID,
    )

    validate_error(
        world.api.record_verification(
            pending["id"], torque_verification_payload(20.0, 10), world.qa_a
        ),
        E.ERR_CONNECTION_COUNT_MISMATCH,
    )
    assert_assembly_axes(
        world.read_assembly(pending["id"]),
        torque_status=C.AXIS_PENDING,
        certification_status=C.CERT_PENDING,
    )

    torqued = validate_success(
        world.api.record_verification(
            pending["id"], torque_verification_payload(20.0, 12), world.qa_a
        ),
        200,
    )
    assert_assembly_axes(torqued, torque_status=C.AXIS_PASS)
    validate_error(
        world.api.record_verification(
            pending["id"], torque_verification_payload(21.0, 12), world.qa_a
        ),
        E.ERR_ASSEMBLY_AXIS_ALREADY_RECORDED,
    )
    assert_close(
        world.read_assembly(pending["id"])["measured_torque_nm"],
        20.0,
        "measured_torque_nm",
        1,
    )

    certified = world.certify_assembly(lot["id"], "ASM-S2")
    world.draw_plan(lot["id"], plan_reason="acceptance plan so tests may be scheduled")
    assert world.read_lot(lot["id"])["process_state"] == C.LOT_TESTING

    validate_error(
        world.api.create_capacity_test(
            capacity_test_payload(pending["id"], chamber_id), world.qa_a
        ),
        E.ERR_ASSEMBLY_NOT_CERTIFIED,
    )
    validate_error(
        world.api.advance_lot(
            lot["id"], advance_payload(C.LOT_FORMATION), world.sup_a
        ),
        E.ERR_LOT_STATE_INVALID,
    )
    validate_error(
        world.api.create_capacity_test(
            capacity_test_payload(
                certified["id"],
                chamber_id,
                "2026-09-03T10:00:00Z",
                "2026-09-03T10:00:00Z",
            ),
            world.qa_a,
        ),
        E.ERR_WINDOW_INVALID,
    )

    lots, lot_meta = validate_paginated(world.api.list_production_lots(world.sup_a))
    assert lot_meta["total_count"] == 1, lots
    tests, test_meta = validate_paginated(world.api.list_capacity_tests(world.qa_a))
    assert tests == [], tests
    assert test_meta["total_count"] == 0


def test_the_selector_refuses_twice_and_leaves_no_request_behind(world: World):
    """An empty pool and a pool with no feasible charger are two codes, and neither persists a row.

    "When `evaluated_design_count` is zero -- no approved design of the preferred chemistry matched
    the voltage, weight and capacity envelope -- the request is refused with
    `ERR_NO_ELIGIBLE_CELL_DESIGN`. When designs were eligible but not one of them had a feasible
    charger, the request is refused with `ERR_NO_CHARGER_MATCH`. In both cases **no sizing request
    row is persisted**; a failed quote leaves no trace, so an engineer cannot list unmatched
    requests." The margin between the two is arithmetic: recharge time "is the design's
    `nominal_capacity_ah` multiplied by the depth-of-discharge cap for its chemistry -- the pack is
    only refilling the part that was actually used -- multiplied by the sizing charge factor for that
    chemistry, which is 1.15 for `LEAD_ACID` and 1.05 for `LITHIUM_LFP` to account for charge
    inefficiency, then divided by the charger's `output_amps` and rounded half up to two decimal
    places. That figure must be less than or equal to `charge_window_hours`; a pair landing exactly
    on the window is feasible."

    Design: Corner/errors/sizing_selector_codes_are_each_triggerable_without_persisting_a_request
    """
    validate_success(
        world.api.create_charger(
            charger_payload("CH-A50", output_amps=50.0, price_cents=300000), world.fleet
        ),
        201,
    )
    validate_success(
        world.api.create_charger(
            charger_payload(
                "CH-B60",
                output_amps=60.0,
                price_cents=250000,
                charge_profile="HF_MODULAR",
            ),
            world.fleet,
        ),
        201,
    )

    def quote(application_name, **overrides):
        return sizing_request_payload(
            world.plant_id,
            application_name=application_name,
            forklift_class="CLASS_II",
            forklift_count=4,
            shift_energy_kwh_per_shift=8.00,
            shifts_per_day=1,
            ambient_temp_c=25.0,
            compartment_max_kg=1000.0,
            **overrides,
        )

    validate_error(
        world.api.create_sizing_request(
            quote(
                "High Voltage Reach Trucks",
                required_voltage_v=48.0,
                charge_window_hours=9.00,
            ),
            world.fleet,
        ),
        E.ERR_NO_ELIGIBLE_CELL_DESIGN,
    )
    validate_error(
        world.api.create_sizing_request(
            quote(
                "Tight Window Pickers",
                required_voltage_v=24.0,
                charge_window_hours=7.00,
            ),
            world.fleet,
        ),
        E.ERR_NO_CHARGER_MATCH,
    )
    validate_error(
        world.api.create_sizing_request(
            quote(
                "Lithium Only Pickers",
                required_voltage_v=24.0,
                charge_window_hours=9.00,
                chemistry_preference=C.CHEMISTRY_LITHIUM_LFP,
            ),
            world.fleet,
        ),
        E.ERR_NO_ELIGIBLE_CELL_DESIGN,
    )

    rows, meta = validate_paginated(
        world.api.list_sizing_requests(world.fleet, {"plant_id": world.plant_id})
    )
    assert rows == [], rows
    assert meta["total_count"] == 0

    matched = validate_success(
        world.api.create_sizing_request(
            quote(
                "Aisle Pickers",
                required_voltage_v=24.0,
                charge_window_hours=9.00,
            ),
            world.fleet,
        ),
        201,
    )
    assert matched["request_state"] == C.SIZING_MATCHED
    assert matched["evaluated_design_count"] == 1
    assert matched["required_ah"] == 438
    assert_close(matched["selected_charge_hours"], 7.13, "selected_charge_hours", 2)


def test_the_run_and_test_lifecycle_refusals_each_answer_their_own_code(world: World):
    """A bay out of service, an implausible meter reading, a settled run and both cycle-life halves.

    "A bay in `MAINTENANCE` accepts no new runs and no run starts, and both refusals are
    `ERR_BAY_UNAVAILABLE`", and its chamber counterpart is separate: "its `chamber_status` must be
    `AVAILABLE`, otherwise `ERR_CHAMBER_UNAVAILABLE`". The meter has a sanity band -- "The metered
    reading must be strictly positive and at most twice `estimated_energy_kwh`; anything else is
    `ERR_METERED_ENERGY_OUT_OF_RANGE`" -- and a settled run is closed to further completion:
    "`ERR_RUN_STATE_INVALID` guards `POST /formation-runs/{id}/start`, `POST
    /formation-runs/{id}/complete` and `POST /formation-runs/{id}/abort`." On the result surface,
    "The test must be `SCHEDULED` and the logical clock must have reached or passed
    `scheduled_end_at` -- a result cannot be filed before the window it describes has closed -- and
    any violation of either is `ERR_CAPACITY_TEST_STATE_INVALID`", while the discriminator answers
    one code from both sides: "`cycles_completed` is required when the test's `test_type` is
    `CYCLE_LIFE` and must be omitted when it is `CAPACITY`, and either mismatch is refused with
    `ERR_CYCLE_LIFE_SAMPLE_MISSING`."

    Design: Corner/errors/run_and_test_lifecycle_codes_are_each_triggerable
    """
    bay_ok = world.add_bay(C.BAY_CODE)
    bay_down = world.add_bay("BAY-2")
    validate_success(
        world.api.update_formation_bay(
            bay_down, {"bay_status": C.BAY_MAINTENANCE}, world.admin
        ),
        200,
    )
    chamber_ok = world.add_chamber(C.CHAMBER_CODE)
    chamber_down = world.add_chamber("TC-2")
    validate_success(
        world.api.update_test_chamber(
            chamber_down, {"chamber_status": C.CHAMBER_MAINTENANCE}, world.admin
        ),
        200,
    )

    lot = world.lot_in_state(C.LOT_FORMATION, "LOT-R", 9)
    run = world.schedule_run(lot["id"], bay_ok)
    assert_close(run["estimated_energy_kwh"], 102.00, "estimated_energy_kwh", 2)
    world.set_clock("2026-09-02T06:00:00Z")
    world.start_run(run["id"])
    world.set_clock("2026-09-02T12:00:00Z")

    validate_error(
        world.api.create_formation_run(
            formation_run_payload(
                lot["id"], bay_down, "2026-09-03T06:00:00Z", "2026-09-03T12:00:00Z"
            ),
            world.sup_a,
        ),
        E.ERR_BAY_UNAVAILABLE,
    )

    settlement = complete_run_payload(100.00, 95.00, "2026-09-02T12:00:00Z")
    validate_error(
        world.api.complete_formation_run(
            run["id"],
            complete_run_payload(300.00, 95.00, "2026-09-02T12:00:00Z"),
            world.sup_a,
        ),
        E.ERR_METERED_ENERGY_OUT_OF_RANGE,
    )
    assert world.read_run(run["id"])["run_state"] == C.RUN_STATE_CHARGING

    completed = validate_success(
        world.api.complete_formation_run(run["id"], settlement, world.sup_a), 200
    )
    assert completed["run_state"] == C.RUN_STATE_COMPLETED
    assert_close(completed["metered_energy_kwh"], 100.00, "metered_energy_kwh", 2)
    validate_error(
        world.api.complete_formation_run(run["id"], settlement, world.sup_a),
        E.ERR_RUN_STATE_INVALID,
    )

    world.advance_lot_to(lot["id"], C.LOT_ASSEMBLY)
    assembly = world.certify_assembly(lot["id"], "ASM-R1")
    world.draw_plan(lot["id"], plan_reason="acceptance plan so tests may be scheduled")

    validate_error(
        world.api.create_capacity_test(
            capacity_test_payload(assembly["id"], chamber_down), world.qa_a
        ),
        E.ERR_CHAMBER_UNAVAILABLE,
    )
    capacity = world.schedule_test(
        assembly["id"], chamber_ok, "2026-09-03T08:00:00Z", "2026-09-03T10:00:00Z"
    )
    cycle_life = world.schedule_test(
        assembly["id"],
        chamber_ok,
        "2026-09-03T10:00:00Z",
        "2026-09-03T12:00:00Z",
        test_type=C.TEST_TYPE_CYCLE_LIFE,
    )

    validate_error(
        world.api.record_test_result(
            capacity["id"], capacity_result_payload(441.8), world.qa_a
        ),
        E.ERR_CAPACITY_TEST_STATE_INVALID,
    )

    world.set_clock("2026-09-03T12:00:00Z")
    validate_error(
        world.api.record_test_result(
            capacity["id"], cycle_life_result_payload(441.8, 900), world.qa_a
        ),
        E.ERR_CYCLE_LIFE_SAMPLE_MISSING,
    )
    validate_error(
        world.api.record_test_result(
            cycle_life["id"], capacity_result_payload(372.0), world.qa_a
        ),
        E.ERR_CYCLE_LIFE_SAMPLE_MISSING,
    )

    for test in (capacity, cycle_life):
        after = world.read_test(test["id"])
        assert after["test_state"] == C.TEST_STATE_SCHEDULED
        assert after["result"] is None
    assert_lot_counters(world.read_lot(lot["id"]), completed=0, failed=0)
