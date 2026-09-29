"""Composite setup helpers.

Every test runs against an empty database, so each helper here builds the state
it needs from scratch using only endpoints the PRD declares.  Setup calls use
the lenient ``get_success_data`` validator so a broken precondition surfaces as
a setup failure rather than as a confusing assertion failure.
"""
import copy
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC, SIZE_CURVE_TOP_4SZ, TEST_DEFAULTS
from .factories import (
    create_fixture_plan_payload,
    create_item_payload,
    create_program_payload,
    create_promo_event_payload,
    create_receipt_payload,
    create_size_profile_payload,
    create_store_payload,
    create_store_position_payload,
    create_transfer_payload,
    units_by_size,
)
from .test_users import (
    TEST_USERS,
    make_allocation_manager_headers,
    make_allocator_headers,
    make_planning_admin_headers,
    make_store_operator_headers,
)

ADMIN = TEST_USERS["planning_admin_headers"]
ALLOCATOR = TEST_USERS["allocator_headers"]
MANAGER = TEST_USERS["allocation_manager_headers"]

# --------------------------------------------------------------------------- #
# Reusable network descriptions
# --------------------------------------------------------------------------- #

STORE_SPECS_FOUR = [
    {
        "store_code": "0101",
        "grade": "A",
        "grade_index_bp": 13000,
        "cluster_code": "URBAN",
        "freight_flat_usd": 41.00,
        "historical_sell_through_bp": 6500,
    },
    {
        "store_code": "0102",
        "grade": "B",
        "grade_index_bp": 10000,
        "cluster_code": "URBAN",
        "freight_flat_usd": 38.00,
        "historical_sell_through_bp": 5800,
    },
    {
        "store_code": "0103",
        "grade": "C",
        "grade_index_bp": 12500,
        "cluster_code": "SUBURBAN",
        "freight_flat_usd": 42.00,
        "historical_sell_through_bp": 4200,
    },
    {
        "store_code": "0104",
        "grade": "D",
        "grade_index_bp": 11000,
        "cluster_code": "SUBURBAN",
        "freight_flat_usd": 55.00,
        "historical_sell_through_bp": 3100,
    },
]

STORE_SPECS_THREE = STORE_SPECS_FOUR[:3]

# Shelf plans effective 2026-07-01, open ended.
FIXTURE_SPECS_FOUR = {
    "0101": {"fixture_count": 4, "facings_per_fixture": 3, "units_per_facing": 4,
             "presentation_min_units": 12},
    "0102": {"fixture_count": 2, "facings_per_fixture": 3, "units_per_facing": 4,
             "presentation_min_units": 8},
    "0103": {"fixture_count": 1, "facings_per_fixture": 4, "units_per_facing": 5,
             "presentation_min_units": 8},
    "0104": {"fixture_count": 1, "facings_per_fixture": 4, "units_per_facing": 5,
             "presentation_min_units": 6},
}

FIXTURE_SPECS_THREE = {
    "0101": {"fixture_count": 4, "facings_per_fixture": 3, "units_per_facing": 4,
             "presentation_min_units": 12},
    "0102": {"fixture_count": 2, "facings_per_fixture": 3, "units_per_facing": 4,
             "presentation_min_units": 8},
    "0103": {"fixture_count": 1, "facings_per_fixture": 3, "units_per_facing": 5,
             "presentation_min_units": 8},
}

# 0101 LOW + BROKEN, 0102 OVERSTOCK + COMPLETE, 0103 IN_STOCK + COMPLETE.
POSITION_SPECS_REBALANCE = {
    "0101": {
        "on_hand_units": 4,
        "size_on_hand": [
            {"size_code": "S", "units": 0},
            {"size_code": "M", "units": 3},
            {"size_code": "L", "units": 1},
            {"size_code": "XL", "units": 0},
        ],
        "min_units": 12, "max_units": 48,
        "weekly_forecast_units": 9, "trailing_4wk_sales_units": 30,
    },
    "0102": {
        "on_hand_units": 30,
        "size_on_hand": [
            {"size_code": "S", "units": 8},
            {"size_code": "M", "units": 10},
            {"size_code": "L", "units": 8},
            {"size_code": "XL", "units": 4},
        ],
        "min_units": 8, "max_units": 24,
        "weekly_forecast_units": 5, "trailing_4wk_sales_units": 16,
    },
    "0103": {
        "on_hand_units": 5,
        "size_on_hand": [
            {"size_code": "S", "units": 1},
            {"size_code": "M", "units": 2},
            {"size_code": "L", "units": 1},
            {"size_code": "XL", "units": 1},
        ],
        "min_units": 4, "max_units": 20,
        "weekly_forecast_units": 3, "trailing_4wk_sales_units": 6,
    },
}

# Four positions used by the receipt-allocation scenarios.
POSITION_SPECS_RECEIPT = {
    "0101": {
        "on_hand_units": 6,
        "size_on_hand": [
            {"size_code": "S", "units": 0},
            {"size_code": "M", "units": 4},
            {"size_code": "L", "units": 2},
            {"size_code": "XL", "units": 0},
        ],
        "on_order_units": 4,
        "min_units": 12, "max_units": 48,
        "weekly_forecast_units": 9, "trailing_4wk_sales_units": 30,
    },
    "0102": {
        "on_hand_units": 20,
        "size_on_hand": [
            {"size_code": "S", "units": 5},
            {"size_code": "M", "units": 7},
            {"size_code": "L", "units": 6},
            {"size_code": "XL", "units": 2},
        ],
        "on_order_units": 0,
        "min_units": 8, "max_units": 24,
        "weekly_forecast_units": 5, "trailing_4wk_sales_units": 16,
    },
    "0103": {
        "on_hand_units": 2,
        "size_on_hand": [
            {"size_code": "S", "units": 0},
            {"size_code": "M", "units": 1},
            {"size_code": "L", "units": 1},
            {"size_code": "XL", "units": 0},
        ],
        "on_order_units": 0,
        "min_units": 8, "max_units": 20,
        "weekly_forecast_units": 3, "trailing_4wk_sales_units": 6,
    },
    "0104": {
        "on_hand_units": 0,
        "size_on_hand": [],
        "on_order_units": 0,
        "min_units": 6, "max_units": 20,
        "weekly_forecast_units": 2, "trailing_4wk_sales_units": 5,
    },
}


# --------------------------------------------------------------------------- #
# Tier 1 — single-entity creation and state progression
# --------------------------------------------------------------------------- #

def set_clock(instant: str, headers: Optional[dict] = None) -> dict:
    """Move the logical clock. The PRD's default before any set is 2026-08-01T00:00:00Z."""
    return get_success_data(
        api_client.set_current_utc({"current_utc": instant}, headers or ADMIN)
    )


def reset_clock(headers: Optional[dict] = None) -> dict:
    return set_clock(DEFAULT_CLOCK_UTC, headers)


def create_program(**overrides) -> dict:
    return get_success_data(
        api_client.create_program(create_program_payload(**overrides), ADMIN)
    )


def create_active_program(**overrides) -> dict:
    """Create a program and walk it PLANNING -> ACTIVE."""
    program = create_program(**overrides)
    return get_success_data(api_client.activate_program(program["id"], ADMIN))


def lock_program(program_id: str, reason: str = "fiscal freeze") -> dict:
    return get_success_data(
        api_client.lock_program(program_id, MANAGER, {"reason": reason})
    )


def unlock_program(program_id: str) -> dict:
    return get_success_data(api_client.unlock_program(program_id, MANAGER))


def create_store(program_id: str, store_code: str = "0101", **overrides) -> dict:
    return get_success_data(
        api_client.create_store(
            create_store_payload(program_id, store_code, **overrides), ADMIN
        )
    )


def set_store_status(store_id: str, status: str) -> dict:
    return get_success_data(
        api_client.set_store_status(store_id, {"target_status": status}, ADMIN)
    )


def create_fixture_plan(store_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_fixture_plan(
            create_fixture_plan_payload(store_id, **overrides), ADMIN
        )
    )


def create_size_profile(program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_size_profile(
            create_size_profile_payload(program_id, **overrides), ADMIN
        )
    )


def create_item(program_id: str, size_profile_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_item(
            create_item_payload(program_id, size_profile_id, **overrides), ADMIN
        )
    )


def create_position(store_id: str, item_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_store_position(
            create_store_position_payload(store_id, item_id, **overrides), ALLOCATOR
        )
    )


def create_receipt(program_id: str, item_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_receipt(
            create_receipt_payload(program_id, item_id, **overrides), ALLOCATOR
        )
    )


def create_promo_event(program_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_promo_event(
            create_promo_event_payload(program_id, **overrides), ADMIN
        )
    )


def create_active_promo_event(program_id: str, **overrides) -> dict:
    """Create a promotional event and walk it DRAFT -> SCHEDULED -> ACTIVE."""
    event = create_promo_event(program_id, **overrides)
    get_success_data(api_client.schedule_promo_event(event["id"], ADMIN))
    return get_success_data(api_client.activate_promo_event(event["id"], ADMIN))


def create_scheduled_promo_event(program_id: str, **overrides) -> dict:
    """Create a promotional event and walk it DRAFT -> SCHEDULED."""
    event = create_promo_event(program_id, **overrides)
    return get_success_data(api_client.schedule_promo_event(event["id"], ADMIN))


# --------------------------------------------------------------------------- #
# Tier 2 — entity hierarchy: the whole merchandising network in one call
# --------------------------------------------------------------------------- #

def setup_network(
    store_specs: Optional[List[dict]] = None,
    fixture_specs: Optional[Dict[str, dict]] = None,
    position_specs: Optional[Dict[str, dict]] = None,
    program_overrides: Optional[dict] = None,
    profile_overrides: Optional[dict] = None,
    item_overrides: Optional[dict] = None,
    effective_from: str = "2026-07-01T00:00:00Z",
    activate: bool = True,
    create_positions: bool = True,
) -> Dict[str, Any]:
    """Build a program, its stores, their shelf plans, a size curve, one SKU and
    (optionally) one store position per store.

    Returns a dict with keys ``program``, ``stores`` (keyed by store_code),
    ``fixture_plans`` (keyed by store_code), ``size_profile``, ``item`` and
    ``positions`` (keyed by store_code).  Positions are created after the program
    is ACTIVE because the shelf plan and the curve must already exist.
    """
    store_specs = copy.deepcopy(store_specs if store_specs is not None else STORE_SPECS_THREE)
    fixture_specs = copy.deepcopy(
        fixture_specs if fixture_specs is not None else FIXTURE_SPECS_THREE
    )
    position_specs = copy.deepcopy(
        position_specs if position_specs is not None else POSITION_SPECS_REBALANCE
    )

    program = create_program(**(program_overrides or {}))
    stores: Dict[str, dict] = {}
    for spec in store_specs:
        spec = dict(spec)
        code = spec.pop("store_code")
        stores[code] = create_store(program["id"], code, **spec)

    fixture_plans: Dict[str, dict] = {}
    for code, spec in fixture_specs.items():
        if code not in stores:
            continue
        fixture_plans[code] = create_fixture_plan(
            stores[code]["id"], effective_from=effective_from, **spec
        )

    size_profile = create_size_profile(program["id"], **(profile_overrides or {}))
    item = create_item(program["id"], size_profile["id"], **(item_overrides or {}))

    if activate:
        program = get_success_data(api_client.activate_program(program["id"], ADMIN))

    positions: Dict[str, dict] = {}
    if create_positions:
        for code, spec in position_specs.items():
            if code not in stores:
                continue
            positions[code] = create_position(stores[code]["id"], item["id"], **spec)

    return {
        "program": program,
        "stores": stores,
        "fixture_plans": fixture_plans,
        "size_profile": size_profile,
        "item": item,
        "positions": positions,
    }


def setup_rebalance_network(**overrides) -> Dict[str, Any]:
    """Three stores where 0101 is LOW and BROKEN, 0102 is OVERSTOCK and COMPLETE
    and 0103 is IN_STOCK and COMPLETE. The starting point for transfer economics,
    assortment detection and remedy selection."""
    kwargs = {
        "store_specs": STORE_SPECS_THREE,
        "fixture_specs": FIXTURE_SPECS_THREE,
        "position_specs": POSITION_SPECS_REBALANCE,
    }
    kwargs.update(overrides)
    return setup_network(**kwargs)


def setup_receipt_network(**overrides) -> Dict[str, Any]:
    """Four graded stores with shelf plans and positions, ready for a receipt."""
    kwargs = {
        "store_specs": STORE_SPECS_FOUR,
        "fixture_specs": FIXTURE_SPECS_FOUR,
        "position_specs": POSITION_SPECS_RECEIPT,
    }
    kwargs.update(overrides)
    return setup_network(**kwargs)


def setup_network_with_staged_receipt(
    units_received: int = 60,
    size_received: Optional[List[dict]] = None,
    network: Optional[Dict[str, Any]] = None,
    **network_overrides,
) -> Dict[str, Any]:
    """A four-store network plus one STAGED receipt for its SKU."""
    scenario = network if network is not None else setup_receipt_network(**network_overrides)
    receipt_kwargs: Dict[str, Any] = {"units_received": units_received}
    if size_received is not None:
        receipt_kwargs["size_received"] = size_received
    scenario["receipt"] = create_receipt(
        scenario["program"]["id"], scenario["item"]["id"], **receipt_kwargs
    )
    return scenario


# --------------------------------------------------------------------------- #
# Tier 3 — lifecycle shortcuts
# --------------------------------------------------------------------------- #

def current_receipt_version(receipt_id: str, headers: Optional[dict] = None) -> int:
    """Re-read the receipt so a run creation can present a fresh token."""
    data = get_success_data(api_client.get_receipt(receipt_id, headers or ALLOCATOR))
    return data["version"]


def current_position_version(position_id: str, headers: Optional[dict] = None) -> int:
    data = get_success_data(
        api_client.get_store_position(position_id, headers or ALLOCATOR)
    )
    return data["version"]


def create_run(
    receipt_id: str,
    method: str = "DEMAND_DRIVEN",
    need_basis: str = "FORWARD_LOOKING",
    expected_receipt_version: Optional[int] = None,
    headers: Optional[dict] = None,
) -> dict:
    """Create an allocation run against the receipt's current version."""
    version = (
        expected_receipt_version
        if expected_receipt_version is not None
        else current_receipt_version(receipt_id)
    )
    return get_success_data(
        api_client.create_allocation_run(
            receipt_id,
            {
                "method": method,
                "need_basis": need_basis,
                "expected_receipt_version": version,
            },
            headers or ALLOCATOR,
        )
    )


def create_proposed_run(
    receipt_id: str,
    method: str = "DEMAND_DRIVEN",
    need_basis: str = "FORWARD_LOOKING",
    headers: Optional[dict] = None,
) -> dict:
    """Create a run and walk it DRAFT -> PROPOSED."""
    caller = headers or ALLOCATOR
    run = create_run(receipt_id, method, need_basis, headers=caller)
    return get_success_data(api_client.propose_run(run["id"], caller))


def create_committed_run(
    receipt_id: str,
    method: str = "DEMAND_DRIVEN",
    need_basis: str = "FORWARD_LOOKING",
    author_headers: Optional[dict] = None,
    committer_headers: Optional[dict] = None,
) -> dict:
    """Create a run, propose it, then have a different operator commit it."""
    run = create_proposed_run(receipt_id, method, need_basis, headers=author_headers)
    return get_success_data(
        api_client.commit_run(run["id"], committer_headers or MANAGER)
    )


def lines_for_run(run_id: str, headers: Optional[dict] = None) -> List[dict]:
    response = api_client.list_allocation_lines(
        headers or ALLOCATOR, params={"run_id": run_id, "limit": 100}
    )
    body = response.json()
    return body["data"]


def line_for_store(run_id: str, store_id: str, headers: Optional[dict] = None) -> dict:
    for line in lines_for_run(run_id, headers):
        if line["store_id"] == store_id:
            return line
    raise AssertionError(f"Setup failed: run {run_id} has no line for store {store_id}")


def ship_and_confirm_line(line_id: str, store_id: str) -> dict:
    """Walk a committed line PENDING -> SHIPPED -> RECEIVED. The confirmation is
    booked by the receiving store itself."""
    get_success_data(api_client.ship_line(line_id, MANAGER))
    return get_success_data(
        api_client.confirm_line_receipt(line_id, make_store_operator_headers(store_id))
    )


# --------------------------------------------------------------------------- #
# Tier 4 — transfer economics and assortment remedies
# --------------------------------------------------------------------------- #

def propose_transfer(
    scenario: Dict[str, Any],
    from_code: str = "0102",
    to_code: str = "0101",
    units: int = 6,
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    """Propose a rebalancing transfer between two stores of a built network,
    presenting the donor position's current version."""
    donor_position = scenario["positions"][from_code]
    payload = create_transfer_payload(
        scenario["program"]["id"],
        scenario["stores"][from_code]["id"],
        scenario["stores"][to_code]["id"],
        scenario["item"]["id"],
        units,
        current_position_version(donor_position["id"]),
        **overrides,
    )
    return get_success_data(
        api_client.create_transfer_recommendation(payload, headers or ALLOCATOR)
    )


def setup_proposed_transfer(units: int = 6, **network_overrides) -> Dict[str, Any]:
    """Rebalance network plus one PROPOSED transfer from 0102 to 0101."""
    scenario = setup_rebalance_network(**network_overrides)
    scenario["transfer"] = propose_transfer(scenario, units=units)
    return scenario


def setup_approved_transfer(units: int = 6, **network_overrides) -> Dict[str, Any]:
    """Rebalance network plus one APPROVED transfer, approved by a manager who is
    not the proposer."""
    scenario = setup_proposed_transfer(units=units, **network_overrides)
    scenario["transfer"] = get_success_data(
        api_client.approve_transfer(scenario["transfer"]["id"], MANAGER)
    )
    return scenario


def setup_dispatched_transfer(units: int = 6, **network_overrides) -> Dict[str, Any]:
    scenario = setup_approved_transfer(units=units, **network_overrides)
    scenario["transfer"] = get_success_data(
        api_client.dispatch_transfer(scenario["transfer"]["id"], MANAGER)
    )
    return scenario


def receive_transfer(scenario: Dict[str, Any], to_code: str = "0101") -> dict:
    """Book the physical arrival as the receiving store."""
    receiver_id = scenario["stores"][to_code]["id"]
    return get_success_data(
        api_client.receive_transfer(
            scenario["transfer"]["id"], make_store_operator_headers(receiver_id)
        )
    )


def run_detection(program_id: str, headers: Optional[dict] = None) -> Any:
    response = api_client.run_assortment_detection(
        {"program_id": program_id}, headers or MANAGER
    )
    return get_success_data(response)


def actions_for(
    program_id: str,
    item_id: Optional[str] = None,
    store_id: Optional[str] = None,
    headers: Optional[dict] = None,
) -> List[dict]:
    params: Dict[str, Any] = {"limit": 100}
    if item_id:
        params["item_id"] = item_id
    if store_id:
        params["store_id"] = store_id
    response = api_client.list_assortment_actions(headers or MANAGER, params=params)
    return response.json()["data"]


def setup_detected_action(
    store_code: str = "0101", **network_overrides
) -> Dict[str, Any]:
    """Rebalance network, one detection sweep, and the resulting PENDING action
    for the degraded store."""
    scenario = setup_rebalance_network(**network_overrides)
    run_detection(scenario["program"]["id"])
    matches = actions_for(
        scenario["program"]["id"],
        item_id=scenario["item"]["id"],
        store_id=scenario["stores"][store_code]["id"],
    )
    assert matches, (
        f"Setup failed: detection produced no assortment action for store {store_code}"
    )
    scenario["action"] = matches[0]
    return scenario


def setup_executed_consolidation(**network_overrides) -> Dict[str, Any]:
    """Detection, then execution of the CONSOLIDATION remedy. Leaves the item in
    CONSOLIDATION_PENDING with a system-proposed transfer in flight."""
    scenario = setup_detected_action(**network_overrides)
    scenario["action"] = get_success_data(
        api_client.execute_assortment_action(scenario["action"]["id"], MANAGER)
    )
    transfers = api_client.list_transfer_recommendations(
        MANAGER, params={"program_id": scenario["program"]["id"], "limit": 100}
    ).json()["data"]
    consolidations = [t for t in transfers if t["source_reason"] == "CONSOLIDATION"]
    assert consolidations, (
        "Setup failed: executing a CONSOLIDATION action created no transfer"
    )
    scenario["transfer"] = consolidations[0]
    return scenario


def refresh_position(scenario: Dict[str, Any], store_code: str) -> dict:
    position_id = scenario["positions"][store_code]["id"]
    return get_success_data(api_client.get_store_position(position_id, ALLOCATOR))


def refresh_item(scenario: Dict[str, Any]) -> dict:
    return get_success_data(api_client.get_item(scenario["item"]["id"], ALLOCATOR))


def refresh_program(scenario: Dict[str, Any]) -> dict:
    return get_success_data(api_client.get_program(scenario["program"]["id"], ADMIN))


def refresh_receipt(scenario: Dict[str, Any]) -> dict:
    return get_success_data(api_client.get_receipt(scenario["receipt"]["id"], ALLOCATOR))


def network_on_hand_total(scenario: Dict[str, Any]) -> int:
    """Sum on_hand_units over every position of the built network."""
    total = 0
    for code in scenario["positions"]:
        total += refresh_position(scenario, code)["on_hand_units"]
    return total


def size_units(entity: dict, field: str) -> dict:
    """Collapse one of the size-keyed arrays into ``{size_code: units}``."""
    return units_by_size(entity.get(field))
