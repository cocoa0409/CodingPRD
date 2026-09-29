"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, because each test starts against an empty plant. Helpers use
the lenient success validator so that a broken precondition surfaces as a
setup failure rather than as a confusing assertion failure.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC
from .factories import (
    a1_program_payload,
    a2l_program_payload,
    allocate_payload,
    cancel_build_order_payload,
    charge_payload,
    close_corrective_action_payload,
    compressor_supply_payload,
    control_board_supply_payload,
    create_build_order_payload,
    create_certification_record_payload,
    create_distributor_order_payload,
    create_run_test_payload,
    create_test_cell_payload,
    create_warehouse_payload,
    create_warehouse_reservation_payload,
    create_warranty_claim_payload,
    decide_certification_payload,
    helium_leak_test_payload,
    high_a2l_platform_payload,
    northeast_standard_payload,
    pressure_decay_leak_test_payload,
    reject_certification_payload,
    release_reservation_payload,
    return_to_draft_payload,
    set_clock_payload,
    ship_payload,
    southeast_standard_payload,
    standard_a1_platform_payload,
)
from .test_users import TEST_USERS, make_headers

# ---------------------------------------------------------------------------
# Canonical operator identifiers used by the composite chains below.
# ---------------------------------------------------------------------------

DESIGN_ENGINEER_ID = "user-de-1"
RELIABILITY_ENGINEER_ID = "user-re-1"
RELIABILITY_ENGINEER_2_ID = "user-re-2"
CERTIFICATION_ENGINEER_ID = "user-ce-1"
CERTIFICATION_ENGINEER_2_ID = "user-ce-2"
REGULATORY_AUDITOR_ID = "user-ra-1"
LEAK_TECHNICIAN_ID = "user-qt-1"
RUN_TECHNICIAN_ID = "user-qt-2"
PRODUCTION_TECHNICIAN_ID = "user-pt-1"
WARRANTY_ANALYST_ID = "user-wa-1"
DISTRIBUTOR_REP_1_ID = "user-dr-1"
DISTRIBUTOR_REP_2_ID = "user-dr-2"
DISTRIBUTOR_REP_3_ID = "user-dr-3"

ADMIN = TEST_USERS["plant_admin_headers"]
DESIGN = TEST_USERS["design_engineer_headers"]
RELIABILITY = TEST_USERS["reliability_engineer_headers"]
CERTIFIER = TEST_USERS["certification_engineer_headers"]
AUDITOR = TEST_USERS["regulatory_auditor_headers"]
SUPPLY = TEST_USERS["supply_planner_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
TECHNICIAN = TEST_USERS["production_technician_headers"]
LEAK_TECH = TEST_USERS["quality_technician_headers"]
RUN_TECH = TEST_USERS["quality_technician_2_headers"]
ANALYST = TEST_USERS["warranty_analyst_headers"]
REP_1 = TEST_USERS["distributor_rep_headers"]
REP_2 = TEST_USERS["distributor_rep_2_headers"]
REP_3 = TEST_USERS["distributor_rep_3_headers"]


def _data(response):
    return get_success_data(response)


# ---------------------------------------------------------------------------
# Tier 1: primitives and state progression
# ---------------------------------------------------------------------------


def set_clock(current_utc: str = DEFAULT_CLOCK_UTC):
    """Move the logical plant clock. Returns the raw response."""
    return api_client.set_clock(set_clock_payload(current_utc), ADMIN)


def create_a2l_program(**overrides) -> dict:
    """Register a mildly flammable (A2L) refrigerant program."""
    return _data(
        api_client.create_refrigerant_program(a2l_program_payload(**overrides), ADMIN)
    )


def create_a1_program(**overrides) -> dict:
    """Register a non-flammable (A1) refrigerant program."""
    return _data(
        api_client.create_refrigerant_program(a1_program_payload(**overrides), ADMIN)
    )


def create_southeast_standard(**overrides) -> dict:
    return _data(
        api_client.create_regional_standard(southeast_standard_payload(**overrides), ADMIN)
    )


def create_northeast_standard(**overrides) -> dict:
    return _data(
        api_client.create_regional_standard(northeast_standard_payload(**overrides), ADMIN)
    )


def create_high_a2l_draft_platform(program_id: str, **overrides) -> dict:
    """HIGH-tier platform on an A2L program, in DRAFT."""
    return _data(
        api_client.create_product_platform(
            high_a2l_platform_payload(program_id, **overrides), DESIGN
        )
    )


def create_standard_a1_draft_platform(program_id: str, **overrides) -> dict:
    """STANDARD-tier platform on an A1 program, in DRAFT."""
    return _data(
        api_client.create_product_platform(
            standard_a1_platform_payload(program_id, **overrides), DESIGN
        )
    )


def submit_platform(platform_id: str, submitter_id: str = DESIGN_ENGINEER_ID) -> dict:
    """Advance DRAFT to ENG_REVIEW, recording submitter_id as the submitter."""
    return _data(
        api_client.submit_engineering_review(
            platform_id, make_headers(submitter_id, "DesignEngineer")
        )
    )


def release_platform(
    platform_id: str, releaser_id: str = RELIABILITY_ENGINEER_ID
) -> dict:
    """Advance ENG_REVIEW to RELEASED by an engineer who is not the submitter."""
    return _data(
        api_client.release_platform(
            platform_id, make_headers(releaser_id, "ReliabilityEngineer")
        )
    )


def return_platform_to_draft(
    platform_id: str,
    revision_notes: str = "Coil circuit revision required for the A2L charge limit",
    reviewer_id: str = RELIABILITY_ENGINEER_ID,
) -> dict:
    return _data(
        api_client.return_platform_to_draft(
            platform_id,
            return_to_draft_payload(revision_notes),
            make_headers(reviewer_id, "ReliabilityEngineer"),
        )
    )


def create_released_high_a2l_platform(program_id: str, **overrides) -> dict:
    """DRAFT to ENG_REVIEW to RELEASED for a HIGH/A2L design."""
    platform = create_high_a2l_draft_platform(program_id, **overrides)
    submit_platform(platform["id"])
    release_platform(platform["id"])
    return _data(api_client.get_product_platform(platform["id"], ADMIN))


def create_released_standard_a1_platform(program_id: str, **overrides) -> dict:
    """DRAFT to ENG_REVIEW to RELEASED for a STANDARD/A1 design."""
    platform = create_standard_a1_draft_platform(program_id, **overrides)
    submit_platform(platform["id"])
    release_platform(platform["id"])
    return _data(api_client.get_product_platform(platform["id"], ADMIN))


def read_program(program_id: str) -> dict:
    return _data(api_client.get_refrigerant_program(program_id, ADMIN))


def read_platform(platform_id: str) -> dict:
    return _data(api_client.get_product_platform(platform_id, ADMIN))


def read_supply(supply_id: str) -> dict:
    return _data(api_client.get_component_supply(supply_id, SUPPLY))


def read_order(order_id: str) -> dict:
    return _data(api_client.get_distributor_order(order_id, SUPPLY))


def read_build_order(build_order_id: str) -> dict:
    return _data(api_client.get_build_order(build_order_id, PLANNER))


def read_warehouse(warehouse_id: str) -> dict:
    return _data(api_client.get_warehouse(warehouse_id, PLANNER))


def read_reservation(reservation_id: str) -> dict:
    return _data(api_client.get_warehouse_reservation(reservation_id, PLANNER))


def create_warehouse(name: str = "WH-1", pallet_capacity: int = 50) -> dict:
    return _data(
        api_client.create_warehouse(create_warehouse_payload(name, pallet_capacity), ADMIN)
    )


def create_test_cell(cell_code: str = "CELL-1", cooldown_minutes: int = None) -> dict:
    overrides = {} if cooldown_minutes is None else {"cooldown_minutes": cooldown_minutes}
    return _data(
        api_client.create_test_cell(create_test_cell_payload(cell_code, **overrides), ADMIN)
    )


# ---------------------------------------------------------------------------
# Tier 2: certification chains
# ---------------------------------------------------------------------------


def file_certification(
    platform_id: str,
    expected_platform_version: int,
    region_code: str = "SOUTHEAST",
    rated_seer2_submitted: float = 15.80,
    engineer_id: str = CERTIFICATION_ENGINEER_ID,
) -> dict:
    return _data(
        api_client.create_certification_record(
            create_certification_record_payload(
                platform_id,
                expected_platform_version,
                region_code=region_code,
                rated_seer2_submitted=rated_seer2_submitted,
            ),
            make_headers(engineer_id, "CertificationEngineer"),
        )
    )


def submit_certification(
    record_id: str, engineer_id: str = CERTIFICATION_ENGINEER_ID
) -> dict:
    return _data(
        api_client.submit_certification_record(
            record_id, make_headers(engineer_id, "CertificationEngineer")
        )
    )


def certify_certification(record_id: str, auditor_id: str = REGULATORY_AUDITOR_ID) -> dict:
    return _data(
        api_client.decide_certification_record(
            record_id,
            decide_certification_payload("CERTIFIED"),
            make_headers(auditor_id, "RegulatoryAuditor"),
        )
    )


def reject_certification(
    record_id: str,
    rejection_reason: str = "SEER2 test report incomplete",
    auditor_id: str = REGULATORY_AUDITOR_ID,
) -> dict:
    return _data(
        api_client.decide_certification_record(
            record_id,
            reject_certification_payload(rejection_reason),
            make_headers(auditor_id, "RegulatoryAuditor"),
        )
    )


def certify_platform_for_region(
    platform_id: str,
    region_code: str = "SOUTHEAST",
    rated_seer2_submitted: float = 15.80,
    engineer_id: str = CERTIFICATION_ENGINEER_ID,
    auditor_id: str = REGULATORY_AUDITOR_ID,
) -> dict:
    """File, submit, and certify one region for an already released platform.

    Returns the certified certification record.
    """
    platform = read_platform(platform_id)
    record = file_certification(
        platform_id,
        platform["version"],
        region_code=region_code,
        rated_seer2_submitted=rated_seer2_submitted,
        engineer_id=engineer_id,
    )
    submit_certification(record["id"], engineer_id=engineer_id)
    return certify_certification(record["id"], auditor_id=auditor_id)


def setup_certified_high_a2l_platform(
    region_code: str = "SOUTHEAST", **program_overrides
) -> dict:
    """SOUTHEAST standard + A2L program + released HIGH platform certified for
    that region. Returns {program, platform, standard, certification}.
    """
    standard = create_southeast_standard()
    program = create_a2l_program(**program_overrides)
    platform = create_released_high_a2l_platform(program["id"])
    certification = certify_platform_for_region(platform["id"], region_code=region_code)
    return {
        "standard": standard,
        "program": program,
        "platform": read_platform(platform["id"]),
        "certification": certification,
    }


# ---------------------------------------------------------------------------
# Tier 3: build-lot lifecycle walkers
# ---------------------------------------------------------------------------


def create_build_order(
    platform_id: str,
    quantity_units: int = 20,
    scheduled_start_utc: str = "2026-08-05T08:00:00Z",
    is_preseason: bool = None,
) -> dict:
    overrides = {}
    if is_preseason is not None:
        overrides["is_preseason"] = is_preseason
    payload = create_build_order_payload(
        platform_id, quantity_units, scheduled_start_utc, **overrides
    )
    return _data(api_client.create_build_order(payload, PLANNER))


def braze_lot(build_order_id: str) -> dict:
    """DRAFT (or REWORK) to COIL_FAB to BRAZED."""
    api_client.start_coil_fab(build_order_id, TECHNICIAN)
    return _data(api_client.complete_brazing(build_order_id, TECHNICIAN))


def record_helium_leak_test(
    build_order_id: str,
    measured_leak_rate_g_per_year: float = 1.20,
    technician_id: str = LEAK_TECHNICIAN_ID,
) -> dict:
    return _data(
        api_client.create_leak_test(
            helium_leak_test_payload(build_order_id, measured_leak_rate_g_per_year),
            make_headers(technician_id, "QualityTechnician"),
        )
    )


def record_pressure_decay_leak_test(
    build_order_id: str,
    decay_kpa: float = 1.90,
    hold_minutes: int = 30,
    technician_id: str = LEAK_TECHNICIAN_ID,
) -> dict:
    return _data(
        api_client.create_leak_test(
            pressure_decay_leak_test_payload(build_order_id, decay_kpa, hold_minutes),
            make_headers(technician_id, "QualityTechnician"),
        )
    )


def charge_lot(build_order_id: str, charge_grams: int = 1750) -> dict:
    return _data(
        api_client.charge_build_order(
            build_order_id, charge_payload(charge_grams), TECHNICIAN
        )
    )


def record_run_test(
    build_order_id: str,
    test_cell_id: str,
    window_start_utc: str = "2026-08-05T08:00:00Z",
    window_end_utc: str = "2026-08-05T09:00:00Z",
    measured_capacity_btuh: int = 36000,
    measured_power_w: int = 2850,
    measured_ambient_c: float = 33.0,
    technician_id: str = RUN_TECHNICIAN_ID,
) -> dict:
    return _data(
        api_client.create_run_test(
            create_run_test_payload(
                build_order_id,
                test_cell_id,
                window_start_utc,
                window_end_utc,
                measured_capacity_btuh,
                measured_power_w,
                measured_ambient_c,
            ),
            make_headers(technician_id, "QualityTechnician"),
        )
    )


def release_lot_to_stock(build_order_id: str) -> dict:
    return _data(api_client.release_to_stock(build_order_id, PLANNER))


def setup_brazed_high_a2l_lot(quantity_units: int = 20, **program_overrides) -> dict:
    """A2L program + released HIGH platform + one lot walked to BRAZED.

    Returns {program, platform, build_order}.
    """
    program = create_a2l_program(**program_overrides)
    platform = create_released_high_a2l_platform(program["id"])
    build_order = create_build_order(platform["id"], quantity_units=quantity_units)
    braze_lot(build_order["id"])
    return {
        "program": program,
        "platform": platform,
        "build_order": read_build_order(build_order["id"]),
    }


def setup_brazed_standard_a1_lot(quantity_units: int = 10, **program_overrides) -> dict:
    """A1 program + released STANDARD platform + one lot walked to BRAZED."""
    program = create_a1_program(**program_overrides)
    platform = create_released_standard_a1_platform(program["id"])
    build_order = create_build_order(platform["id"], quantity_units=quantity_units)
    braze_lot(build_order["id"])
    return {
        "program": program,
        "platform": platform,
        "build_order": read_build_order(build_order["id"]),
    }


def setup_charged_high_a2l_lot(
    quantity_units: int = 20,
    charge_grams: int = 1750,
    leak_rate: float = 1.20,
    cell_code: str = "CELL-1",
    cooldown_minutes: int = None,
    **program_overrides,
) -> dict:
    """A2L HIGH lot walked to CHARGED, plus a registered test cell.

    Returns {program, platform, build_order, test_cell}.
    """
    scenario = setup_brazed_high_a2l_lot(quantity_units, **program_overrides)
    record_helium_leak_test(scenario["build_order"]["id"], leak_rate)
    charge_lot(scenario["build_order"]["id"], charge_grams)
    scenario["test_cell"] = create_test_cell(cell_code, cooldown_minutes)
    scenario["build_order"] = read_build_order(scenario["build_order"]["id"])
    return scenario


def walk_lot_to_released_to_stock(
    build_order_id: str,
    test_cell_id: str,
    charge_grams: int = 1750,
    leak_rate: float = 1.20,
    window_start_utc: str = "2026-08-05T08:00:00Z",
    window_end_utc: str = "2026-08-05T09:00:00Z",
    measured_capacity_btuh: int = 36000,
    measured_power_w: int = 2850,
    measured_ambient_c: float = 33.0,
) -> dict:
    """BRAZED-capable lot walked all the way to RELEASED_TO_STOCK."""
    braze_lot(build_order_id)
    record_helium_leak_test(build_order_id, leak_rate)
    charge_lot(build_order_id, charge_grams)
    record_run_test(
        build_order_id,
        test_cell_id,
        window_start_utc,
        window_end_utc,
        measured_capacity_btuh,
        measured_power_w,
        measured_ambient_c,
    )
    release_lot_to_stock(build_order_id)
    return read_build_order(build_order_id)


def setup_platform_with_released_lot(
    quantity_units: int = 20, **program_overrides
) -> dict:
    """A2L HIGH platform with one lot fully released to finished stock.

    Returns {program, platform, test_cell, build_order}.
    """
    program = create_a2l_program(**program_overrides)
    platform = create_released_high_a2l_platform(program["id"])
    test_cell = create_test_cell("CELL-1")
    build_order = create_build_order(platform["id"], quantity_units=quantity_units)
    walk_lot_to_released_to_stock(build_order["id"], test_cell["id"])
    return {
        "program": program,
        "platform": read_platform(platform["id"]),
        "test_cell": test_cell,
        "build_order": read_build_order(build_order["id"]),
    }


# ---------------------------------------------------------------------------
# Tier 3: supply, order, and allocation chains
# ---------------------------------------------------------------------------


def create_compressor_supply(**overrides) -> dict:
    return _data(
        api_client.create_component_supply(compressor_supply_payload(**overrides), SUPPLY)
    )


def create_control_board_supply(**overrides) -> dict:
    return _data(
        api_client.create_component_supply(
            control_board_supply_payload(**overrides), SUPPLY
        )
    )


def create_supply_pair(
    compressor_part_number: str = "CMP-5T-A2L",
    control_board_part_number: str = "CTL-9X",
    compressor_units: int = 100,
    board_units: int = 100,
    supply_month: str = "2026-11",
    compressor_lot: str = "LOT-CMP-51",
    board_lot: str = "LOT-CTL-77",
    allocation_policy: str = "PRIORITY_WATERFALL",
) -> tuple:
    """One compressor pool and one control-board pool for the same month.

    The compressor pool is created first so that it is the primary compressor
    supply row (earliest created_at). Returns (compressor, control_board).
    """
    compressor = create_compressor_supply(
        part_number=compressor_part_number,
        supplier_lot_code=compressor_lot,
        supply_month=supply_month,
        total_allocatable_units=compressor_units,
        allocation_policy=allocation_policy,
    )
    control_board = create_control_board_supply(
        part_number=control_board_part_number,
        supplier_lot_code=board_lot,
        supply_month=supply_month,
        total_allocatable_units=board_units,
        allocation_policy=allocation_policy,
    )
    return compressor, control_board


def place_order(
    platform_id: str,
    requested_units: int = 30,
    priority_score: int = 70,
    distributor_code: str = "DIST-SE-1",
    region_code: str = "SOUTHEAST",
    requested_delivery_month: str = "2026-11",
    rep_id: str = DISTRIBUTOR_REP_1_ID,
) -> dict:
    return _data(
        api_client.create_distributor_order(
            create_distributor_order_payload(
                platform_id,
                distributor_code=distributor_code,
                region_code=region_code,
                requested_units=requested_units,
                priority_score=priority_score,
                requested_delivery_month=requested_delivery_month,
            ),
            make_headers(rep_id, "DistributorRep"),
        )
    )


def allocate_order(order_id: str, primary_compressor_supply_id: str) -> dict:
    """Draw kits, carrying the primary compressor pool's current version."""
    version = read_supply(primary_compressor_supply_id)["version"]
    return _data(
        api_client.allocate_distributor_order(
            order_id, allocate_payload(version), SUPPLY
        )
    )


def stage_order(order_id: str) -> dict:
    return _data(api_client.stage_distributor_order(order_id, PLANNER))


def ship_order(order_id: str, shipped_units: int) -> dict:
    return _data(
        api_client.ship_distributor_order(order_id, ship_payload(shipped_units), PLANNER)
    )


def setup_certified_platform_with_pools(
    compressor_units: int = 100,
    board_units: int = 100,
    supply_month: str = "2026-11",
    **program_overrides,
) -> dict:
    """SOUTHEAST-certified HIGH/A2L platform plus a matched pool pair.

    Returns {standard, program, platform, compressor, control_board}.
    """
    scenario = setup_certified_high_a2l_platform(**program_overrides)
    compressor, control_board = create_supply_pair(
        compressor_part_number=scenario["platform"]["compressor_part_number"],
        control_board_part_number=scenario["platform"]["control_board_part_number"],
        compressor_units=compressor_units,
        board_units=board_units,
        supply_month=supply_month,
    )
    scenario["compressor"] = compressor
    scenario["control_board"] = control_board
    return scenario


def setup_allocated_order(
    requested_units: int = 30,
    compressor_units: int = 50,
    board_units: int = 50,
    priority_score: int = 70,
    **program_overrides,
) -> dict:
    """Certified platform + pools + one order drawn against them.

    Returns {standard, program, platform, compressor, control_board, order}.
    """
    scenario = setup_certified_platform_with_pools(
        compressor_units=compressor_units,
        board_units=board_units,
        **program_overrides,
    )
    order = place_order(
        scenario["platform"]["id"],
        requested_units=requested_units,
        priority_score=priority_score,
    )
    allocate_order(order["id"], scenario["compressor"]["id"])
    scenario["order"] = read_order(order["id"])
    return scenario


def setup_staged_order(
    requested_units: int = 40, pool_units: int = 40, **program_overrides
) -> dict:
    """Fully allocated order advanced to STAGED."""
    scenario = setup_allocated_order(
        requested_units=requested_units,
        compressor_units=pool_units,
        board_units=pool_units,
        **program_overrides,
    )
    stage_order(scenario["order"]["id"])
    scenario["order"] = read_order(scenario["order"]["id"])
    return scenario


# ---------------------------------------------------------------------------
# Tier 3: warehouse and reservation chains
# ---------------------------------------------------------------------------


def create_reservation(
    warehouse_id: str,
    build_order_id: str,
    start_date: str = "2026-11-02",
    end_date: str = "2026-11-20",
    pallet_units: int = 10,
) -> dict:
    return _data(
        api_client.create_warehouse_reservation(
            create_warehouse_reservation_payload(
                warehouse_id, build_order_id, start_date, end_date, pallet_units
            ),
            PLANNER,
        )
    )


def release_reservation(
    reservation_id: str, release_reason: str = "Pre-season plan rebalanced"
) -> dict:
    return _data(
        api_client.release_warehouse_reservation(
            reservation_id, release_reservation_payload(release_reason), PLANNER
        )
    )


def setup_preseason_lot_with_reservation(
    pallet_capacity: int = 50,
    quantity_units: int = 24,
    pallet_units: int = 20,
    scheduled_start_utc: str = "2026-09-10T08:00:00Z",
    start_date: str = "2026-09-01",
    end_date: str = "2026-12-01",
    program_kind: str = "a1",
    **program_overrides,
) -> dict:
    """Warehouse + released platform + pre-season lot holding pallet space.

    Returns {program, platform, warehouse, build_order, reservation}.
    """
    warehouse = create_warehouse("WH-1", pallet_capacity)
    if program_kind == "a1":
        program = create_a1_program(**program_overrides)
        platform = create_released_standard_a1_platform(program["id"])
    else:
        program = create_a2l_program(**program_overrides)
        platform = create_released_high_a2l_platform(program["id"])
    build_order = create_build_order(
        platform["id"],
        quantity_units=quantity_units,
        scheduled_start_utc=scheduled_start_utc,
        is_preseason=True,
    )
    reservation = create_reservation(
        warehouse["id"], build_order["id"], start_date, end_date, pallet_units
    )
    return {
        "program": read_program(program["id"]),
        "platform": platform,
        "warehouse": read_warehouse(warehouse["id"]),
        "build_order": read_build_order(build_order["id"]),
        "reservation": reservation,
    }


# ---------------------------------------------------------------------------
# Tier 4: accumulation and threshold targeting
# ---------------------------------------------------------------------------


def file_claim(
    platform_id: str,
    claim_cost_cents: int,
    failure_code: str = "COMPRESSOR_FAILURE",
    component_type: str = "COMPRESSOR",
    supplier_lot_code: str = "LOT-CMP-51",
    analyst_id: str = WARRANTY_ANALYST_ID,
) -> dict:
    return _data(
        api_client.create_warranty_claim(
            create_warranty_claim_payload(
                platform_id,
                failure_code=failure_code,
                claim_cost_cents=claim_cost_cents,
                component_type=component_type,
                supplier_lot_code=supplier_lot_code,
            ),
            make_headers(analyst_id, "WarrantyAnalyst"),
        )
    )


def file_compressor_claims(
    platform_id: str,
    costs: list,
    supplier_lot_code: str = "LOT-CMP-51",
    analyst_id: str = WARRANTY_ANALYST_ID,
) -> list:
    """File one compressor claim per cost, in order. Returns the claim rows."""
    return [
        file_claim(
            platform_id,
            cost,
            failure_code="COMPRESSOR_FAILURE",
            component_type="COMPRESSOR",
            supplier_lot_code=supplier_lot_code,
            analyst_id=analyst_id,
        )
        for cost in costs
    ]


def setup_platform_two_claims_below_threshold(
    quantity_units: int = 60,
    compressor_units: int = 100,
    board_units: int = 100,
    supplier_lot_code: str = "LOT-CMP-51",
    **program_overrides,
) -> dict:
    """A HIGH/A2L platform with one released lot, matched pools, and exactly
    two open compressor claims — one short of the three-claim gate.

    Returns {program, platform, test_cell, build_order, compressor,
    control_board, claims}.
    """
    scenario = setup_platform_with_released_lot(
        quantity_units=quantity_units, **program_overrides
    )
    compressor, control_board = create_supply_pair(
        compressor_part_number=scenario["platform"]["compressor_part_number"],
        control_board_part_number=scenario["platform"]["control_board_part_number"],
        compressor_units=compressor_units,
        board_units=board_units,
        compressor_lot=supplier_lot_code,
    )
    claims = file_compressor_claims(
        scenario["platform"]["id"], [41500, 39900], supplier_lot_code=supplier_lot_code
    )
    scenario["compressor"] = compressor
    scenario["control_board"] = control_board
    scenario["claims"] = claims
    scenario["platform"] = read_platform(scenario["platform"]["id"])
    return scenario


def open_corrective_action_via_third_claim(
    platform_id: str,
    claim_cost_cents: int = 40200,
    supplier_lot_code: str = "LOT-CMP-51",
) -> dict:
    """File the claim that crosses the corrective-action threshold."""
    return file_claim(
        platform_id,
        claim_cost_cents,
        failure_code="COMPRESSOR_FAILURE",
        component_type="COMPRESSOR",
        supplier_lot_code=supplier_lot_code,
    )


def find_open_corrective_action(component_supply_id: str) -> dict:
    """Read back the single OPEN corrective action governing a pool."""
    response = api_client.list_supplier_corrective_actions(
        SUPPLY, params={"component_supply_id": component_supply_id, "status": "OPEN"}
    )
    rows = _data(response)
    assert rows, f"expected an OPEN corrective action for pool {component_supply_id}"
    return rows[0]


def close_corrective_action(
    action_id: str,
    resolution: str = "EFFECTIVE",
    effectiveness_note: str = None,
    engineer_id: str = RELIABILITY_ENGINEER_2_ID,
) -> dict:
    return _data(
        api_client.close_supplier_corrective_action(
            action_id,
            close_corrective_action_payload(resolution, effectiveness_note),
            make_headers(engineer_id, "ReliabilityEngineer"),
        )
    )


# ---------------------------------------------------------------------------
# Tier 5: composite scenarios for the harder assertions
# ---------------------------------------------------------------------------


def setup_two_brazed_high_a2l_lots(
    quantity_units: int = 20, **program_overrides
) -> dict:
    """Two independent lots of the same HIGH/A2L platform, both at BRAZED.

    Returns {program, platform, build_order_1, build_order_2}.
    """
    program = create_a2l_program(**program_overrides)
    platform = create_released_high_a2l_platform(program["id"])
    first = create_build_order(platform["id"], quantity_units=quantity_units)
    second = create_build_order(platform["id"], quantity_units=quantity_units)
    braze_lot(first["id"])
    braze_lot(second["id"])
    return {
        "program": program,
        "platform": platform,
        "build_order_1": read_build_order(first["id"]),
        "build_order_2": read_build_order(second["id"]),
    }


def setup_lot_after_two_failed_leak_cycles(
    quantity_units: int = 20,
    first_decay_kpa: float = 3.50,
    second_decay_kpa: float = 3.20,
    hold_minutes: int = 30,
    **program_overrides,
) -> dict:
    """A HIGH/A2L lot that has burned both units of its repair budget and is
    back at BRAZED awaiting a third leak test.

    Returns {program, platform, build_order}.
    """
    scenario = setup_brazed_high_a2l_lot(quantity_units, **program_overrides)
    build_order_id = scenario["build_order"]["id"]
    record_pressure_decay_leak_test(build_order_id, first_decay_kpa, hold_minutes)
    braze_lot(build_order_id)
    record_pressure_decay_leak_test(build_order_id, second_decay_kpa, hold_minutes)
    braze_lot(build_order_id)
    scenario["build_order"] = read_build_order(build_order_id)
    return scenario


def setup_platform_returned_to_draft_and_revised(
    revised_max_charge_grams: int = 1650, **program_overrides
) -> dict:
    """A2L HIGH platform submitted once, returned to draft, then edited.

    Returns {program, platform}. The platform is back in DRAFT with
    revision_round already at 1 and last_revision_notes recorded.
    """
    program = create_a2l_program(**program_overrides)
    platform = create_high_a2l_draft_platform(program["id"])
    submit_platform(platform["id"])
    return_platform_to_draft(platform["id"])
    _data(
        api_client.update_product_platform(
            platform["id"], {"max_charge_grams": revised_max_charge_grams}, DESIGN
        )
    )
    return {"program": program, "platform": read_platform(platform["id"])}


def setup_sell_through_cascade_scenario(
    manufacture_cutoff_utc: str = "2026-10-01T00:00:00Z",
    sell_through_deadline_utc: str = "2027-04-01T00:00:00Z",
    clock_after_cutoff: str = "2026-10-02T00:00:00Z",
    pallet_capacity: int = 50,
    quantity_units: int = 24,
    pallet_units: int = 20,
) -> dict:
    """An A1 program past its manufacture cutoff, holding a released platform,
    a pre-season lot, and that lot's live pallet space.

    Returns {program, platform, warehouse, build_order, reservation}.
    """
    scenario = setup_preseason_lot_with_reservation(
        pallet_capacity=pallet_capacity,
        quantity_units=quantity_units,
        pallet_units=pallet_units,
        scheduled_start_utc="2026-09-10T08:00:00Z",
        start_date="2026-09-01",
        end_date="2026-12-01",
        program_kind="a1",
        manufacture_cutoff_utc=manufacture_cutoff_utc,
        sell_through_deadline_utc=sell_through_deadline_utc,
    )
    set_clock(clock_after_cutoff)
    return scenario


def setup_warranty_capa_cascade_scenario(
    quantity_units: int = 20,
    compressor_units: int = 100,
    board_units: int = 100,
    order_units: int = 40,
    priority_score: int = 70,
) -> dict:
    """A certified HIGH/A2L platform with a released lot, matched pools, one
    allocated SOUTHEAST order, and two open compressor claims.

    Returns {standard, program, platform, test_cell, build_order, compressor,
    control_board, order, claims}.
    """
    standard = create_southeast_standard()
    program = create_a2l_program()
    platform = create_released_high_a2l_platform(program["id"])
    certify_platform_for_region(platform["id"], region_code="SOUTHEAST")
    test_cell = create_test_cell("CELL-1")
    build_order = create_build_order(platform["id"], quantity_units=quantity_units)
    walk_lot_to_released_to_stock(build_order["id"], test_cell["id"])
    compressor, control_board = create_supply_pair(
        compressor_part_number="CMP-5T-A2L",
        control_board_part_number="CTL-9X",
        compressor_units=compressor_units,
        board_units=board_units,
    )
    order = place_order(
        platform["id"],
        requested_units=order_units,
        priority_score=priority_score,
        distributor_code="DIST-SE-1",
    )
    allocate_order(order["id"], compressor["id"])
    claims = file_compressor_claims(platform["id"], [41500, 39900])
    return {
        "standard": standard,
        "program": program,
        "platform": read_platform(platform["id"]),
        "test_cell": test_cell,
        "build_order": read_build_order(build_order["id"]),
        "compressor": read_supply(compressor["id"]),
        "control_board": read_supply(control_board["id"]),
        "order": read_order(order["id"]),
        "claims": claims,
    }


def setup_two_regions_one_certified(
    compressor_units: int = 100, board_units: int = 100
) -> dict:
    """SOUTHEAST and flammable-prohibiting NORTHEAST standards, a HIGH/A2L
    platform certified for SOUTHEAST only, and a matched pool pair.

    Returns {southeast, northeast, program, platform, compressor,
    control_board}.
    """
    southeast = create_southeast_standard()
    northeast = create_northeast_standard()
    program = create_a2l_program()
    platform = create_released_high_a2l_platform(program["id"])
    certify_platform_for_region(platform["id"], region_code="SOUTHEAST")
    compressor, control_board = create_supply_pair(
        compressor_part_number="CMP-5T-A2L",
        control_board_part_number="CTL-9X",
        compressor_units=compressor_units,
        board_units=board_units,
    )
    return {
        "southeast": southeast,
        "northeast": northeast,
        "program": program,
        "platform": read_platform(platform["id"]),
        "compressor": compressor,
        "control_board": control_board,
    }


def setup_two_preseason_reservations_for_cost(
    pallet_capacity: int = 50,
    quantity_units: int = 10,
    first_window: tuple = ("2026-11-02", "2026-11-12"),
    second_window: tuple = ("2026-11-12", "2026-11-22"),
    pallet_units: int = 5,
) -> dict:
    """One warehouse holding two adjacent pre-season reservations.

    Returns {program, platform, warehouse, build_order_1, build_order_2,
    reservation_1, reservation_2}.
    """
    warehouse = create_warehouse("WH-1", pallet_capacity)
    program = create_a1_program()
    platform = create_released_standard_a1_platform(program["id"])
    first_lot = create_build_order(
        platform["id"],
        quantity_units=quantity_units,
        scheduled_start_utc="2026-11-02T08:00:00Z",
        is_preseason=True,
    )
    second_lot = create_build_order(
        platform["id"],
        quantity_units=quantity_units,
        scheduled_start_utc="2026-11-12T08:00:00Z",
        is_preseason=True,
    )
    reservation_1 = create_reservation(
        warehouse["id"], first_lot["id"], first_window[0], first_window[1], pallet_units
    )
    reservation_2 = create_reservation(
        warehouse["id"], second_lot["id"], second_window[0], second_window[1], pallet_units
    )
    return {
        "program": program,
        "platform": platform,
        "warehouse": read_warehouse(warehouse["id"]),
        "build_order_1": first_lot,
        "build_order_2": second_lot,
        "reservation_1": reservation_1,
        "reservation_2": reservation_2,
    }


def setup_test_cell_with_one_run_test(
    quantity_units: int = 20,
    cooldown_minutes: int = 30,
    first_window: tuple = ("2026-08-05T08:00:00Z", "2026-08-05T09:00:00Z"),
    second_lot_leak_rate: float = 1.10,
    second_lot_charge_grams: int = 1750,
) -> dict:
    """One test cell that already holds a run test, plus a second CHARGED lot
    waiting for the cell.

    Returns {program, platform, test_cell, build_order_1, build_order_2,
    run_test_1}.
    """
    program = create_a2l_program()
    platform = create_released_high_a2l_platform(program["id"])
    test_cell = create_test_cell("CELL-1", cooldown_minutes)
    first_lot = create_build_order(platform["id"], quantity_units=quantity_units)
    braze_lot(first_lot["id"])
    record_helium_leak_test(first_lot["id"], 1.20)
    charge_lot(first_lot["id"], 1750)
    run_test_1 = record_run_test(
        first_lot["id"], test_cell["id"], first_window[0], first_window[1]
    )
    second_lot = create_build_order(platform["id"], quantity_units=quantity_units)
    braze_lot(second_lot["id"])
    record_helium_leak_test(second_lot["id"], second_lot_leak_rate)
    charge_lot(second_lot["id"], second_lot_charge_grams)
    return {
        "program": program,
        "platform": platform,
        "test_cell": test_cell,
        "build_order_1": read_build_order(first_lot["id"]),
        "build_order_2": read_build_order(second_lot["id"]),
        "run_test_1": run_test_1,
    }


def setup_warehouse_with_one_large_reservation(
    pallet_capacity: int = 50,
    first_pallets: int = 30,
    first_window: tuple = ("2026-11-02", "2026-11-12"),
    first_lot_units: int = 60,
    second_lot_units: int = 50,
) -> dict:
    """A warehouse already carrying one reservation, plus a second pre-season
    lot that still needs space.

    Returns {program, platform, warehouse, build_order_1, build_order_2,
    reservation_1}.
    """
    warehouse = create_warehouse("WH-1", pallet_capacity)
    program = create_a1_program()
    platform = create_released_standard_a1_platform(program["id"])
    first_lot = create_build_order(
        platform["id"],
        quantity_units=first_lot_units,
        scheduled_start_utc="2026-11-02T08:00:00Z",
        is_preseason=True,
    )
    second_lot = create_build_order(
        platform["id"],
        quantity_units=second_lot_units,
        scheduled_start_utc="2026-11-10T08:00:00Z",
        is_preseason=True,
    )
    reservation_1 = create_reservation(
        warehouse["id"], first_lot["id"], first_window[0], first_window[1], first_pallets
    )
    return {
        "program": program,
        "platform": platform,
        "warehouse": read_warehouse(warehouse["id"]),
        "build_order_1": first_lot,
        "build_order_2": second_lot,
        "reservation_1": reservation_1,
    }


def setup_preseason_lot_with_released_reservation(
    pallet_capacity: int = 50,
    quantity_units: int = 10,
    pallet_units: int = 10,
    start_date: str = "2026-08-01",
    end_date: str = "2026-09-01",
    release_reason: str = "Pre-season plan rebalanced to a different site",
) -> dict:
    """A pre-season HIGH/A2L lot walked to RUN_PASSED whose pallet space has
    already been given back.

    Returns {program, platform, warehouse, test_cell, build_order,
    reservation}.
    """
    warehouse = create_warehouse("WH-1", pallet_capacity)
    program = create_a2l_program()
    platform = create_released_high_a2l_platform(program["id"])
    test_cell = create_test_cell("CELL-1")
    build_order = create_build_order(
        platform["id"], quantity_units=quantity_units, is_preseason=True
    )
    reservation = create_reservation(
        warehouse["id"], build_order["id"], start_date, end_date, pallet_units
    )
    release_reservation(reservation["id"], release_reason)
    braze_lot(build_order["id"])
    record_helium_leak_test(build_order["id"], 1.20)
    charge_lot(build_order["id"], 1750)
    record_run_test(build_order["id"], test_cell["id"])
    return {
        "program": program,
        "platform": platform,
        "warehouse": read_warehouse(warehouse["id"]),
        "test_cell": test_cell,
        "build_order": read_build_order(build_order["id"]),
        "reservation": read_reservation(reservation["id"]),
    }


def setup_three_standard_a1_lots_through_run_test(
    quantities: tuple = (12, 8, 14),
    leak_rates: tuple = (1.10, 1.30, 1.40),
    charge_grams: int = 1600,
    windows: tuple = (
        ("2026-08-05T08:00:00Z", "2026-08-05T09:00:00Z"),
        ("2026-08-05T09:30:00Z", "2026-08-05T10:30:00Z"),
        ("2026-08-05T11:00:00Z", "2026-08-05T12:00:00Z"),
    ),
    release_first: bool = True,
) -> dict:
    """Three STANDARD/A1 lots each walked to RUN_PASSED in one cell, with the
    first optionally already released to finished stock.

    Returns {program, platform, test_cell, build_orders}.
    """
    program = create_a1_program()
    platform = create_released_standard_a1_platform(program["id"])
    test_cell = create_test_cell("CELL-1")
    build_orders = []
    for index, quantity in enumerate(quantities):
        lot = create_build_order(platform["id"], quantity_units=quantity)
        braze_lot(lot["id"])
        record_helium_leak_test(lot["id"], leak_rates[index])
        charge_lot(lot["id"], charge_grams)
        record_run_test(
            lot["id"],
            test_cell["id"],
            windows[index][0],
            windows[index][1],
            measured_capacity_btuh=24000,
            measured_power_w=2020,
            measured_ambient_c=35.0,
        )
        build_orders.append(lot)
    if release_first:
        release_lot_to_stock(build_orders[0]["id"])
    return {
        "program": program,
        "platform": read_platform(platform["id"]),
        "test_cell": test_cell,
        "build_orders": [read_build_order(lot["id"]) for lot in build_orders],
    }


def setup_two_competing_orders(
    compressor_units: int = 100,
    board_units: int = 100,
    first_units: int = 80,
    first_priority: int = 90,
    second_units: int = 60,
    second_priority: int = 40,
) -> dict:
    """Two unallocated SOUTHEAST orders competing for one pool pair.

    Returns {standard, program, platform, compressor, control_board, order_a,
    order_b}.
    """
    scenario = setup_certified_platform_with_pools(
        compressor_units=compressor_units, board_units=board_units
    )
    order_a = place_order(
        scenario["platform"]["id"],
        requested_units=first_units,
        priority_score=first_priority,
        distributor_code="DIST-A",
        rep_id=DISTRIBUTOR_REP_1_ID,
    )
    order_b = place_order(
        scenario["platform"]["id"],
        requested_units=second_units,
        priority_score=second_priority,
        distributor_code="DIST-B",
        rep_id=DISTRIBUTOR_REP_2_ID,
    )
    scenario["order_a"] = order_a
    scenario["order_b"] = order_b
    return scenario


def cancel_lot(build_order_id: str, reason: str = "Pre-season plan trimmed") -> dict:
    return _data(
        api_client.cancel_build_order(
            build_order_id, cancel_build_order_payload(reason), PLANNER
        )
    )
