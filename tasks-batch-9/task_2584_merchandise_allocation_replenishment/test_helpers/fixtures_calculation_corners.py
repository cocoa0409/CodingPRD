"""Bespoke composite setups for the calculation and validation corner scenarios.

Every builder here constructs its whole world from scratch through PRD-declared
endpoints, because the harness wipes the database before each test.  Setup calls
use the lenient ``get_success_data`` validator so a broken precondition surfaces
as a setup failure rather than as a confusing assertion failure.

These builders are additive: they exist because the scenarios below need store
networks, size curves and promotional calendars that the shared helpers in
``fixtures`` do not describe.  Two request payloads are written out here rather
than reused, because the PRD names the fields ``target_status`` on a store
lifecycle move and ``reason`` on a program lock.
"""
from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK_UTC
from .fixtures import ADMIN, ALLOCATOR, MANAGER

# --------------------------------------------------------------------------- #
# Size curves used by the scenarios
# --------------------------------------------------------------------------- #

CURVE_TOP_4SZ = [
    {"size_code": "S", "share_bp": 2000},
    {"size_code": "M", "share_bp": 3500},
    {"size_code": "L", "share_bp": 3000},
    {"size_code": "XL", "share_bp": 1500},
]

CURVE_TOP_6SZ = [
    {"size_code": "XS", "share_bp": 800},
    {"size_code": "S", "share_bp": 2000},
    {"size_code": "M", "share_bp": 3000},
    {"size_code": "L", "share_bp": 2400},
    {"size_code": "XL", "share_bp": 1500},
    {"size_code": "XXL", "share_bp": 300},
]

CURVE_TOP_5SZ_EVEN = [
    {"size_code": "S", "share_bp": 2000},
    {"size_code": "M", "share_bp": 2000},
    {"size_code": "L", "share_bp": 2000},
    {"size_code": "XL", "share_bp": 2000},
    {"size_code": "XXL", "share_bp": 2000},
]

CURVE_TOP_5SZ_SKEW = [
    {"size_code": "S", "share_bp": 1900},
    {"size_code": "M", "share_bp": 3300},
    {"size_code": "L", "share_bp": 2900},
    {"size_code": "XL", "share_bp": 1200},
    {"size_code": "XXL", "share_bp": 700},
]

CURVE_TOP_TIE = [
    {"size_code": "S", "share_bp": 3000},
    {"size_code": "M", "share_bp": 3000},
    {"size_code": "L", "share_bp": 2500},
    {"size_code": "XL", "share_bp": 1500},
]

# Store descriptions reused across the scenarios, keyed by store_code.
STORE_ATTRS = {
    "0101": {"grade": "A", "grade_index_bp": 13000, "cluster_code": "URBAN",
             "freight_flat_usd": 41.00, "historical_sell_through_bp": 6500},
    "0102": {"grade": "B", "grade_index_bp": 10000, "cluster_code": "URBAN",
             "freight_flat_usd": 38.00, "historical_sell_through_bp": 5800},
    "0103": {"grade": "C", "grade_index_bp": 12500, "cluster_code": "SUBURBAN",
             "freight_flat_usd": 42.00, "historical_sell_through_bp": 4200},
    "0104": {"grade": "D", "grade_index_bp": 11000, "cluster_code": "SUBURBAN",
             "freight_flat_usd": 55.00, "historical_sell_through_bp": 3100},
    "0105": {"grade": "A", "grade_index_bp": 13000, "cluster_code": "URBAN",
             "freight_flat_usd": 39.00, "historical_sell_through_bp": 6100},
    "0106": {"grade": "A", "grade_index_bp": 13000, "cluster_code": "URBAN",
             "freight_flat_usd": 40.00, "historical_sell_through_bp": 6000},
}

PLAN_EFFECTIVE_FROM = "2026-07-01T00:00:00Z"
ITEM_CLASS = "APPAREL_TOP"


# --------------------------------------------------------------------------- #
# Small primitives
# --------------------------------------------------------------------------- #

def sizes(mapping: Dict[str, int]) -> List[Dict[str, Any]]:
    """Build a size/units array from a ``{size_code: units}`` mapping."""
    return [{"size_code": code, "units": units} for code, units in mapping.items()]


def units_map(entries: Optional[List[Dict[str, Any]]]) -> Dict[str, int]:
    """Collapse a size/units array into a ``{size_code: units}`` mapping."""
    return {entry["size_code"]: entry["units"] for entry in (entries or [])}


def set_clock(instant: str = DEFAULT_CLOCK_UTC) -> None:
    get_success_data(api_client.set_current_utc({"current_utc": instant}, ADMIN))


def new_program(**overrides: Any) -> Dict[str, Any]:
    payload = {
        "name": "FA26 Core Tops",
        "season_code": "FA26",
        "banner_code": "NORTH",
    }
    payload.update(overrides)
    return get_success_data(api_client.create_program(payload, ADMIN))


def activate(program_id: str) -> Dict[str, Any]:
    # PRD §4: activate is authorised for `PlanningAdmin` only.
    return get_success_data(api_client.activate_program(program_id, ADMIN))


def lock(program_id: str, reason: str = "priority ladder freeze") -> Dict[str, Any]:
    return get_success_data(api_client.lock_program(program_id, MANAGER, {"reason": reason}))


def unlock(program_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.unlock_program(program_id, MANAGER))


def new_store(program_id: str, store_code: str, **overrides: Any) -> Dict[str, Any]:
    payload = {"program_id": program_id, "store_code": store_code}
    payload.update(STORE_ATTRS.get(store_code, {}))
    payload.update(overrides)
    return get_success_data(api_client.create_store(payload, ADMIN))


def move_store(store_id: str, target_status: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.set_store_status(store_id, {"target_status": target_status}, ADMIN)
    )


def new_plan(
    store_id: str,
    fixture_count: int,
    facings_per_fixture: int,
    units_per_facing: int,
    presentation_min_units: int,
    effective_from: str = PLAN_EFFECTIVE_FROM,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "store_id": store_id,
        "item_class": ITEM_CLASS,
        "effective_from": effective_from,
        "fixture_count": fixture_count,
        "facings_per_fixture": facings_per_fixture,
        "units_per_facing": units_per_facing,
        "presentation_min_units": presentation_min_units,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_fixture_plan(payload, ADMIN))


def new_profile(
    program_id: str,
    profile_code: str = "TOP-4SZ",
    size_curve: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "program_id": program_id,
        "profile_code": profile_code,
        "item_class": ITEM_CLASS,
        "size_curve": size_curve if size_curve is not None else CURVE_TOP_4SZ,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_size_profile(payload, ADMIN))


def new_item(
    program_id: str,
    size_profile_id: str,
    sku_code: str = "SKU-1001",
    style_code: str = "ST-100",
    item_type: str = "SEASONAL",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "program_id": program_id,
        "size_profile_id": size_profile_id,
        "sku_code": sku_code,
        "style_code": style_code,
        "item_class": ITEM_CLASS,
        "item_type": item_type,
        "unit_cost_usd": 14.20,
        "retail_price_usd": 36.50,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_item(payload, ADMIN))


def new_position(
    store_id: str,
    item_id: str,
    on_hand_units: int,
    size_on_hand: Dict[str, int],
    min_units: int,
    max_units: int,
    weekly_forecast_units: int,
    trailing_4wk_sales_units: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "store_id": store_id,
        "item_id": item_id,
        "on_hand_units": on_hand_units,
        "size_on_hand": sizes(size_on_hand),
        "min_units": min_units,
        "max_units": max_units,
        "weekly_forecast_units": weekly_forecast_units,
        "trailing_4wk_sales_units": trailing_4wk_sales_units,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_store_position(payload, ALLOCATOR))


def new_receipt(
    program_id: str,
    item_id: str,
    reference: str,
    units_received: int,
    size_received: Dict[str, int],
    receipt_date: str = DEFAULT_CLOCK_UTC,
) -> Dict[str, Any]:
    payload = {
        "program_id": program_id,
        "item_id": item_id,
        "reference": reference,
        "units_received": units_received,
        "size_received": sizes(size_received),
        "receipt_date": receipt_date,
    }
    return get_success_data(api_client.create_receipt(payload, ALLOCATOR))


def receipt_version(receipt_id: str) -> int:
    return get_success_data(api_client.get_receipt(receipt_id, ALLOCATOR))["version"]


def position_version(position_id: str) -> int:
    return get_success_data(
        api_client.get_store_position(position_id, ALLOCATOR)
    )["version"]


def open_run_response(
    receipt_id: str,
    method: str,
    expected_receipt_version: int,
    need_basis: str = "FORWARD_LOOKING",
):
    """Raw response, so a caller can assert on a refusal."""
    return api_client.create_allocation_run(
        receipt_id,
        {
            "method": method,
            "need_basis": need_basis,
            "expected_receipt_version": expected_receipt_version,
        },
        ALLOCATOR,
    )


def open_run(
    receipt_id: str,
    method: str = "DEMAND_DRIVEN",
    need_basis: str = "FORWARD_LOOKING",
) -> Dict[str, Any]:
    version = receipt_version(receipt_id)
    return get_success_data(
        open_run_response(receipt_id, method, version, need_basis)
    )


def propose(run_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.propose_run(run_id, ALLOCATOR))


def commit(run_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.commit_run(run_id, MANAGER))


def run_lines(run_id: str) -> List[Dict[str, Any]]:
    response = api_client.list_allocation_lines(
        ALLOCATOR, params={"run_id": run_id, "limit": 100}
    )
    return get_success_data(response)


def lines_meta(run_id: str) -> Dict[str, Any]:
    response = api_client.list_allocation_lines(
        ALLOCATOR, params={"run_id": run_id, "limit": 100}
    )
    return response.json()["meta"]


def line_at(run_id: str, store_id: str) -> Optional[Dict[str, Any]]:
    for line in run_lines(run_id):
        if line["store_id"] == store_id:
            return line
    return None


def sweep(program_id: str) -> Any:
    return get_success_data(
        api_client.run_assortment_detection({"program_id": program_id}, MANAGER)
    )


def sweep_actions(program_id: str) -> List[Dict[str, Any]]:
    """The sweep's own result list, in the order the sweep returned it."""
    raised = sweep(program_id)
    if isinstance(raised, list):
        return raised
    if isinstance(raised, dict):
        for key in ("actions", "data", "items", "results"):
            if isinstance(raised.get(key), list):
                return raised[key]
    return []


def all_actions(**filters: Any) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"limit": 100}
    params.update(filters)
    response = api_client.list_assortment_actions(MANAGER, params=params)
    return get_success_data(response)


def action_at(item_id: str, store_id: str) -> Optional[Dict[str, Any]]:
    for action in all_actions(item_id=item_id, store_id=store_id):
        return action
    return None


def snapshot_response(program_id: str, cluster_code: str, basis: Optional[str] = None):
    payload: Dict[str, Any] = {"program_id": program_id, "cluster_code": cluster_code}
    if basis is not None:
        payload["basis"] = basis
    return api_client.create_performance_snapshot(payload, MANAGER)


def transfer_response(
    program_id: str,
    from_store_id: str,
    to_store_id: str,
    item_id: str,
    units: int,
    expected_from_position_version: int,
    headers: Optional[dict] = None,
):
    payload = {
        "program_id": program_id,
        "from_store_id": from_store_id,
        "to_store_id": to_store_id,
        "item_id": item_id,
        "units": units,
        "expected_from_position_version": expected_from_position_version,
    }
    return api_client.create_transfer_recommendation(
        payload, ALLOCATOR if headers is None else headers
    )


# --------------------------------------------------------------------------- #
# Scenario builders
# --------------------------------------------------------------------------- #

def build_model_resolution_network() -> Dict[str, Any]:
    """One store, one size curve, four SKUs spanning every item type plus one
    explicit override, and one twelve-unit receipt per SKU."""
    program = new_program()
    store = new_store(program["id"], "0101")
    new_plan(store["id"], 4, 3, 4, 12)
    profile = new_profile(program["id"], "TOP-4SZ", CURVE_TOP_4SZ)
    items = {
        "SKU-1001": new_item(
            program["id"], profile["id"], "SKU-1001", "ST-100", "SEASONAL"
        ),
        "SKU-2001": new_item(
            program["id"], profile["id"], "SKU-2001", "ST-200", "BASIC"
        ),
        "SKU-3001": new_item(
            program["id"], profile["id"], "SKU-3001", "ST-300", "FASHION"
        ),
        "SKU-4001": new_item(
            program["id"],
            profile["id"],
            "SKU-4001",
            "ST-400",
            "FASHION",
            replenishment_model_override="MIN_MAX",
        ),
    }
    activate(program["id"])
    twelve = {"S": 2, "M": 4, "L": 4, "XL": 2}
    receipts = {
        "ASN-C101": new_receipt(
            program["id"], items["SKU-1001"]["id"], "ASN-C101", 12, twelve
        ),
        "ASN-C102": new_receipt(
            program["id"], items["SKU-2001"]["id"], "ASN-C102", 12, twelve
        ),
        "ASN-C103": new_receipt(
            program["id"], items["SKU-3001"]["id"], "ASN-C103", 12, twelve
        ),
        "ASN-C104": new_receipt(
            program["id"], items["SKU-4001"]["id"], "ASN-C104", 12, twelve
        ),
    }
    return {
        "program": program,
        "store": store,
        "profile": profile,
        "items": items,
        "receipts": receipts,
    }


def build_need_target_network() -> Dict[str, Any]:
    """Two stores of different capacity, one SKU per replenishment model, and a
    thirty-unit receipt for each SKU."""
    program = new_program()
    s1 = new_store(program["id"], "0101")
    s2 = new_store(program["id"], "0102")
    new_plan(s1["id"], 4, 3, 4, 12)
    new_plan(s2["id"], 4, 2, 4, 8)
    profile = new_profile(program["id"], "TOP-4SZ", CURVE_TOP_4SZ)
    i1 = new_item(program["id"], profile["id"], "SKU-1001", "ST-100", "SEASONAL")
    i2 = new_item(program["id"], profile["id"], "SKU-2001", "ST-200", "BASIC")
    i3 = new_item(program["id"], profile["id"], "SKU-3001", "ST-300", "FASHION")
    activate(program["id"])
    positions = {
        "SKU-1001@0101": new_position(
            s1["id"], i1["id"], 13, {"S": 3, "M": 4, "L": 4, "XL": 2}, 12, 48, 9, 30
        ),
        "SKU-2001@0101": new_position(
            s1["id"], i2["id"], 5, {"S": 1, "M": 2, "L": 1, "XL": 1}, 10, 30, 4, 12
        ),
        "SKU-3001@0101": new_position(
            s1["id"], i3["id"], 13, {"S": 3, "M": 4, "L": 4, "XL": 2}, 12, 48, 9, 30
        ),
        "SKU-3001@0102": new_position(
            s2["id"], i3["id"], 25, {"S": 5, "M": 9, "L": 8, "XL": 3}, 8, 32, 5, 16
        ),
    }
    thirty = {"S": 6, "M": 11, "L": 9, "XL": 4}
    receipts = {
        "ASN-C201": new_receipt(program["id"], i1["id"], "ASN-C201", 30, thirty),
        "ASN-C202": new_receipt(program["id"], i2["id"], "ASN-C202", 30, thirty),
        "ASN-C203": new_receipt(program["id"], i3["id"], "ASN-C203", 30, thirty),
    }
    return {
        "program": program,
        "stores": {"0101": s1, "0102": s2},
        "items": {"SKU-1001": i1, "SKU-2001": i2, "SKU-3001": i3},
        "positions": positions,
        "receipts": receipts,
    }


def new_event(
    program_id: str,
    event_code: str,
    scope: str,
    start_date: str,
    end_date: str,
    lift_factor_bp: int,
    activate_it: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "event_code": event_code,
        "scope": scope,
        "start_date": start_date,
        "end_date": end_date,
        "lift_factor_bp": lift_factor_bp,
    }
    payload.update(overrides)
    event = get_success_data(api_client.create_promo_event(payload, ADMIN))
    if activate_it:
        get_success_data(api_client.schedule_promo_event(event["id"], ADMIN))
        event = get_success_data(api_client.activate_promo_event(event["id"], ADMIN))
    return event


def build_promo_network() -> Dict[str, Any]:
    """Two stores in different clusters and a seven-event promotional calendar in
    which only one event is a candidate for each store."""
    program = new_program()
    s1 = new_store(program["id"], "0101")
    s2 = new_store(program["id"], "0102", cluster_code="SUBURBAN")
    new_plan(s1["id"], 4, 3, 4, 12)
    new_plan(s2["id"], 2, 3, 4, 8)
    profile = new_profile(program["id"], "TOP-4SZ", CURVE_TOP_4SZ)
    item = new_item(program["id"], profile["id"], "SKU-1001", "ST-100", "SEASONAL")
    activate(program["id"])
    positions = {
        "0101": new_position(
            s1["id"], item["id"], 10, {"S": 2, "M": 4, "L": 3, "XL": 1}, 12, 48, 9, 30
        ),
        "0102": new_position(
            s2["id"], item["id"], 6, {"S": 1, "M": 3, "L": 2}, 8, 24, 5, 16
        ),
    }
    events: Dict[str, Any] = {}
    # The winning candidate for store 0101 is created first but only becomes
    # visible to need calculation once it is ACTIVE.
    store_a = get_success_data(
        api_client.create_promo_event(
            {
                "program_id": program["id"],
                "event_code": "EV-STORE-A",
                "scope": "STORE",
                "store_id": s1["id"],
                "item_class": ITEM_CLASS,
                "start_date": "2026-07-28T00:00:00Z",
                "end_date": "2026-08-05T00:00:00Z",
                "lift_factor_bp": 13000,
            },
            ADMIN,
        )
    )
    # A richer lift on the same store and window that is deliberately left DRAFT.
    events["EV-DRAFT"] = get_success_data(
        api_client.create_promo_event(
            {
                "program_id": program["id"],
                "event_code": "EV-DRAFT",
                "scope": "STORE",
                "store_id": s1["id"],
                "item_class": ITEM_CLASS,
                "start_date": "2026-07-28T00:00:00Z",
                "end_date": "2026-08-05T00:00:00Z",
                "lift_factor_bp": 30000,
            },
            ADMIN,
        )
    )
    get_success_data(api_client.schedule_promo_event(store_a["id"], ADMIN))
    events["EV-STORE-A"] = get_success_data(
        api_client.activate_promo_event(store_a["id"], ADMIN)
    )
    events["EV-CLUSTER"] = new_event(
        program["id"], "EV-CLUSTER", "CLUSTER",
        "2026-07-20T00:00:00Z", "2026-08-20T00:00:00Z", 18000,
        cluster_code="URBAN", item_class=ITEM_CLASS,
    )
    events["EV-PROGRAM"] = new_event(
        program["id"], "EV-PROGRAM", "PROGRAM",
        "2026-07-01T00:00:00Z", "2026-08-31T00:00:00Z", 25000,
    )
    events["EV-STORE-B"] = new_event(
        program["id"], "EV-STORE-B", "STORE",
        "2026-07-28T00:00:00Z", "2026-08-05T00:00:00Z", 20000,
        store_id=s2["id"], item_class=ITEM_CLASS,
    )
    events["EV-BOTTOM"] = new_event(
        program["id"], "EV-BOTTOM", "STORE",
        "2026-07-28T00:00:00Z", "2026-08-05T00:00:00Z", 22000,
        store_id=s1["id"], item_class="APPAREL_BOTTOM",
    )
    events["EV-FUTURE"] = new_event(
        program["id"], "EV-FUTURE", "STORE",
        "2026-08-08T00:00:00Z", "2026-08-12T00:00:00Z", 40000,
        store_id=s1["id"], item_class=ITEM_CLASS,
    )
    receipt = new_receipt(
        program["id"], item["id"], "ASN-C301", 40,
        {"S": 8, "M": 14, "L": 12, "XL": 6},
    )
    return {
        "program": program,
        "stores": {"0101": s1, "0102": s2},
        "item": item,
        "positions": positions,
        "events": events,
        "receipt": receipt,
    }


def build_scorecard_network() -> Dict[str, Any]:
    """Four stores across three clusters, one marked-down SKU, one store taken to
    CLOSING and one to REMODEL, and a single committed allocation line."""
    set_clock()
    program = new_program()
    s1 = new_store(program["id"], "0101")
    s2 = new_store(program["id"], "0102")
    s3 = new_store(program["id"], "0103")
    s4 = new_store(program["id"], "0104", cluster_code="OUTLET")
    new_plan(s1["id"], 4, 3, 4, 12)
    new_plan(s2["id"], 2, 3, 4, 8)
    new_plan(s3["id"], 1, 4, 5, 8)
    new_plan(s4["id"], 1, 4, 5, 6)
    profile = new_profile(program["id"], "TOP-4SZ", CURVE_TOP_4SZ)
    i1 = new_item(program["id"], profile["id"], "SKU-1001", "ST-100", "SEASONAL")
    i2 = new_item(program["id"], profile["id"], "SKU-2001", "ST-200", "SEASONAL")
    activate(program["id"])
    positions = {
        "SKU-1001@0101": new_position(
            s1["id"], i1["id"], 12, {"S": 3, "M": 4, "L": 4, "XL": 1}, 20, 40, 5, 40
        ),
        "SKU-1001@0102": new_position(
            s2["id"], i1["id"], 8, {"S": 2, "M": 3, "L": 2, "XL": 1}, 10, 30, 4, 20
        ),
        "SKU-1001@0103": new_position(
            s3["id"], i1["id"], 30, {"S": 7, "M": 11, "L": 9, "XL": 3}, 8, 30, 3, 25
        ),
        "SKU-1001@0104": new_position(
            s4["id"], i1["id"], 4, {"S": 1, "M": 1, "L": 1, "XL": 1}, 4, 20, 2, 8
        ),
        "SKU-2001@0101": new_position(s1["id"], i2["id"], 0, {}, 5, 20, 2, 9),
    }
    move_store(s4["id"], "CLOSING")
    move_store(s2["id"], "REMODEL")
    sweep(program["id"])
    action = action_at(i2["id"], s1["id"])
    assert action is not None, "Setup failed: the empty position raised no action"
    get_success_data(api_client.execute_assortment_action(action["id"], MANAGER))
    receipt = new_receipt(
        program["id"], i1["id"], "ASN-C401", 12, {"S": 2, "M": 4, "L": 4, "XL": 2}
    )
    run = open_run(receipt["id"], "DEMAND_DRIVEN")
    propose(run["id"])
    line = line_at(run["id"], s1["id"])
    assert line is not None, "Setup failed: store 0101 received no allocation line"
    commit(run["id"])
    return {
        "program": program,
        "stores": {"0101": s1, "0102": s2, "0103": s3, "0104": s4},
        "items": {"SKU-1001": i1, "SKU-2001": i2},
        "positions": positions,
        "receipt": receipt,
        "run": run,
        "line": line,
        "markdown_action": action,
    }


def build_proration_network() -> Dict[str, Any]:
    """Six identically stocked stores, one of which has a tiny fixture plan, and a
    twelve-unit receipt to spread across them."""
    program = new_program()
    codes = ["0101", "0102", "0103", "0104", "0105", "0106"]
    stores = {code: new_store(program["id"], code) for code in codes}
    for code in codes[:5]:
        new_plan(stores[code]["id"], 4, 3, 4, 12)
    new_plan(stores["0106"]["id"], 3, 1, 3, 2)
    profile = new_profile(program["id"], "TOP-4SZ", CURVE_TOP_4SZ)
    item = new_item(program["id"], profile["id"], "SKU-1001", "ST-100", "SEASONAL")
    activate(program["id"])
    positions = {
        code: new_position(
            stores[code]["id"], item["id"], 8,
            {"S": 2, "M": 3, "L": 2, "XL": 1}, 6, 40, 3, 10,
        )
        for code in codes
    }
    receipt = new_receipt(
        program["id"], item["id"], "ASN-C501", 12, {"S": 2, "M": 4, "L": 4, "XL": 2}
    )
    run = open_run(receipt["id"], "DEMAND_DRIVEN")
    proposed = propose(run["id"])
    return {
        "program": program,
        "stores": stores,
        "item": item,
        "positions": positions,
        "receipt": receipt,
        "run": proposed,
    }


def build_markdown_tier_network() -> Dict[str, Any]:
    """Four stores, three size curves of different width, and six positions whose
    broken-size ratios sit exactly on each markdown tier edge."""
    set_clock()
    program = new_program()
    s1 = new_store(program["id"], "0101")
    s2 = new_store(program["id"], "0102")
    s3 = new_store(program["id"], "0103")
    s4 = new_store(program["id"], "0104")
    new_plan(s1["id"], 4, 3, 4, 12)
    new_plan(s2["id"], 2, 3, 4, 8)
    new_plan(s3["id"], 1, 4, 5, 8)
    new_plan(s4["id"], 1, 2, 3, 2)
    four = new_profile(program["id"], "TOP-4SZ", CURVE_TOP_4SZ)
    six = new_profile(program["id"], "TOP-6SZ", CURVE_TOP_6SZ)
    five = new_profile(program["id"], "TOP-5SZ", CURVE_TOP_5SZ_EVEN)
    i1 = new_item(program["id"], four["id"], "SKU-1001", "ST-100", "SEASONAL")
    i2 = new_item(program["id"], six["id"], "SKU-2001", "ST-200", "SEASONAL")
    i3 = new_item(program["id"], five["id"], "SKU-3001", "ST-300", "SEASONAL")
    activate(program["id"])
    positions = {
        "SKU-1001@0101": new_position(
            s1["id"], i1["id"], 9, {"M": 4, "L": 3, "XL": 2}, 8, 40, 3, 10
        ),
        "SKU-1001@0102": new_position(
            s2["id"], i1["id"], 7, {"M": 4, "L": 3}, 6, 30, 3, 10
        ),
        "SKU-1001@0103": new_position(
            s3["id"], i1["id"], 4, {"M": 4}, 4, 20, 2, 8
        ),
        "SKU-2001@0103": new_position(
            s3["id"], i2["id"], 6, {"XS": 1, "M": 2, "L": 2, "XL": 1}, 4, 20, 2, 8
        ),
        "SKU-2001@0104": new_position(
            s4["id"], i2["id"], 7, {"S": 2, "M": 2, "L": 2, "XL": 1}, 4, 20, 2, 8
        ),
        "SKU-3001@0102": new_position(
            s2["id"], i3["id"], 8, {"S": 2, "M": 2, "L": 2, "XL": 2}, 6, 30, 3, 10
        ),
    }
    return {
        "program": program,
        "stores": {"0101": s1, "0102": s2, "0103": s3, "0104": s4},
        "items": {"SKU-1001": i1, "SKU-2001": i2, "SKU-3001": i3},
        "positions": positions,
    }


def build_size_split_network() -> Dict[str, Any]:
    """Two SKUs on two different curves: a skewed five-size curve fed by a receipt
    of a single size, and a curve with a tie at the top."""
    program = new_program()
    s1 = new_store(program["id"], "0101")
    s2 = new_store(program["id"], "0102")
    new_plan(s1["id"], 4, 3, 4, 12)
    new_plan(s2["id"], 2, 3, 4, 8)
    skew = new_profile(program["id"], "TOP-5SZ", CURVE_TOP_5SZ_SKEW)
    tie = new_profile(program["id"], "TOP-TIE", CURVE_TOP_TIE)
    i1 = new_item(program["id"], skew["id"], "SKU-1001", "ST-100", "SEASONAL")
    i2 = new_item(program["id"], tie["id"], "SKU-2001", "ST-200", "SEASONAL")
    activate(program["id"])
    positions = {
        "SKU-1001@0101": new_position(
            s1["id"], i1["id"], 4, {"S": 1, "M": 2, "L": 1}, 12, 48, 5, 20
        ),
        "SKU-2001@0102": new_position(
            s2["id"], i2["id"], 6, {"S": 1, "M": 2, "L": 2, "XL": 1}, 8, 24, 4, 12
        ),
    }
    receipts = {
        "ASN-C701": new_receipt(program["id"], i1["id"], "ASN-C701", 16, {"M": 16}),
        "ASN-C702": new_receipt(
            program["id"], i2["id"], "ASN-C702", 10, {"S": 3, "M": 3, "L": 3, "XL": 1}
        ),
    }
    return {
        "program": program,
        "stores": {"0101": s1, "0102": s2},
        "items": {"SKU-1001": i1, "SKU-2001": i2},
        "positions": positions,
        "receipts": receipts,
    }


def build_consolidation_choice_network() -> Dict[str, Any]:
    """Seven stores whose sell-through, grade and fixture headroom disagree about
    which one should receive a consolidation."""
    set_clock()
    program = new_program()
    specs = [
        ("0101", {"grade": "A", "grade_index_bp": 13000, "cluster_code": "URBAN",
                  "freight_flat_usd": 41.00, "historical_sell_through_bp": 6500}),
        ("0102", {"grade": "B", "grade_index_bp": 10000, "cluster_code": "URBAN",
                  "freight_flat_usd": 38.00, "historical_sell_through_bp": 9000}),
        ("0103", {"grade": "C", "grade_index_bp": 12500, "cluster_code": "SUBURBAN",
                  "freight_flat_usd": 42.00, "historical_sell_through_bp": 8000}),
        ("0104", {"grade": "D", "grade_index_bp": 11000, "cluster_code": "SUBURBAN",
                  "freight_flat_usd": 55.00, "historical_sell_through_bp": 8000}),
        ("0105", {"grade": "A", "grade_index_bp": 13000, "cluster_code": "URBAN",
                  "freight_flat_usd": 39.00, "historical_sell_through_bp": 8000}),
        ("0106", {"grade": "A", "grade_index_bp": 13000, "cluster_code": "URBAN",
                  "freight_flat_usd": 40.00, "historical_sell_through_bp": 8000}),
        ("0107", {"grade": "A", "grade_index_bp": 13000, "cluster_code": "URBAN",
                  "freight_flat_usd": 37.00, "historical_sell_through_bp": 9500}),
    ]
    stores = {code: new_store(program["id"], code, **attrs) for code, attrs in specs}
    new_plan(stores["0101"]["id"], 4, 3, 4, 12)
    new_plan(stores["0102"]["id"], 2, 3, 4, 8)
    for code in ["0103", "0104", "0105", "0106", "0107"]:
        new_plan(stores[code]["id"], 1, 4, 5, 6)
    profile = new_profile(program["id"], "TOP-4SZ", CURVE_TOP_4SZ)
    i1 = new_item(program["id"], profile["id"], "SKU-1001", "ST-100", "SEASONAL")
    i2 = new_item(program["id"], profile["id"], "SKU-2001", "ST-200", "SEASONAL")
    activate(program["id"])
    positions = {
        "SKU-1001@0101": new_position(
            stores["0101"]["id"], i1["id"], 4, {"M": 3, "L": 1}, 12, 48, 9, 30
        ),
        "SKU-1001@0102": new_position(
            stores["0102"]["id"], i1["id"], 22,
            {"S": 5, "M": 9, "L": 6, "XL": 2}, 8, 24, 5, 16,
        ),
    }
    for code in ["0103", "0104", "0105", "0106", "0107"]:
        positions[f"SKU-1001@{code}"] = new_position(
            stores[code]["id"], i1["id"], 8,
            {"S": 2, "M": 3, "L": 2, "XL": 1}, 8, 20, 3, 6,
        )
    positions["SKU-2001@0101"] = new_position(
        stores["0101"]["id"], i2["id"], 0, {}, 5, 20, 2, 9
    )
    positions["SKU-2001@0103"] = new_position(
        stores["0103"]["id"], i2["id"], 4,
        {"S": 1, "M": 1, "L": 1, "XL": 1}, 4, 20, 2, 8,
    )
    move_store(stores["0107"]["id"], "REMODEL")
    return {
        "program": program,
        "stores": stores,
        "items": {"SKU-1001": i1, "SKU-2001": i2},
        "positions": positions,
    }


def build_ladder_network() -> Dict[str, Any]:
    """Four stores in one program plus a single store in a second program, one of
    the four taken to CLOSING, so a transfer creation can be walked down the
    priority order one repaired field at a time."""
    set_clock()
    program = new_program()
    s1 = new_store(program["id"], "0101")
    s2 = new_store(program["id"], "0102")
    s3 = new_store(program["id"], "0103")
    s4 = new_store(program["id"], "0104")
    new_plan(s1["id"], 4, 3, 4, 12)
    new_plan(s2["id"], 2, 3, 4, 8)
    new_plan(s3["id"], 1, 4, 5, 8)
    new_plan(s4["id"], 1, 4, 5, 6)
    profile = new_profile(program["id"], "TOP-4SZ", CURVE_TOP_4SZ)
    item = new_item(program["id"], profile["id"], "SKU-1001", "ST-100", "SEASONAL")
    activate(program["id"])
    positions = {
        "0101": new_position(
            s1["id"], item["id"], 20, {"S": 5, "M": 7, "L": 6, "XL": 2}, 8, 24, 5, 16
        ),
        "0102": new_position(s2["id"], item["id"], 6, {"M": 4, "L": 2}, 6, 20, 3, 10),
        "0103": new_position(
            s3["id"], item["id"], 4, {"S": 1, "M": 2, "L": 1}, 4, 20, 2, 8
        ),
        "0104": new_position(
            s4["id"], item["id"], 4, {"S": 1, "M": 1, "L": 1, "XL": 1}, 4, 20, 2, 8
        ),
    }
    move_store(s3["id"], "CLOSING")
    other_program = new_program(name="FA26 Kids Tops", banner_code="SOUTH")
    other_store = new_store(
        other_program["id"], "0201", grade="B", grade_index_bp=10000,
        cluster_code="URBAN", freight_flat_usd=40.00, historical_sell_through_bp=6000,
    )
    return {
        "program": program,
        "stores": {"0101": s1, "0102": s2, "0103": s3, "0104": s4},
        "item": item,
        "positions": positions,
        "other_program": other_program,
        "other_store": other_store,
    }


def build_freight_gate_network() -> Dict[str, Any]:
    """A program with a demanding freight-worthiness threshold, one broken store
    and one full store, so a mandated sweep-up and a discretionary rebalance can be
    compared side by side."""
    set_clock()
    program = new_program(transfer_min_ratio_bp=20000)
    s1 = new_store(program["id"], "0101")
    s2 = new_store(program["id"], "0102")
    new_plan(s1["id"], 4, 3, 4, 12)
    new_plan(s2["id"], 2, 3, 4, 8)
    profile = new_profile(program["id"], "TOP-4SZ", CURVE_TOP_4SZ)
    item = new_item(program["id"], profile["id"], "SKU-1001", "ST-100", "SEASONAL")
    activate(program["id"])
    positions = {
        "0101": new_position(s1["id"], item["id"], 4, {"M": 3, "L": 1}, 12, 48, 9, 30),
        "0102": new_position(
            s2["id"], item["id"], 20, {"S": 5, "M": 7, "L": 6, "XL": 2}, 8, 24, 5, 16
        ),
    }
    return {
        "program": program,
        "stores": {"0101": s1, "0102": s2},
        "item": item,
        "positions": positions,
    }


def build_exact_fill_network() -> Dict[str, Any]:
    """Four stores whose total forward-looking need is exactly the size of the
    receipt about to be allocated."""
    set_clock()
    program = new_program()
    s1 = new_store(program["id"], "0101")
    s2 = new_store(program["id"], "0102")
    s3 = new_store(program["id"], "0103")
    s4 = new_store(program["id"], "0104")
    new_plan(s1["id"], 4, 3, 4, 12)
    new_plan(s2["id"], 2, 3, 4, 8)
    new_plan(s3["id"], 1, 4, 5, 8)
    new_plan(s4["id"], 1, 4, 5, 6)
    profile = new_profile(program["id"], "TOP-4SZ", CURVE_TOP_4SZ)
    item = new_item(program["id"], profile["id"], "SKU-1001", "ST-100", "SEASONAL")
    activate(program["id"])
    positions = {
        "0101": new_position(
            s1["id"], item["id"], 6, {"M": 4, "L": 2}, 12, 48, 9, 30, on_order_units=4
        ),
        "0102": new_position(
            s2["id"], item["id"], 20, {"S": 5, "M": 7, "L": 6, "XL": 2}, 8, 24, 5, 16
        ),
        "0103": new_position(s3["id"], item["id"], 2, {"M": 1, "L": 1}, 8, 20, 3, 6),
        "0104": new_position(s4["id"], item["id"], 0, {}, 6, 20, 2, 5),
    }
    receipt = new_receipt(
        program["id"], item["id"], "ASN-V301", 44,
        {"S": 8, "M": 17, "L": 14, "XL": 5},
    )
    return {
        "program": program,
        "stores": {"0101": s1, "0102": s2, "0103": s3, "0104": s4},
        "item": item,
        "positions": positions,
        "receipt": receipt,
    }
