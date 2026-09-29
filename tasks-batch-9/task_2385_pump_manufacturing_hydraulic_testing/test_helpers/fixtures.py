"""Composite setup helpers.

The API server is restarted before every individual test, so every fixture here
builds its preconditions from an empty database using nothing but public
endpoints.  The helpers are layered:

* atoms, one create call each;
* `setup_master_data`, the foundry / model / pattern / configuration world that
  almost every scenario needs;
* lifecycle shortcuts that walk an aggregate to a named state
  (approved selection, accepted lot, assembled order, certified run, shipped
  package, claim under adjudication);
* accumulation helpers that drive a counter to a chosen threshold;
* terminal-state helpers (settled claim, closed order).

Setup calls go through `get_success_data`, so a broken precondition fails with
the API's own error identifier rather than as an opaque KeyError.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import constants as K
from . import factories as F
from . import test_users as U
from .api_client import ApiClient

World = Dict[str, Any]


# ─────────────────────────────────────────────────────────────────────────────
# Tier 1 — atoms
# ─────────────────────────────────────────────────────────────────────────────
def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock (PRD 2.4)."""
    return get_success_data(
        api.set_clock(F.clock_payload(to_iso8601), U.PLATFORM_ADMIN)
    )


def create_foundry(api: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_foundry(F.foundry_payload(**overrides), U.PLATFORM_ADMIN)
    )


def create_pump_model(api: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_pump_model(F.pump_model_payload(**overrides), U.PLATFORM_ADMIN)
    )


def create_pattern_asset(
    api: ApiClient, pump_model_id: str, foundry_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_pattern_asset(
            F.pattern_asset_payload(pump_model_id, foundry_id, **overrides),
            U.PLATFORM_ADMIN,
        )
    )


def create_material_seal_config(
    api: ApiClient, pump_model_id: str, **overrides
) -> Dict[str, Any]:
    return get_success_data(
        api.create_material_seal_config(
            F.material_seal_config_payload(pump_model_id, **overrides),
            U.PLATFORM_ADMIN,
        )
    )


def create_duty_application(api: ApiClient, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_duty_application(
            F.duty_application_payload(**overrides), U.APPLICATION_ENGINEER
        )
    )


def create_repair_kit(api: ApiClient, pump_model_id: str, **overrides) -> Dict[str, Any]:
    return get_success_data(
        api.create_repair_kit(
            F.repair_kit_payload(pump_model_id, **overrides), U.PLATFORM_ADMIN
        )
    )


def reread_duty_application(api: ApiClient, duty_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_duty_application(duty_id, U.APPLICATION_ENGINEER))


def reread_selection(api: ApiClient, selection_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_selection(selection_id, U.APPLICATION_ENGINEER))


def reread_pump_model(api: ApiClient, model_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_pump_model(model_id, U.PLATFORM_ADMIN))


def reread_pattern_asset(api: ApiClient, pattern_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_pattern_asset(pattern_id, U.PLATFORM_ADMIN))


def reread_casting_lot(api: ApiClient, lot_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_casting_lot(lot_id, U.QUALITY_INSPECTOR))


def reread_casting_defect(api: ApiClient, defect_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_casting_defect(defect_id, U.QUALITY_INSPECTOR))


def reread_build_order(api: ApiClient, build_order_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_build_order(build_order_id, U.PRODUCTION_PLANNER))


def reread_test_run(api: ApiClient, test_run_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_test_run(test_run_id, U.TEST_ENGINEER))


def reread_pump_package(api: ApiClient, package_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_pump_package(package_id, U.PRODUCTION_PLANNER))


def reread_repair_kit(api: ApiClient, kit_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_repair_kit(kit_id, U.PRODUCTION_PLANNER))


def reread_kit_allocation(api: ApiClient, allocation_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_kit_allocation(allocation_id, U.PRODUCTION_PLANNER))


def reread_warranty_claim(api: ApiClient, claim_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_warranty_claim(claim_id, U.WARRANTY_ADJUDICATOR))


# ─────────────────────────────────────────────────────────────────────────────
# Tier 2 — the master-data world
# ─────────────────────────────────────────────────────────────────────────────
def setup_master_data(
    api: ApiClient,
    *,
    foundry: Optional[Dict[str, Any]] = None,
    model: Optional[Dict[str, Any]] = None,
    pattern: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    with_pattern: bool = True,
    with_config: bool = True,
) -> World:
    """One active foundry, one orderable model, one qualified pattern, one config.

    The returned dictionary also carries `foundry_headers`, the only correct way
    to act as the foundry partner that backs this foundry.
    """
    foundry_row = create_foundry(api, **(foundry or {}))
    model_row = create_pump_model(api, **(model or {}))
    world: World = {
        "foundry": foundry_row,
        "model": model_row,
        "foundry_headers": U.make_foundry_partner_headers(foundry_row["id"]),
        "pattern": None,
        "config": None,
    }
    if with_pattern:
        world["pattern"] = create_pattern_asset(
            api, model_row["id"], foundry_row["id"], **(pattern or {})
        )
    if with_config:
        world["config"] = create_material_seal_config(
            api, model_row["id"], **(config or {})
        )
    return world


# ─────────────────────────────────────────────────────────────────────────────
# Tier 3 — selection lifecycle
# ─────────────────────────────────────────────────────────────────────────────
def setup_draft_selection(
    api: ApiClient,
    world: Optional[World] = None,
    *,
    duty: Optional[Dict[str, Any]] = None,
    engineer_headers: Optional[Dict[str, str]] = None,
    **world_kwargs,
) -> World:
    """A DRAFT Selection on a fresh duty application."""
    ctx = dict(world if world is not None else setup_master_data(api, **world_kwargs))
    duty_row = create_duty_application(api, **(duty or {}))
    selection = get_success_data(
        api.create_selection(
            F.selection_payload(
                duty_row["id"],
                ctx["model"]["id"],
                ctx["config"]["id"],
                duty_row["version"],
            ),
            engineer_headers or U.APPLICATION_ENGINEER,
        )
    )
    ctx["duty"] = reread_duty_application(api, duty_row["id"])
    ctx["duty_at_create"] = duty_row
    ctx["selection"] = selection
    return ctx


def setup_proposed_selection(
    api: ApiClient,
    world: Optional[World] = None,
    *,
    engineer_headers: Optional[Dict[str, str]] = None,
    **kwargs,
) -> World:
    headers = engineer_headers or U.APPLICATION_ENGINEER
    ctx = setup_draft_selection(api, world, engineer_headers=headers, **kwargs)
    get_success_data(api.propose_selection(ctx["selection"]["id"], headers))
    ctx["selection"] = reread_selection(api, ctx["selection"]["id"])
    ctx["proposer_headers"] = headers
    return ctx


def setup_approved_selection(
    api: ApiClient,
    world: Optional[World] = None,
    *,
    approver_headers: Optional[Dict[str, str]] = None,
    **kwargs,
) -> World:
    """An APPROVED Selection; the duty application is SELECTION_LOCKED."""
    ctx = setup_proposed_selection(api, world, **kwargs)
    get_success_data(
        api.approve_selection(
            ctx["selection"]["id"], approver_headers or U.HYDRAULIC_APPROVER
        )
    )
    ctx["selection"] = reread_selection(api, ctx["selection"]["id"])
    ctx["duty"] = reread_duty_application(api, ctx["duty"]["id"])
    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# Tier 3 — casting lifecycle
# ─────────────────────────────────────────────────────────────────────────────
def pour_casting_lot(api: ApiClient, ctx: World, **overrides) -> Dict[str, Any]:
    """Pour a lot from the world's pattern, acting as that foundry's partner."""
    return get_success_data(
        api.create_casting_lot(
            F.casting_lot_payload(
                ctx["pattern"]["id"], ctx["foundry"]["id"], **overrides
            ),
            ctx["foundry_headers"],
        )
    )


def report_defect(
    api: ApiClient,
    lot_id: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    **overrides,
) -> Dict[str, Any]:
    return get_success_data(
        api.report_casting_defect(
            lot_id, F.casting_defect_payload(**overrides), headers or U.QUALITY_INSPECTOR
        )
    )


def setup_inspected_lot(api: ApiClient, ctx: World, **overrides) -> Dict[str, Any]:
    lot = pour_casting_lot(api, ctx, **overrides)
    get_success_data(api.inspect_casting_lot(lot["id"], U.QUALITY_INSPECTOR))
    return reread_casting_lot(api, lot["id"])


def setup_accepted_lot(api: ApiClient, ctx: World, **overrides) -> Dict[str, Any]:
    lot = setup_inspected_lot(api, ctx, **overrides)
    get_success_data(api.accept_casting_lot(lot["id"], U.QUALITY_INSPECTOR))
    return reread_casting_lot(api, lot["id"])


# ─────────────────────────────────────────────────────────────────────────────
# Tier 3 — build order lifecycle
# ─────────────────────────────────────────────────────────────────────────────
def setup_planned_build_order(
    api: ApiClient,
    world: Optional[World] = None,
    *,
    lot_overrides: Optional[Dict[str, Any]] = None,
    build_overrides: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> World:
    """An APPROVED Selection, an ACCEPTED lot and a PLANNED BuildOrder."""
    ctx = (
        dict(world)
        if world is not None and "selection" in world
        else setup_approved_selection(api, world, **kwargs)
    )
    ctx["lot"] = setup_accepted_lot(api, ctx, **(lot_overrides or {}))
    ctx["build_order"] = get_success_data(
        api.create_build_order(
            F.build_order_payload(
                ctx["selection"]["id"], ctx["lot"]["id"], **(build_overrides or {})
            ),
            U.PRODUCTION_PLANNER,
        )
    )
    ctx["lot"] = reread_casting_lot(api, ctx["lot"]["id"])
    ctx["duty"] = reread_duty_application(api, ctx["duty"]["id"])
    return ctx


def setup_assembled_build_order(
    api: ApiClient,
    world: Optional[World] = None,
    *,
    assembly: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> World:
    ctx = (
        dict(world)
        if world is not None and "build_order" in world
        else setup_planned_build_order(api, world, **kwargs)
    )
    get_success_data(
        api.record_assembly(
            ctx["build_order"]["id"],
            F.assembly_payload(**(assembly or {})),
            U.PRODUCTION_PLANNER,
        )
    )
    ctx["build_order"] = reread_build_order(api, ctx["build_order"]["id"])
    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# Tier 3 — test run lifecycle
# ─────────────────────────────────────────────────────────────────────────────
def add_points(
    api: ApiClient, test_run_id: str, points: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    return [
        get_success_data(api.add_test_point(test_run_id, dict(p), U.TEST_ENGINEER))
        for p in points
    ]


def setup_open_test_run(
    api: ApiClient,
    build_order_id: str,
    *,
    points: Optional[List[Dict[str, Any]]] = None,
    **run_overrides,
) -> Dict[str, Any]:
    """An OPEN TestRun that already carries its measured points."""
    run = get_success_data(
        api.create_test_run(
            F.test_run_payload(build_order_id, **run_overrides), U.TEST_ENGINEER
        )
    )
    add_points(
        api,
        run["id"],
        F.curve_points(
            points if points is not None else K.GOLDEN_CURVE_POINTS_AT_RATED
        ),
    )
    return reread_test_run(api, run["id"])


def setup_locked_test_run(
    api: ApiClient, build_order_id: str, **kwargs
) -> Dict[str, Any]:
    run = setup_open_test_run(api, build_order_id, **kwargs)
    get_success_data(api.lock_test_run(run["id"], U.TEST_ENGINEER))
    return reread_test_run(api, run["id"])


def setup_evaluated_test_run(
    api: ApiClient, build_order_id: str, **kwargs
) -> Dict[str, Any]:
    run = setup_locked_test_run(api, build_order_id, **kwargs)
    get_success_data(api.evaluate_test_run(run["id"], U.TEST_ENGINEER))
    return reread_test_run(api, run["id"])


def setup_certified_test_run(
    api: ApiClient, build_order_id: str, **kwargs
) -> Dict[str, Any]:
    run = setup_evaluated_test_run(api, build_order_id, **kwargs)
    get_success_data(api.certify_test_run(run["id"], U.TEST_ENGINEER))
    return reread_test_run(api, run["id"])


def setup_tested_build_order(
    api: ApiClient,
    world: Optional[World] = None,
    *,
    run_kwargs: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> World:
    """A BuildOrder driven to TESTED by certifying one run on it."""
    ctx = (
        dict(world)
        if world is not None and world.get("build_order", {}).get("status") == "ASSEMBLED"
        else setup_assembled_build_order(api, world, **kwargs)
    )
    ctx["test_run"] = setup_certified_test_run(
        api, ctx["build_order"]["id"], **(run_kwargs or {})
    )
    ctx["build_order"] = reread_build_order(api, ctx["build_order"]["id"])
    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# Tier 3 — package lifecycle
# ─────────────────────────────────────────────────────────────────────────────
def setup_configured_package(
    api: ApiClient,
    world: Optional[World] = None,
    *,
    package: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> World:
    ctx = (
        dict(world)
        if world is not None and "test_run" in world
        else setup_tested_build_order(api, world, **kwargs)
    )
    ctx["package"] = get_success_data(
        api.create_pump_package(
            F.pump_package_payload(
                ctx["build_order"]["id"], ctx["test_run"]["id"], **(package or {})
            ),
            U.PRODUCTION_PLANNER,
        )
    )
    return ctx


def setup_released_package(api: ApiClient, world: Optional[World] = None, **kwargs) -> World:
    ctx = (
        dict(world)
        if world is not None and "package" in world
        else setup_configured_package(api, world, **kwargs)
    )
    get_success_data(api.release_pump_package(ctx["package"]["id"], U.PRODUCTION_PLANNER))
    ctx["package"] = reread_pump_package(api, ctx["package"]["id"])
    return ctx


def setup_shipped_package(
    api: ApiClient,
    world: Optional[World] = None,
    *,
    actual_ship_date: str = K.DEFAULT_ACTUAL_SHIP_DATE,
    **kwargs,
) -> World:
    ctx = setup_released_package(api, world, **kwargs)
    get_success_data(
        api.ship_pump_package(
            ctx["package"]["id"], F.ship_payload(actual_ship_date), U.PRODUCTION_PLANNER
        )
    )
    ctx["package"] = reread_pump_package(api, ctx["package"]["id"])
    ctx["build_order"] = reread_build_order(api, ctx["build_order"]["id"])
    ctx["duty"] = reread_duty_application(api, ctx["duty"]["id"])
    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# Tier 4 — accumulation and threshold targeting
# ─────────────────────────────────────────────────────────────────────────────
def setup_kit_with_stock(
    api: ApiClient, pump_model_id: str, qty: int = 5, **overrides
) -> Dict[str, Any]:
    """A RepairKit whose stock has been received, so its version has advanced.

    The returned row is the receipt response, so `version` is the value a
    subsequent allocation must echo in `expected_repair_kit_version`.
    """
    kit = create_repair_kit(api, pump_model_id, **overrides)
    return get_success_data(
        api.receive_repair_kit_stock(
            kit["id"], F.kit_receipt_payload(qty), U.PRODUCTION_PLANNER
        )
    )


def setup_reserved_allocation(
    api: ApiClient,
    kit: Dict[str, Any],
    build_order_id: str,
    requested_qty: int = 1,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_kit_allocation(
            F.kit_allocation_payload(
                kit["id"], build_order_id, requested_qty, kit["version"]
            ),
            U.PRODUCTION_PLANNER,
        )
    )


def setup_pattern_one_pour_below_threshold(
    api: ApiClient, ctx: World, pours: int
) -> Dict[str, Any]:
    """Pour `pours` non-overlapping lots so the wear counter climbs by `pours`.

    PRD 2.10 gives the pattern closed-interval semantics, so consecutive windows
    must not even touch.
    """
    day = 5
    for _ in range(pours):
        pour_casting_lot(
            api,
            ctx,
            pour_window_start=f"2026-08-{day:02d}T00:00:00Z",
            pour_window_end=f"2026-08-{day + 1:02d}T00:00:00Z",
        )
        day += 3
    return reread_pattern_asset(api, ctx["pattern"]["id"])


def setup_lot_with_critical_defect(
    api: ApiClient, ctx: World, *, affected_qty: int = 1, **lot_overrides
) -> Dict[str, Any]:
    """A poured lot carrying one CRITICAL defect, which weights the wear index."""
    lot = pour_casting_lot(api, ctx, **lot_overrides)
    defect = report_defect(
        api,
        lot["id"],
        headers=ctx["foundry_headers"],
        severity="CRITICAL",
        affected_qty=affected_qty,
    )
    return {"lot": reread_casting_lot(api, lot["id"]), "defect": defect}


# ─────────────────────────────────────────────────────────────────────────────
# Tier 5 — warranty lifecycle and terminal states
# ─────────────────────────────────────────────────────────────────────────────
def setup_claim_submitted(
    api: ApiClient,
    world: Optional[World] = None,
    *,
    claim: Optional[Dict[str, Any]] = None,
    claim_lines: Optional[List[Dict[str, Any]]] = None,
    clock: Optional[str] = K.CLOCK_SEVENTEEN_MONTHS_AFTER_SHIP,
    engineer_headers: Optional[Dict[str, str]] = None,
    **kwargs,
) -> World:
    """A SUBMITTED WarrantyClaim against a shipped package.

    By default the clock is 17 whole months past the ship date, which puts the
    claim inside the warranty and on the 0.60 coverage tier.
    """
    ctx = (
        dict(world)
        if world is not None and world.get("package", {}).get("status") == "SHIPPED"
        else setup_shipped_package(api, world, **kwargs)
    )
    if clock is not None:
        set_clock(api, clock)
    ctx["claim"] = get_success_data(
        api.create_warranty_claim(
            F.warranty_claim_payload(
                ctx["package"]["id"], claim_lines=claim_lines, **(claim or {})
            ),
            engineer_headers or U.APPLICATION_ENGINEER,
        )
    )
    return ctx


def setup_claim_under_adjudication(
    api: ApiClient,
    world: Optional[World] = None,
    *,
    adjudicator_headers: Optional[Dict[str, str]] = None,
    **kwargs,
) -> World:
    ctx = (
        dict(world)
        if world is not None and "claim" in world
        else setup_claim_submitted(api, world, **kwargs)
    )
    get_success_data(
        api.begin_claim_adjudication(
            ctx["claim"]["id"], adjudicator_headers or U.WARRANTY_ADJUDICATOR
        )
    )
    ctx["claim"] = reread_warranty_claim(api, ctx["claim"]["id"])
    return ctx


def setup_adjudicated_claim(
    api: ApiClient,
    world: Optional[World] = None,
    *,
    adjudicator_headers: Optional[Dict[str, str]] = None,
    **kwargs,
) -> World:
    ctx = setup_claim_under_adjudication(
        api, world, adjudicator_headers=adjudicator_headers, **kwargs
    )
    get_success_data(
        api.adjudicate_claim(
            ctx["claim"]["id"], adjudicator_headers or U.WARRANTY_ADJUDICATOR
        )
    )
    ctx["claim"] = reread_warranty_claim(api, ctx["claim"]["id"])
    return ctx


def setup_settled_claim(api: ApiClient, world: Optional[World] = None, **kwargs) -> World:
    """A SETTLED claim, the terminal state of the warranty workflow."""
    ctx = setup_adjudicated_claim(api, world, **kwargs)
    get_success_data(api.settle_claim(ctx["claim"]["id"], U.WARRANTY_ADJUDICATOR))
    ctx["claim"] = reread_warranty_claim(api, ctx["claim"]["id"])
    return ctx


# ─────────────────────────────────────────────────────────────────────────────
# Convenience: a package whose guarantee rests on the selection rather than on
# a certified curve, which the warranty workflow treats differently.
# ─────────────────────────────────────────────────────────────────────────────
def setup_shipped_package_on_selection_basis(
    api: ApiClient, world: Optional[World] = None, **kwargs
) -> World:
    """A shipped package whose run was not witnessed, so guarantee_basis is SELECTION."""
    ctx = world if world is not None else setup_master_data(api)
    ctx = setup_assembled_build_order(
        api, ctx, duty={"witness_required": False}, **kwargs
    )
    ctx["test_run"] = setup_certified_test_run(
        api, ctx["build_order"]["id"], witness_required=False
    )
    ctx["build_order"] = reread_build_order(api, ctx["build_order"]["id"])
    return setup_shipped_package(api, ctx)
