"""Composite setup helpers.

Every test starts against an empty database, so all preconditions are built from
scratch here through PRD-declared endpoints only.  The module is organised in two
layers:

* single-step helpers (``register_customer``, ``receive_pallet``, ``book_load``,
  ``capture_cycle_log`` …) that wrap exactly one endpoint call and return the
  resulting resource; and
* composite builders (``setup_facility``, ``setup_running_cycle``,
  ``setup_dispositioned_clean_cycle``, ``setup_inspected_load`` …) that walk a
  whole preamble and return a dictionary of everything they made.

All helpers read their responses through the lenient success reader, so a broken
preamble surfaces as a setup failure rather than as a confusing assertion deep
inside a test.
"""

from typing import Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    adjudicate_deviation_payload,
    clock_payload,
    create_cold_room_payload,
    create_contract_payload,
    create_customer_payload,
    create_cycle_load_payload,
    create_lot_payload,
    create_product_family_payload,
    create_qualification_payload,
    create_vessel_cycle_payload,
    create_vessel_payload,
    cycle_log_payload,
    dock_inspection_payload,
    load_inspection_payload,
    patch_vessel_payload,
    qualification_decision_payload,
    release_decision_payload,
    ship_payload,
    supersede_qualification_payload,
    terminate_cycle_payload,
    validation_run_payload,
    waive_payload,
)
from .test_users import TEST_USERS, make_customer_headers

ADMIN = TEST_USERS["facility_admin_headers"]
SCHEDULER = TEST_USERS["plant_scheduler_headers"]
OPERATOR = TEST_USERS["plant_operator_headers"]
QUALITY = TEST_USERS["quality_manager_headers"]
QUALITY_SECOND = TEST_USERS["quality_manager_second_headers"]
QUALITY_THIRD = TEST_USERS["quality_manager_third_headers"]

CLOCK_AUG03 = TEST_DEFAULTS["CLOCK_AUG03"]


# --------------------------------------------------------------------------- #
# logical clock and the end-of-day sweep
# --------------------------------------------------------------------------- #
def set_clock(to_iso8601: str, headers: Optional[dict] = None) -> str:
    """Move the logical clock and return the ``current_utc`` it adopted."""
    data = get_success_data(
        api_client.set_clock(clock_payload(to_iso8601), headers or ADMIN)
    )
    return data.get("current_utc")


def run_day_close(headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.run_day_close(headers or ADMIN))


# --------------------------------------------------------------------------- #
# customers
# --------------------------------------------------------------------------- #
def register_customer(code: str = TEST_DEFAULTS["CUSTOMER_CODE"], **overrides) -> dict:
    return get_success_data(
        api_client.create_customer(
            create_customer_payload(code=code, **overrides), ADMIN
        )
    )


def read_customer(customer_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_customer(customer_id, headers or ADMIN))


# --------------------------------------------------------------------------- #
# product families, vessels and cold rooms
# --------------------------------------------------------------------------- #
def define_family(
    family_code: str = TEST_DEFAULTS["FAMILY_CODE"], **overrides
) -> dict:
    return get_success_data(
        api_client.create_product_family(
            create_product_family_payload(family_code=family_code, **overrides), ADMIN
        )
    )


def read_family(family_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_product_family(family_id, headers or ADMIN)
    )


def commission_vessel(
    vessel_code: str = TEST_DEFAULTS["VESSEL_CODE"], **overrides
) -> dict:
    return get_success_data(
        api_client.create_vessel(
            create_vessel_payload(vessel_code=vessel_code, **overrides), ADMIN
        )
    )


def commission_second_vessel(vessel_code: str = "HPP-2", **overrides) -> dict:
    """The six-basket machine: ramp 5.0 MPa/s, 15 s of decompression."""
    defaults = {
        "chamber_volume_liters": 525,
        "max_pressure_mpa": 600.0,
        "pump_ramp_rate_mpa_per_sec": 5.0,
        "decompression_seconds": 15,
        "basket_count": 6,
        "hourly_operating_cost_cents": 120000,
    }
    defaults.update(overrides)
    return commission_vessel(vessel_code=vessel_code, **defaults)


def commission_third_vessel(vessel_code: str = "HPP-3", **overrides) -> dict:
    """The five-basket machine: ramp 6.0 MPa/s, 12 s of decompression."""
    defaults = {
        "chamber_volume_liters": 440,
        "max_pressure_mpa": 600.0,
        "pump_ramp_rate_mpa_per_sec": 6.0,
        "decompression_seconds": 12,
        "basket_count": 5,
        "hourly_operating_cost_cents": 100000,
    }
    defaults.update(overrides)
    return commission_vessel(vessel_code=vessel_code, **defaults)


def patch_vessel_status(vessel_id: str, status: str) -> dict:
    return get_success_data(
        api_client.patch_vessel(vessel_id, patch_vessel_payload(status), ADMIN)
    )


def read_vessel(vessel_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_vessel(vessel_id, headers or ADMIN))


def define_cold_room(room_code: str = TEST_DEFAULTS["ROOM_CODE"], **overrides) -> dict:
    return get_success_data(
        api_client.create_cold_room(
            create_cold_room_payload(room_code=room_code, **overrides), ADMIN
        )
    )


def read_cold_room(room_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_cold_room(room_id, headers or ADMIN))


# --------------------------------------------------------------------------- #
# qualifications
# --------------------------------------------------------------------------- #
def open_qualification(
    customer_id: str, product_family_id: str, **overrides
) -> dict:
    return get_success_data(
        api_client.create_qualification(
            create_qualification_payload(customer_id, product_family_id, **overrides),
            make_customer_headers(customer_id),
        )
    )


def submit_qualification(qualification_id: str, customer_id: str) -> dict:
    return get_success_data(
        api_client.submit_qualification(
            qualification_id, make_customer_headers(customer_id)
        )
    )


def append_validation_run(
    qualification_id: str, headers: Optional[dict] = None, **overrides
) -> dict:
    return get_success_data(
        api_client.append_validation_run(
            qualification_id, validation_run_payload(**overrides), headers or QUALITY
        )
    )


def append_acceptable_runs(
    qualification_id: str, how_many: int = 2, headers: Optional[dict] = None
) -> List[dict]:
    """Append ``how_many`` runs that satisfy all four ACCEPTABLE conditions."""
    return [
        append_validation_run(qualification_id, headers=headers)
        for _ in range(how_many)
    ]


def decide_qualification(
    qualification_id: str,
    outcome: str = "QUALIFY",
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.decide_qualification(
            qualification_id,
            qualification_decision_payload(outcome, **overrides),
            headers or QUALITY,
        )
    )


def read_qualification(qualification_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_qualification(qualification_id, headers or QUALITY)
    )


def list_qualifications(headers: Optional[dict] = None, **params) -> List[dict]:
    return get_success_data(
        api_client.list_qualifications(headers or QUALITY, params or None)
    )


def list_validation_runs(
    qualification_id: str, headers: Optional[dict] = None, **params
) -> List[dict]:
    response = api_client.list_validation_runs(
        qualification_id, headers or QUALITY, params or None
    )
    return get_success_data(response)


def supersede_qualification(
    qualification_id: str, customer_id: str, expected_version: int, **overrides
) -> dict:
    return get_success_data(
        api_client.supersede_qualification(
            qualification_id,
            supersede_qualification_payload(expected_version, **overrides),
            make_customer_headers(customer_id),
        )
    )


def qualify_recipe(
    customer_id: str, product_family_id: str, qm_headers: Optional[dict] = None, **overrides
) -> dict:
    """Open, submit, validate twice and QUALIFY one process recipe.

    The default recipe is 600 MPa for 180 s in a POUCH with a 660 MPa burst
    pressure and a 90 micron film, which scores 100.00 and clears all four gates.
    """
    qualification = open_qualification(customer_id, product_family_id, **overrides)
    submit_qualification(qualification["id"], customer_id)
    append_acceptable_runs(
        qualification["id"],
        how_many=2,
        headers=qm_headers,
    )
    decide_qualification(qualification["id"], "QUALIFY", headers=qm_headers)
    return read_qualification(qualification["id"])


# --------------------------------------------------------------------------- #
# capacity contracts
# --------------------------------------------------------------------------- #
def write_contract(customer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_contract(
            create_contract_payload(customer_id, **overrides), ADMIN
        )
    )


def activate_contract(contract_id: str) -> dict:
    return get_success_data(api_client.activate_contract(contract_id, ADMIN))


def close_contract(contract_id: str) -> dict:
    return get_success_data(api_client.close_contract(contract_id, ADMIN))


def read_contract(contract_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_contract(contract_id, headers or ADMIN))


def open_active_contract(customer_id: str, **overrides) -> dict:
    """A contract written and then activated, so its slots are bookable."""
    contract = write_contract(customer_id, **overrides)
    activate_contract(contract["id"])
    return read_contract(contract["id"])


# --------------------------------------------------------------------------- #
# lots (pallets)
# --------------------------------------------------------------------------- #
def receive_pallet(
    customer_id: str,
    qualification_id: str,
    cold_room_id: str,
    pallet_ref: str = "PAL-001",
    **overrides,
) -> dict:
    return get_success_data(
        api_client.create_lot(
            create_lot_payload(
                customer_id,
                qualification_id,
                cold_room_id,
                pallet_ref=pallet_ref,
                **overrides,
            ),
            OPERATOR,
        )
    )


def inspect_at_dock(
    lot_id: str, outcome: str = "ACCEPT", pulp_temp_c: float = 3.2
) -> dict:
    return get_success_data(
        api_client.inspect_lot(
            lot_id, dock_inspection_payload(outcome, pulp_temp_c), OPERATOR
        )
    )


def store_pallet(
    customer_id: str,
    qualification_id: str,
    cold_room_id: str,
    pallet_ref: str = "PAL-001",
    pulp_temp_c: float = 3.2,
    **overrides,
) -> dict:
    """Receive a pallet and accept it at dock inspection, so it lands in cold storage."""
    lot = receive_pallet(
        customer_id, qualification_id, cold_room_id, pallet_ref=pallet_ref, **overrides
    )
    inspect_at_dock(lot["id"], "ACCEPT", pulp_temp_c)
    return read_lot(lot["id"])


def read_lot(lot_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_lot(lot_id, headers or QUALITY))


def list_lots(headers: Optional[dict] = None, **params) -> List[dict]:
    return get_success_data(
        api_client.list_lots(headers or QUALITY, params or None)
    )


def record_release_decision(
    lot_id: str,
    outcome: str,
    headers: Optional[dict] = None,
    expected_lot_version: Optional[int] = None,
    hold_reason: Optional[str] = None,
) -> dict:
    """Record a release decision, reading the pallet's current version if needed."""
    version = (
        expected_lot_version
        if expected_lot_version is not None
        else read_lot(lot_id)["version"]
    )
    return get_success_data(
        api_client.record_release_decision(
            lot_id,
            release_decision_payload(outcome, version, hold_reason=hold_reason),
            headers or QUALITY_SECOND,
        )
    )


def ship_pallet(lot_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.ship_lot(lot_id, ship_payload(**overrides), OPERATOR)
    )


# --------------------------------------------------------------------------- #
# vessel cycles, loads and CCP records
# --------------------------------------------------------------------------- #
def schedule_cycle(vessel_id: str, product_family_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_vessel_cycle(
            create_vessel_cycle_payload(vessel_id, product_family_id, **overrides),
            SCHEDULER,
        )
    )


def read_cycle(cycle_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_vessel_cycle(cycle_id, headers or SCHEDULER)
    )


def cycle_version(cycle_id: str) -> int:
    """The cycle's current ``version``, for the mandatory ``expected_cycle_version``."""
    return read_cycle(cycle_id)["version"]


def list_cycles(headers: Optional[dict] = None, **params) -> List[dict]:
    return get_success_data(
        api_client.list_vessel_cycles(headers or SCHEDULER, params or None)
    )


def book_load(
    cycle_id: str,
    lot_id: str,
    contract_id: str,
    baskets_used: int = 2,
    units_loaded: int = 1000,
    expected_cycle_version: Optional[int] = None,
) -> dict:
    """Book a pallet onto a cycle, reading the cycle's current version if needed."""
    version = (
        expected_cycle_version
        if expected_cycle_version is not None
        else cycle_version(cycle_id)
    )
    return get_success_data(
        api_client.create_cycle_load(
            cycle_id,
            create_cycle_load_payload(
                lot_id, contract_id, baskets_used, units_loaded, version
            ),
            SCHEDULER,
        )
    )


def start_cycle(cycle_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.start_cycle(cycle_id, headers or OPERATOR))


def capture_cycle_log(
    cycle_id: str, headers: Optional[dict] = None, **overrides
) -> dict:
    return get_success_data(
        api_client.create_cycle_log(
            cycle_id, cycle_log_payload(**overrides), headers or OPERATOR
        )
    )


def list_cycle_logs(cycle_id: str, headers: Optional[dict] = None, **params) -> List[dict]:
    return get_success_data(
        api_client.list_cycle_logs(cycle_id, headers or OPERATOR, params or None)
    )


def terminate_cycle(
    cycle_id: str, reason: str = "customer pulled the shipment", headers: Optional[dict] = None
) -> dict:
    return get_success_data(
        api_client.terminate_cycle(
            cycle_id, terminate_cycle_payload(reason), headers or SCHEDULER
        )
    )


def disposition_cycle(cycle_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.disposition_cycle(cycle_id, headers or QUALITY)
    )


# --------------------------------------------------------------------------- #
# cycle loads
# --------------------------------------------------------------------------- #
def read_load(load_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(api_client.get_cycle_load(load_id, headers or QUALITY))


def list_loads(headers: Optional[dict] = None, **params) -> List[dict]:
    return get_success_data(
        api_client.list_cycle_loads(headers or QUALITY, params or None)
    )


def inspect_load(
    load_id: str,
    units_inspected: int = 1000,
    leaker_units: int = 3,
    headers: Optional[dict] = None,
) -> dict:
    return get_success_data(
        api_client.record_load_inspection(
            load_id,
            load_inspection_payload(units_inspected, leaker_units),
            headers or QUALITY,
        )
    )


# --------------------------------------------------------------------------- #
# deviations
# --------------------------------------------------------------------------- #
def read_deviation(deviation_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_deviation(deviation_id, headers or QUALITY)
    )


def list_deviations(headers: Optional[dict] = None, **params) -> List[dict]:
    return get_success_data(
        api_client.list_deviations(headers or QUALITY, params or None)
    )


def first_deviation_on_cycle(cycle_id: str) -> dict:
    rows = list_deviations(cycle_id=cycle_id)
    assert rows, f"expected at least one deviation on cycle {cycle_id}"
    return rows[0]


def first_deviation_on_load(load_id: str) -> dict:
    rows = list_deviations(cycle_load_id=load_id)
    assert rows, f"expected at least one deviation on load {load_id}"
    return rows[0]


def adjudicate_deviation(
    deviation_id: str,
    disposition: str,
    root_cause_code: str = TEST_DEFAULTS["ROOT_CAUSE_EQUIP"],
    headers: Optional[dict] = None,
) -> dict:
    return get_success_data(
        api_client.adjudicate_deviation(
            deviation_id,
            adjudicate_deviation_payload(disposition, root_cause_code),
            headers or QUALITY,
        )
    )


# --------------------------------------------------------------------------- #
# chargeback lines
# --------------------------------------------------------------------------- #
def read_chargeback_line(line_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_chargeback_line(line_id, headers or ADMIN)
    )


def list_chargeback_lines(headers: Optional[dict] = None, **params) -> List[dict]:
    return get_success_data(
        api_client.list_chargeback_lines(headers or ADMIN, params or None)
    )


def waive_chargeback_line(
    line_id: str, waive_reason: str = "goodwill pending supplier claim"
) -> dict:
    return get_success_data(
        api_client.waive_chargeback_line(line_id, waive_payload(waive_reason), ADMIN)
    )


# --------------------------------------------------------------------------- #
# composite builders — the facility itself
# --------------------------------------------------------------------------- #
def setup_facility(
    clock: str = CLOCK_AUG03,
    customer_code: str = TEST_DEFAULTS["CUSTOMER_CODE"],
    family_code: str = TEST_DEFAULTS["FAMILY_CODE"],
    room_code: str = TEST_DEFAULTS["ROOM_CODE"],
    vessel_code: str = TEST_DEFAULTS["VESSEL_CODE"],
    room_capacity: int = 2,
    family_overrides: Optional[Dict] = None,
    vessel_overrides: Optional[Dict] = None,
    room_overrides: Optional[Dict] = None,
    customer_overrides: Optional[Dict] = None,
) -> dict:
    """The standing configuration: clock, one brand owner, one family, one vessel
    and one cold room.

    Defaults describe the VERDE / RTE_GUAC / HPP-1 / CR-1 facility: an
    RTE_PRODUCE family with 45 minutes of cleanout and a 4.0 C ceiling on both
    sides of the cold chain, a four-basket machine ramping at 6.0 MPa/s with 12
    seconds of decompression, and a two-position room that only accepts
    RTE_PRODUCE.
    """
    set_clock(clock)
    customer = register_customer(code=customer_code, **(customer_overrides or {}))
    family = define_family(family_code=family_code, **(family_overrides or {}))
    vessel = commission_vessel(vessel_code=vessel_code, **(vessel_overrides or {}))
    room = define_cold_room(
        room_code=room_code,
        capacity_pallets=room_capacity,
        allowed_family_groups=[
            (family_overrides or {}).get(
                "cross_contamination_group", TEST_DEFAULTS["GROUP"]
            )
        ],
        **(room_overrides or {}),
    )
    return {
        "customer": customer,
        "customer_headers": make_customer_headers(customer["id"]),
        "family": family,
        "vessel": vessel,
        "room": room,
    }


def setup_qualified_facility(
    contract_overrides: Optional[Dict] = None,
    qualification_overrides: Optional[Dict] = None,
    **facility_kwargs,
) -> dict:
    """The facility plus one QUALIFIED recipe and one ACTIVE capacity contract."""
    world = setup_facility(**facility_kwargs)
    world["qualification"] = qualify_recipe(
        world["customer"]["id"],
        world["family"]["id"],
        **(qualification_overrides or {}),
    )
    world["contract"] = open_active_contract(
        world["customer"]["id"], **(contract_overrides or {})
    )
    return world


def setup_stored_pallet(
    pallet_ref: str = "PAL-001", unit_count: int = 1000, **kwargs
) -> dict:
    """A qualified facility with one pallet sitting in cold storage."""
    world = setup_qualified_facility(**kwargs)
    world["lot"] = store_pallet(
        world["customer"]["id"],
        world["qualification"]["id"],
        world["room"]["id"],
        pallet_ref=pallet_ref,
        unit_count=unit_count,
        gross_weight_kg=640.0,
    )
    return world


def add_stored_pallet(
    world: dict,
    pallet_ref: str,
    unit_count: int,
    gross_weight_kg: float = 520.0,
    pulp_temp_c: float = 3.4,
    **overrides,
) -> dict:
    """Receive and accept a further pallet into the world's cold room."""
    return store_pallet(
        world["customer"]["id"],
        world["qualification"]["id"],
        world["room"]["id"],
        pallet_ref=pallet_ref,
        unit_count=unit_count,
        gross_weight_kg=gross_weight_kg,
        pulp_temp_c=pulp_temp_c,
        **overrides,
    )


# --------------------------------------------------------------------------- #
# composite builders — the chamber run
# --------------------------------------------------------------------------- #
def setup_scheduled_cycle(
    cycle_overrides: Optional[Dict] = None, **kwargs
) -> dict:
    """A qualified facility with one stored pallet and one SCHEDULED cycle."""
    world = setup_stored_pallet(**kwargs)
    world["cycle"] = schedule_cycle(
        world["vessel"]["id"], world["family"]["id"], **(cycle_overrides or {})
    )
    return world


def setup_loaded_cycle(
    baskets_used: int = 2, units_loaded: int = 1000, **kwargs
) -> dict:
    """One load booked onto the cycle, so the cycle sits at LOADED."""
    world = setup_scheduled_cycle(**kwargs)
    world["load"] = book_load(
        world["cycle"]["id"],
        world["lot"]["id"],
        world["contract"]["id"],
        baskets_used=baskets_used,
        units_loaded=units_loaded,
        expected_cycle_version=world["cycle"]["version"],
    )
    world["cycle"] = read_cycle(world["cycle"]["id"])
    return world


def setup_running_cycle(**kwargs) -> dict:
    """The chamber is pressurised: the cycle is RUNNING and the pallet IN_VESSEL."""
    world = setup_loaded_cycle(**kwargs)
    start_cycle(world["cycle"]["id"])
    world["cycle"] = read_cycle(world["cycle"]["id"])
    world["lot"] = read_lot(world["lot"]["id"])
    return world


def setup_completed_clean_cycle(
    actual_hold_seconds: int = 195,
    come_up_seconds: int = 104,
    water_temp_c: float = 7.5,
    **kwargs,
) -> dict:
    """A CCP record inside every limit, so the cycle lands at COMPLETED_CLEAN.

    The default record measures 104 seconds of come-up and 195 seconds of hold,
    which is 491 seconds of cycle time under the ACTUAL variant against the 472
    seconds the ESTIMATED variant predicted.
    """
    world = setup_running_cycle(**kwargs)
    world["cycle_log"] = capture_cycle_log(
        world["cycle"]["id"],
        actual_hold_seconds=actual_hold_seconds,
        come_up_seconds=come_up_seconds,
        water_temp_c=water_temp_c,
    )
    world["cycle"] = read_cycle(world["cycle"]["id"])
    world["lot"] = read_lot(world["lot"]["id"])
    return world


def setup_completed_deviated_cycle(
    actual_hold_seconds: int = 170,
    come_up_seconds: int = 104,
    water_temp_c: float = 7.5,
    actual_pressure_mpa: float = TEST_DEFAULTS["PRESSURE_MPA"],
    **kwargs,
) -> dict:
    """A CCP record short of a limit, so the cycle lands at COMPLETED_DEVIATED.

    170 seconds against a required 180 is a 5.56 percent shortfall and therefore
    CRITICAL; 179 seconds is 0.56 percent and therefore MAJOR.
    """
    world = setup_running_cycle(**kwargs)
    world["cycle_log"] = capture_cycle_log(
        world["cycle"]["id"],
        actual_pressure_mpa=actual_pressure_mpa,
        actual_hold_seconds=actual_hold_seconds,
        come_up_seconds=come_up_seconds,
        water_temp_c=water_temp_c,
    )
    world["cycle"] = read_cycle(world["cycle"]["id"])
    world["lot"] = read_lot(world["lot"]["id"])
    world["deviation"] = first_deviation_on_cycle(world["cycle"]["id"])
    return world


def setup_dispositioned_clean_cycle(**kwargs) -> dict:
    """The clean branch closed out: the cycle is DISPOSITIONED and the load ALLOCATED.

    With the default record the actual fee is 12825 cents, all of it allocated to
    the single load.
    """
    world = setup_completed_clean_cycle(**kwargs)
    disposition_cycle(world["cycle"]["id"])
    world["cycle"] = read_cycle(world["cycle"]["id"])
    world["load"] = read_load(world["load"]["id"])
    world["lot"] = read_lot(world["lot"]["id"])
    return world


def setup_inspected_load(
    units_inspected: int = 1000, leaker_units: int = 3, **kwargs
) -> dict:
    """A dispositioned clean cycle whose single load has been package-inspected.

    Three leakers in exactly 1000 units is 3000 ppm, which puts the liability on
    the customer and raises a PACKAGE_FAILURE_RATE deviation.
    """
    world = setup_dispositioned_clean_cycle(**kwargs)
    inspect_load(
        world["load"]["id"],
        units_inspected=units_inspected,
        leaker_units=leaker_units,
    )
    world["load"] = read_load(world["load"]["id"])
    world["customer"] = read_customer(world["customer"]["id"])
    return world


def setup_pending_chargeback_line(**kwargs) -> dict:
    """A world with exactly one PENDING chargeback line, from a 3000 ppm load."""
    world = setup_inspected_load(**kwargs)
    lines = list_chargeback_lines(customer_id=world["customer"]["id"])
    assert lines, "expected the 3000 ppm inspection to mint a chargeback line"
    world["chargeback_line"] = lines[0]
    return world


# --------------------------------------------------------------------------- #
# composite builders — two pallets in one chamber
# --------------------------------------------------------------------------- #
def setup_two_pallet_loaded_cycle(**kwargs) -> dict:
    """Two pallets of the same customer share one four-basket chamber, 2 + 2.

    Both pallets fill the two-position cold room, so the room reads
    ``occupied_pallets`` 2 and ``capacity_state`` AT_CAPACITY.
    """
    world = setup_scheduled_cycle(**kwargs)
    world["lot2"] = add_stored_pallet(world, "PAL-002", 800)
    world["load"] = book_load(
        world["cycle"]["id"],
        world["lot"]["id"],
        world["contract"]["id"],
        baskets_used=2,
        units_loaded=1000,
    )
    world["load2"] = book_load(
        world["cycle"]["id"],
        world["lot2"]["id"],
        world["contract"]["id"],
        baskets_used=2,
        units_loaded=800,
    )
    world["cycle"] = read_cycle(world["cycle"]["id"])
    return world


def setup_two_pallet_completed_deviated_cycle(
    actual_hold_seconds: int = 170, **kwargs
) -> dict:
    """Both pallets in one chamber, logged short of the required hold."""
    world = setup_two_pallet_loaded_cycle(**kwargs)
    start_cycle(world["cycle"]["id"])
    world["cycle_log"] = capture_cycle_log(
        world["cycle"]["id"],
        actual_hold_seconds=actual_hold_seconds,
        come_up_seconds=104,
        water_temp_c=7.5,
    )
    world["cycle"] = read_cycle(world["cycle"]["id"])
    world["lot"] = read_lot(world["lot"]["id"])
    world["lot2"] = read_lot(world["lot2"]["id"])
    world["deviation"] = first_deviation_on_cycle(world["cycle"]["id"])
    return world


def setup_two_pallet_dispositioned_cycle(**kwargs) -> dict:
    """Both pallets treated cleanly and the fee split across the two loads.

    Four of four baskets is 100.00 percent utilisation, which earns no surcharge:
    the 491-second run bills 11250 cents gross, takes the 3 percent credit and
    splits 10912 cents into 5456 and 5456.
    """
    world = setup_two_pallet_loaded_cycle(**kwargs)
    start_cycle(world["cycle"]["id"])
    world["cycle_log"] = capture_cycle_log(
        world["cycle"]["id"], actual_hold_seconds=195, come_up_seconds=104, water_temp_c=7.5
    )
    disposition_cycle(world["cycle"]["id"])
    world["cycle"] = read_cycle(world["cycle"]["id"])
    world["load"] = read_load(world["load"]["id"])
    world["load2"] = read_load(world["load2"]["id"])
    world["lot"] = read_lot(world["lot"]["id"])
    world["lot2"] = read_lot(world["lot2"]["id"])
    return world


# --------------------------------------------------------------------------- #
# composite builders — three loads on the six-basket machine
# --------------------------------------------------------------------------- #
def setup_three_load_cycle_on_second_vessel() -> dict:
    """Three pallets of 1, 1 and 2 baskets on the six-basket machine.

    Four of six baskets is 66.67 percent utilisation, which draws the 8 percent
    surcharge; logged at exactly the target values the run is 495 seconds, bills
    11250 cents of base, 900 of surcharge and takes a 608-cent credit, leaving
    11542 cents to divide across the three loads.
    """
    world = setup_qualified_facility(room_code="CR-2", room_capacity=5)
    world["vessel2"] = commission_second_vessel()
    world["lotA"] = add_stored_pallet(
        world, "PAL-101", 400, gross_weight_kg=260.0, pulp_temp_c=3.2
    )
    world["lotB"] = add_stored_pallet(
        world, "PAL-102", 400, gross_weight_kg=260.0, pulp_temp_c=3.2
    )
    world["lotC"] = add_stored_pallet(
        world, "PAL-103", 800, gross_weight_kg=520.0, pulp_temp_c=3.2
    )
    world["cycle"] = schedule_cycle(
        world["vessel2"]["id"],
        world["family"]["id"],
        scheduled_start="2026-08-06T09:00:00Z",
    )
    world["loadA"] = book_load(
        world["cycle"]["id"],
        world["lotA"]["id"],
        world["contract"]["id"],
        baskets_used=1,
        units_loaded=400,
    )
    world["loadB"] = book_load(
        world["cycle"]["id"],
        world["lotB"]["id"],
        world["contract"]["id"],
        baskets_used=1,
        units_loaded=400,
    )
    world["loadC"] = book_load(
        world["cycle"]["id"],
        world["lotC"]["id"],
        world["contract"]["id"],
        baskets_used=2,
        units_loaded=800,
    )
    start_cycle(world["cycle"]["id"])
    world["cycle_log"] = capture_cycle_log(
        world["cycle"]["id"],
        actual_hold_seconds=180,
        come_up_seconds=120,
        water_temp_c=7.0,
    )
    world["cycle"] = read_cycle(world["cycle"]["id"])
    return world


# --------------------------------------------------------------------------- #
# composite builders — the single-slot spot contract
# --------------------------------------------------------------------------- #
def setup_spot_contract_world(**kwargs) -> dict:
    """A qualified facility whose only live contract commits a single slot.

    One booking therefore drives the ledger to reserved 1 / consumed 0 /
    available 0 and flips the contract ACTIVE to EXHAUSTED.
    """
    world = setup_stored_pallet(
        contract_overrides={
            "season_code": "FY26-SPOT",
            "committed_slots": 1,
            "priority_rank": 2,
        },
        **kwargs,
    )
    world["cycle"] = schedule_cycle(world["vessel"]["id"], world["family"]["id"])
    return world


def setup_exhausted_spot_contract_world(**kwargs) -> dict:
    """The single-slot contract already exhausted by one booked load."""
    world = setup_spot_contract_world(**kwargs)
    world["load"] = book_load(
        world["cycle"]["id"],
        world["lot"]["id"],
        world["contract"]["id"],
        baskets_used=2,
        units_loaded=1000,
        expected_cycle_version=world["cycle"]["version"],
    )
    world["cycle"] = read_cycle(world["cycle"]["id"])
    world["contract"] = read_contract(world["contract"]["id"])
    return world
