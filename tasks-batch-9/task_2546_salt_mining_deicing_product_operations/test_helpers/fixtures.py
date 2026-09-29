"""
Composite setup helpers for the Salt Deicing Operations API.

The database is empty before every test, so each helper here builds the state it
needs from scratch through published endpoints only — there is no seeding back
door. Helpers are deliberately lenient about status codes (they use
get_success_data) because the status code of a *setup* call is not what the test
under way is asserting.

Five tiers are provided:

1. Primitives — one call each (create_mine, create_depot, file_inspection, ...).
2. State progression — walk one entity to a named state (producing_panel,
   hoisted_run, passed_batch).
3. Entity hierarchy — build a parent chain (lot_at_depot, active_contract).
4. Full-lifecycle shortcuts — the canonical mine-to-order chain (standard_world).
5. Targeting helpers — accumulate toward a threshold or reach a terminal state
   (depot_at_surge_edge, shorted_order, accrued_penalty_world).

Every numeric default matches the PRD-derived baseline used throughout the suite:
a 24,000 t/day mine, a 1,000,000 t panel at 60 % extraction / 95.0 % NaCl /
5.0 % insolubles with pillar recovery allowed, a 6,000 t run over a six-hour
window, a COARSE HIGHWAY_DEICING batch of 6,000 t at 2.0 % moisture, and a
40,000 t covered depot.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories as f
from .api_client import SaltApiClient
from .constants import (
    ACTION_CITE,
    CLOCK_EPOCH,
    DECISION_PASS,
    FINDING_DEFECT,
    OUTCOME_AWARD,
)
from .test_users import (
    COMPLIANCE,
    CONTRACT_ADMIN,
    CONTRACT_ADMIN_ALT,
    GROUND_CONTROL,
    LAB_LEAD,
    LAB_TECH,
    LOGISTICS,
    MINE_PLANNER,
)

# ─── Tier 1: primitives ───────────────────────────────


def set_clock(api: SaltApiClient, to_iso8601: str, headers: Dict[str, str] = MINE_PLANNER) -> None:
    get_success_data(api.set_clock(to_iso8601, headers))


def reset_clock(api: SaltApiClient) -> None:
    """Put the clock back on the documented epoch of PRD §2.5."""
    set_clock(api, CLOCK_EPOCH)


def create_mine(api: SaltApiClient, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(api.create_mine(f.mine_payload(**kwargs), MINE_PLANNER))


def create_panel(api: SaltApiClient, mine_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_panel(f.panel_payload(mine_id, **kwargs), MINE_PLANNER)
    )


def develop(api: SaltApiClient, panel_id: str) -> Dict[str, Any]:
    return get_success_data(api.develop_panel(panel_id, MINE_PLANNER))


def start_production(api: SaltApiClient, panel_id: str) -> Dict[str, Any]:
    return get_success_data(api.start_production(panel_id, MINE_PLANNER))


def file_inspection(
    api: SaltApiClient,
    panel_id: str,
    finding: str,
    headers: Dict[str, str] = GROUND_CONTROL,
    **kwargs: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_inspection(f.inspection_payload(panel_id, finding, **kwargs), headers)
    )


def cite_mine(api: SaltApiClient, mine_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.compliance_action(mine_id, f.compliance_action_payload(ACTION_CITE, **kwargs), COMPLIANCE)
    )


def compliance_action(
    api: SaltApiClient, mine_id: str, action: str, **kwargs: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.compliance_action(mine_id, f.compliance_action_payload(action, **kwargs), COMPLIANCE)
    )


def set_hoist_status(api: SaltApiClient, mine_id: str, hoist_state: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.set_hoist_status(mine_id, f.hoist_status_payload(hoist_state, **kwargs), MINE_PLANNER)
    )


def mine_version(api: SaltApiClient, mine_id: str) -> int:
    """Read the mine's current `version` — the value `expected_mine_version` wants."""
    return int(get_success_data(api.get_mine(mine_id, MINE_PLANNER))["version"])


def contract_version(api: SaltApiClient, contract_id: str) -> int:
    return int(get_success_data(api.get_contract(contract_id, CONTRACT_ADMIN))["version"])


def lot_version(api: SaltApiClient, lot_id: str) -> int:
    return int(get_success_data(api.get_lot(lot_id, LOGISTICS))["version"])


def create_run(
    api: SaltApiClient,
    mine_id: str,
    panel_id: str,
    expected_mine_version: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    version = (
        mine_version(api, mine_id) if expected_mine_version is None else expected_mine_version
    )
    payload = f.run_payload(mine_id, panel_id, version, **kwargs)
    return get_success_data(api.create_run(payload, MINE_PLANNER))


def hoist(api: SaltApiClient, run_id: str, hoisted_tons: float) -> Dict[str, Any]:
    return get_success_data(
        api.hoist_run(run_id, f.hoist_payload(hoisted_tons), MINE_PLANNER)
    )


def create_depot(api: SaltApiClient, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(api.create_depot(f.depot_payload(**kwargs), LOGISTICS))


def set_posture(api: SaltApiClient, depot_id: str, depot_state: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.set_posture(depot_id, f.posture_payload(depot_state, **kwargs), LOGISTICS)
    )


def create_batch(
    api: SaltApiClient,
    production_run_id: str,
    depot_id: str,
    headers: Dict[str, str] = LAB_TECH,
    **kwargs: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_batch(f.batch_payload(production_run_id, depot_id, **kwargs), headers)
    )


def decide_batch(
    api: SaltApiClient,
    batch_id: str,
    decision: str,
    headers: Dict[str, str] = LAB_LEAD,
    **kwargs: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.qc_decision(batch_id, f.qc_decision_payload(decision, **kwargs), headers)
    )


def create_forecast(api: SaltApiClient, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_forecast(f.forecast_payload(**kwargs), CONTRACT_ADMIN)
    )


def create_contract(api: SaltApiClient, season_forecast_id: str, **kwargs: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_contract(f.contract_payload(season_forecast_id, **kwargs), CONTRACT_ADMIN)
    )


def submit_contract(api: SaltApiClient, contract_id: str) -> Dict[str, Any]:
    return get_success_data(api.submit_contract(contract_id, CONTRACT_ADMIN))


def decide_contract(api: SaltApiClient, contract_id: str, outcome: str = OUTCOME_AWARD) -> Dict[str, Any]:
    """
    Decided by a second administrator: "the deciding X-User-ID must not equal the
    submitted_by_user_id".
    """
    return get_success_data(
        api.decide_contract(contract_id, f.decision_payload(outcome), CONTRACT_ADMIN_ALT)
    )


def activate_contract(api: SaltApiClient, contract_id: str) -> Dict[str, Any]:
    return get_success_data(api.activate_contract(contract_id, CONTRACT_ADMIN))


def create_order(
    api: SaltApiClient,
    bid_contract_id: str,
    depot_id: str,
    expected_bid_contract_version: Optional[int] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    version = (
        contract_version(api, bid_contract_id)
        if expected_bid_contract_version is None
        else expected_bid_contract_version
    )
    payload = f.order_payload(bid_contract_id, depot_id, version, **kwargs)
    return get_success_data(api.create_order(payload, LOGISTICS))


def allocate(api: SaltApiClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(api.allocate_order(order_id, LOGISTICS))


def reserve_manually(
    api: SaltApiClient,
    delivery_order_id: str,
    stockpile_lot_id: str,
    tons: float,
    expected_stockpile_lot_version: Optional[int] = None,
) -> Dict[str, Any]:
    version = (
        lot_version(api, stockpile_lot_id)
        if expected_stockpile_lot_version is None
        else expected_stockpile_lot_version
    )
    payload = f.allocation_payload(delivery_order_id, stockpile_lot_id, tons, version)
    return get_success_data(api.create_allocation(payload, LOGISTICS))


def create_shipment(
    api: SaltApiClient,
    stockpile_lot_id: str,
    origin_depot_id: str,
    destination_depot_id: str,
    tons: float,
    **kwargs: Any,
) -> Dict[str, Any]:
    payload = f.shipment_payload(
        stockpile_lot_id, origin_depot_id, destination_depot_id, tons, **kwargs
    )
    return get_success_data(api.create_shipment(payload, LOGISTICS))


# ─── Reverse-reachability reads (PRD §2.10) ───────────


def list_rows(response) -> List[Dict[str, Any]]:
    rows, _meta = validate_paginated(response)
    return rows


def lots_of_batch(api: SaltApiClient, treatment_batch_id: str) -> List[Dict[str, Any]]:
    """
    A minted lot "has no creation response of its own"; it is discoverable only
    through the lot list filtered by the batch that minted it.
    """
    return list_rows(
        api.list_lots(LOGISTICS, {"treatment_batch_id": treatment_batch_id, "limit": 100})
    )


def lot_of_batch(api: SaltApiClient, treatment_batch_id: str) -> Dict[str, Any]:
    rows = lots_of_batch(api, treatment_batch_id)
    assert len(rows) == 1, f"expected one minted lot, found {len(rows)}"
    return rows[0]


def lots_at_depot(api: SaltApiClient, depot_id: str) -> List[Dict[str, Any]]:
    return list_rows(api.list_lots(LOGISTICS, {"depot_id": depot_id, "limit": 100}))


def allocations_of_order(api: SaltApiClient, delivery_order_id: str) -> List[Dict[str, Any]]:
    return list_rows(
        api.list_allocations(LOGISTICS, {"delivery_order_id": delivery_order_id, "limit": 100})
    )


def runs_of_mine(api: SaltApiClient, mine_id: str, **filters: Any) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {"mine_id": mine_id, "limit": 100}
    params.update(filters)
    return list_rows(api.list_runs(MINE_PLANNER, params))


# ─── Refresh helpers ──────────────────────────────────


def refresh_mine(api: SaltApiClient, mine_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_mine(mine_id, MINE_PLANNER))


def refresh_panel(api: SaltApiClient, panel_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_panel(panel_id, MINE_PLANNER))


def refresh_run(api: SaltApiClient, run_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_run(run_id, MINE_PLANNER))


def refresh_batch(api: SaltApiClient, batch_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_batch(batch_id, LAB_TECH))


def refresh_depot(api: SaltApiClient, depot_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_depot(depot_id, LOGISTICS))


def refresh_lot(api: SaltApiClient, lot_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_lot(lot_id, LOGISTICS))


def refresh_shipment(api: SaltApiClient, shipment_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_shipment(shipment_id, LOGISTICS))


def refresh_forecast(api: SaltApiClient, forecast_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_forecast(forecast_id, CONTRACT_ADMIN))


def refresh_contract(api: SaltApiClient, contract_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_contract(contract_id, CONTRACT_ADMIN))


def refresh_order(api: SaltApiClient, order_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_order(order_id, LOGISTICS))


def refresh_allocation(api: SaltApiClient, allocation_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_allocation(allocation_id, LOGISTICS))


def hoist_capacity(api: SaltApiClient, mine_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_hoist_capacity(mine_id, MINE_PLANNER))


def storage_posture(api: SaltApiClient, depot_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_storage_posture(depot_id, LOGISTICS))


def contract_ledger(api: SaltApiClient, contract_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_contract_ledger(contract_id, CONTRACT_ADMIN))


# ─── Tier 2: state progression ────────────────────────


def mine_with_producing_panel(
    api: SaltApiClient,
    mine_kwargs: Optional[Dict[str, Any]] = None,
    panel_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Walk a panel PLANNED -> DEVELOPED -> PRODUCING, which is the precondition for
    scheduling any run ("needs the target panel PRODUCING").
    """
    mine = create_mine(api, **(mine_kwargs or {}))
    panel = create_panel(api, mine["id"], **(panel_kwargs or {}))
    develop(api, panel["id"])
    panel = start_production(api, panel["id"])
    return {"mine": refresh_mine(api, mine["id"]), "panel": panel}


def scheduled_run(
    api: SaltApiClient,
    mine_kwargs: Optional[Dict[str, Any]] = None,
    panel_kwargs: Optional[Dict[str, Any]] = None,
    **run_kwargs: Any,
) -> Dict[str, Any]:
    world = mine_with_producing_panel(api, mine_kwargs, panel_kwargs)
    run = create_run(api, world["mine"]["id"], world["panel"]["id"], **run_kwargs)
    world["run"] = run
    world["mine"] = refresh_mine(api, world["mine"]["id"])
    return world


def hoisted_run(
    api: SaltApiClient,
    mine_kwargs: Optional[Dict[str, Any]] = None,
    panel_kwargs: Optional[Dict[str, Any]] = None,
    hoisted_tons: float = 6000,
    **run_kwargs: Any,
) -> Dict[str, Any]:
    """A run at HOISTED, the state a treatment batch may be opened against."""
    world = scheduled_run(api, mine_kwargs, panel_kwargs, **run_kwargs)
    world["run"] = hoist(api, world["run"]["id"], hoisted_tons)
    world["mine"] = refresh_mine(api, world["mine"]["id"])
    world["panel"] = refresh_panel(api, world["panel"]["id"])
    return world


def suspend_by_defect(api: SaltApiClient, panel_id: str, **kwargs: Any) -> Dict[str, Any]:
    """File the DEFECT inspection that fires the four-hop cascade of PRD §3.3."""
    return file_inspection(api, panel_id, FINDING_DEFECT, **kwargs)


# ─── Tier 3: entity hierarchy ─────────────────────────


def mint_lot(
    api: SaltApiClient,
    production_run_id: str,
    depot_id: str,
    **batch_kwargs: Any,
) -> Dict[str, Any]:
    """
    Open a batch as one lab operator and pass it as another, which is the only
    operation in the system that creates tonnage. Returns the batch and the minted
    lot, the latter found through the lot list filtered by `treatment_batch_id`.
    """
    batch = create_batch(api, production_run_id, depot_id, **batch_kwargs)
    batch = decide_batch(api, batch["id"], DECISION_PASS)
    return {"batch": batch, "lot": lot_of_batch(api, batch["id"])}


def lot_at_depot(
    api: SaltApiClient,
    mine_kwargs: Optional[Dict[str, Any]] = None,
    panel_kwargs: Optional[Dict[str, Any]] = None,
    depot_kwargs: Optional[Dict[str, Any]] = None,
    run_kwargs: Optional[Dict[str, Any]] = None,
    hoisted_tons: float = 6000,
    **batch_kwargs: Any,
) -> Dict[str, Any]:
    """
    The whole mining-to-storage chain: mine, producing panel, hoisted run, depot,
    treated batch and the stockpile lot its quality-control pass minted.
    """
    world = hoisted_run(
        api,
        mine_kwargs,
        panel_kwargs,
        hoisted_tons=hoisted_tons,
        **(run_kwargs or {}),
    )
    world["depot"] = create_depot(api, **(depot_kwargs or {}))
    minted = mint_lot(api, world["run"]["id"], world["depot"]["id"], **batch_kwargs)
    world["batch"] = minted["batch"]
    world["lot"] = minted["lot"]
    world["depot"] = refresh_depot(api, world["depot"]["id"])
    world["run"] = refresh_run(api, world["run"]["id"])
    return world


def active_contract(
    api: SaltApiClient,
    forecast_kwargs: Optional[Dict[str, Any]] = None,
    contract_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Draft, submit, award and activate a contract. Activation needs pre-season
    coverage already on the ground, so callers must mint the lots first.
    """
    forecast = create_forecast(api, **(forecast_kwargs or {}))
    contract = create_contract(api, forecast["id"], **(contract_kwargs or {}))
    submit_contract(api, contract["id"])
    decide_contract(api, contract["id"], OUTCOME_AWARD)
    contract = activate_contract(api, contract["id"])
    return {"forecast": forecast, "contract": contract}


def awarded_contract(
    api: SaltApiClient,
    forecast_kwargs: Optional[Dict[str, Any]] = None,
    contract_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Stop one step short of ACTIVE, at AWARDED — the state activation requires."""
    forecast = create_forecast(api, **(forecast_kwargs or {}))
    contract = create_contract(api, forecast["id"], **(contract_kwargs or {}))
    submit_contract(api, contract["id"])
    contract = decide_contract(api, contract["id"], OUTCOME_AWARD)
    return {"forecast": forecast, "contract": contract}


# ─── Tier 4: full-lifecycle shortcuts ─────────────────


def standard_world(
    api: SaltApiClient,
    mine_kwargs: Optional[Dict[str, Any]] = None,
    panel_kwargs: Optional[Dict[str, Any]] = None,
    depot_kwargs: Optional[Dict[str, Any]] = None,
    run_kwargs: Optional[Dict[str, Any]] = None,
    batch_kwargs: Optional[Dict[str, Any]] = None,
    forecast_kwargs: Optional[Dict[str, Any]] = None,
    contract_kwargs: Optional[Dict[str, Any]] = None,
    hoisted_tons: float = 6000,
) -> Dict[str, Any]:
    """
    The canonical chain from seam to active contract: mine, producing panel, hoisted
    run, depot, passed batch, minted lot, forecast and an ACTIVE contract whose
    pre-season coverage the minted lot satisfies. No delivery order yet.
    """
    world = lot_at_depot(
        api,
        mine_kwargs=mine_kwargs,
        panel_kwargs=panel_kwargs,
        depot_kwargs=depot_kwargs,
        run_kwargs=run_kwargs,
        hoisted_tons=hoisted_tons,
        **(batch_kwargs or {}),
    )
    world.update(active_contract(api, forecast_kwargs, contract_kwargs))
    return world


def requested_order(
    api: SaltApiClient,
    order_kwargs: Optional[Dict[str, Any]] = None,
    **world_kwargs: Any,
) -> Dict[str, Any]:
    """standard_world plus one REQUESTED delivery order against the active contract."""
    world = standard_world(api, **world_kwargs)
    world["order"] = create_order(
        api, world["contract"]["id"], world["depot"]["id"], **(order_kwargs or {})
    )
    world["contract"] = refresh_contract(api, world["contract"]["id"])
    return world


def allocated_order(
    api: SaltApiClient,
    order_kwargs: Optional[Dict[str, Any]] = None,
    **world_kwargs: Any,
) -> Dict[str, Any]:
    """A fully allocated order: the waterfall covered the whole `requested_tons`."""
    world = requested_order(api, order_kwargs, **world_kwargs)
    world["order"] = allocate(api, world["order"]["id"])
    world["lot"] = refresh_lot(api, world["lot"]["id"])
    return world


# ─── Tier 5: accumulation and terminal targeting ──────


def shorted_order(
    api: SaltApiClient,
    requested_tons: float = 2000,
    order_kwargs: Optional[Dict[str, Any]] = None,
    **world_kwargs: Any,
) -> Dict[str, Any]:
    """
    An order the waterfall could only partly fill, so it lands on SHORTED with an
    ACCRUED penalty and the contract ledger already re-derived.
    """
    kwargs = dict(order_kwargs or {})
    kwargs["requested_tons"] = requested_tons
    world = requested_order(api, kwargs, **world_kwargs)
    world["order"] = allocate(api, world["order"]["id"])
    world["contract"] = refresh_contract(api, world["contract"]["id"])
    world["lot"] = refresh_lot(api, world["lot"]["id"])
    return world


def delivered_order(
    api: SaltApiClient,
    order_kwargs: Optional[Dict[str, Any]] = None,
    **world_kwargs: Any,
) -> Dict[str, Any]:
    """An allocated order carried through delivery, so its invoice is frozen."""
    world = allocated_order(api, order_kwargs, **world_kwargs)
    world["order"] = get_success_data(api.deliver_order(world["order"]["id"], LOGISTICS))
    world["contract"] = refresh_contract(api, world["contract"]["id"])
    world["lot"] = refresh_lot(api, world["lot"]["id"])
    return world
