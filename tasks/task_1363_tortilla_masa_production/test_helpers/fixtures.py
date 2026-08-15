"""
Composite setup helpers for multi-step test prerequisites.

Every test starts against an empty database (the harness restarts the server
before each test), so each helper builds its preconditions from scratch using
only PRD-declared endpoints. Setup calls use get_success_data() so failures
surface as clear "Setup failed" messages rather than confusing assertions.

Standard clock choreography (PRD §2.4): the clock starts at
2026-08-01T00:00:00Z; cook starts at 00:00, the clock advances to 02:00 so the
90-minute cook has elapsed, steep starts at 02:00, and the clock advances to
12:00 so the 8-hour steep has elapsed.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_allocation_payload,
    create_changeover_payload,
    create_customer_payload,
    create_ingredient_lot_payload,
    create_line_payload,
    create_mill_payload,
    create_nixtamal_batch_payload,
    create_pack_order_payload,
    create_product_payload,
    create_route_payload,
    create_route_stop_payload,
    create_run_payload,
    create_seasonal_window_payload,
    create_weight_check_payload,
)
from .test_users import TEST_USERS, make_sanitation_tech_headers

PM = TEST_USERS["plant_manager_headers"]
MILLER = TEST_USERS["miller_operator_headers"]
QI = TEST_USERS["quality_inspector_headers"]
SCHED = TEST_USERS["line_scheduler_headers"]
SAN = TEST_USERS["sanitation_tech_headers"]
PACK = TEST_USERS["packaging_lead_headers"]
DISP = TEST_USERS["route_dispatcher_headers"]

# Clock positions used by the standard choreography.
CLOCK_COOK_DONE = "2026-08-01T02:00:00Z"   # 120 min >= 90-minute cook
CLOCK_STEEP_DONE = "2026-08-01T12:00:00Z"  # 10 h >= 8-hour steep


# ─── Tier 0/1: single-resource helpers ──────────────────────────────


def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock (PRD §2.4). Returns the response data."""
    return get_success_data(api_client.set_clock(to_iso8601, PM))


def create_lot(**overrides) -> dict:
    """Receive an ingredient lot (lot_status RECEIVED)."""
    return get_success_data(
        api_client.create_ingredient_lot(create_ingredient_lot_payload(**overrides), PM)
    )


def condition_lot(lot_id: str, decision: str = None) -> dict:
    """Condition (default) or reject (decision='REJECT') a RECEIVED lot."""
    payload = {} if decision is None else {"decision": decision}
    return get_success_data(api_client.condition_ingredient_lot(lot_id, payload, MILLER))


def create_conditioned_lot(**overrides) -> dict:
    """Lot driven RECEIVED -> CONDITIONED."""
    lot = create_lot(**overrides)
    return condition_lot(lot["id"])


def create_batch(lot_id: str, **overrides) -> dict:
    """Create a nixtamal batch (batch_status PLANNED) drawing from a lot."""
    return get_success_data(
        api_client.create_nixtamal_batch(
            create_nixtamal_batch_payload(lot_id, **overrides), MILLER
        )
    )


def start_cook(batch_id: str) -> dict:
    return get_success_data(api_client.start_cook(batch_id, MILLER))


def start_steep(batch_id: str) -> dict:
    return get_success_data(api_client.start_steep(batch_id, MILLER))


def evaluate_batch(batch_id: str, decision: str) -> dict:
    return get_success_data(api_client.evaluate_batch(batch_id, decision, QI))


def mill_batch(batch_id: str, **mill_overrides) -> dict:
    return get_success_data(
        api_client.mill_batch(batch_id, create_mill_payload(**mill_overrides), MILLER)
    )


def create_product(**overrides) -> dict:
    return get_success_data(
        api_client.create_product(create_product_payload(**overrides), PM)
    )


def create_line(**overrides) -> dict:
    return get_success_data(api_client.create_line(create_line_payload(**overrides), PM))


def get_line(line_id: str) -> dict:
    return get_success_data(api_client.get_line(line_id, SCHED))


def create_run(product_id: str, line_id: str, expected_line_version=None, **overrides) -> dict:
    """Create a run. When expected_line_version is None, read the line's
    current version first (OCC field is mandatory per PRD §2.6)."""
    if expected_line_version is None:
        expected_line_version = get_line(line_id)["version"]
    return get_success_data(
        api_client.create_run(
            create_run_payload(
                product_id, line_id, expected_line_version, **overrides
            ),
            SCHED,
        )
    )


def schedule_run(run_id: str) -> dict:
    return get_success_data(api_client.schedule_run(run_id, SCHED))


def allocate_masa(batch_id: str, run_id: str, allocated_kg: float = 388.8) -> dict:
    return get_success_data(
        api_client.create_allocation(
            create_allocation_payload(batch_id, run_id, allocated_kg=allocated_kg), SCHED
        )
    )


def start_run(run_id: str) -> dict:
    return get_success_data(api_client.start_run(run_id, SCHED))


def create_pack_order(run_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_pack_order(create_pack_order_payload(run_id, **overrides), PACK)
    )


def create_customer(**overrides) -> dict:
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), PM)
    )


def create_route(**overrides) -> dict:
    return get_success_data(api_client.create_route(create_route_payload(**overrides), DISP))


def get_route(route_id: str) -> dict:
    return get_success_data(api_client.get_route(route_id, DISP))


def create_stop(route_id: str, customer_id: str, pack_order_id: str,
                expected_route_version=None, **overrides) -> dict:
    """Create a stop. When expected_route_version is None, read the route's
    current version first (OCC field is mandatory per PRD §2.6)."""
    if expected_route_version is None:
        expected_route_version = get_route(route_id)["version"]
    return get_success_data(
        api_client.create_route_stop(
            route_id,
            create_route_stop_payload(
                customer_id, pack_order_id, expected_route_version, **overrides
            ),
            DISP,
        )
    )


def create_seasonal_window(**overrides) -> dict:
    return get_success_data(
        api_client.create_seasonal_window(create_seasonal_window_payload(**overrides), PM)
    )


def create_manual_changeover(line_id: str, from_product_id: str, to_product_id: str,
                             performer: str = "san-01", **overrides) -> dict:
    """Manually register a changeover as a SanitationTech (PRD §3.6)."""
    return get_success_data(
        api_client.create_changeover(
            create_changeover_payload(line_id, from_product_id, to_product_id, **overrides),
            make_sanitation_tech_headers(performer),
        )
    )


# ─── Tier 2/3: nixtamal lifecycle shortcuts ─────────────────────────


def setup_steeping_batch(lot_overrides=None, batch_overrides=None) -> dict:
    """CONDITIONED lot + batch driven PLANNED -> COOKING -> STEEPING with the
    cook and steep durations satisfied by the logical clock.

    Returns dict with keys: lot, batch (STEEPING).
    """
    lot = create_conditioned_lot(**(lot_overrides or {}))
    batch = create_batch(lot["id"], **(batch_overrides or {}))
    start_cook(batch["id"])
    set_clock(CLOCK_COOK_DONE)
    start_steep(batch["id"])
    set_clock(CLOCK_STEEP_DONE)
    batch = get_success_data(api_client.get_nixtamal_batch(batch["id"], MILLER))
    return {"lot": lot, "batch": batch}


def setup_milling_batch(**kwargs) -> dict:
    """Batch in MILLING (evaluate PASS after a satisfied steep)."""
    ctx = setup_steeping_batch(**kwargs)
    ctx["batch"] = evaluate_batch(ctx["batch"]["id"], "PASS")
    return ctx


def setup_milled_batch(mill_overrides=None, **kwargs) -> dict:
    """Batch in MASA_AVAILABLE with the standard mill inputs (1620 kg milled,
    58% moisture, 20 kg waste -> 1552.0 kg actual for a 1000 kg WHITE_CORN
    batch). Returns dict with keys: lot, batch.
    """
    ctx = setup_milling_batch(**kwargs)
    ctx["batch"] = mill_batch(ctx["batch"]["id"], **(mill_overrides or {}))
    return ctx


# ─── Tier 3: run lifecycle shortcuts ────────────────────────────────


def setup_in_progress_run(planned_cases: int = 50, allocated_kg: float = 388.8,
                          product_overrides=None, line_overrides=None,
                          run_overrides=None, batch_ctx=None) -> dict:
    """Milled batch + product + SHARED line + run driven to IN_PROGRESS with
    full masa coverage. Returns dict: lot, batch, product, line, run.
    """
    ctx = batch_ctx or setup_milled_batch()
    product = create_product(**(product_overrides or {}))
    line = create_line(**(line_overrides or {}))
    run = create_run(
        product["id"], line["id"], planned_cases=planned_cases, **(run_overrides or {})
    )
    schedule_run(run["id"])
    allocate_masa(ctx["batch"]["id"], run["id"], allocated_kg)
    run = start_run(run["id"])
    return {**ctx, "product": product, "line": line, "run": run}


# ─── Tier 3/4: packaging shortcuts ──────────────────────────────────


def pack_order_pass_weight_check(pack_order_id: str, cases_packed: int = 20,
                                 sample_weights_g=None) -> dict:
    """start-packing + passing weight check (avg 360.0 g inside the default
    360.0 +/- 2% band). Returns the PASSED pack order."""
    get_success_data(api_client.start_packing(pack_order_id, PACK))
    return get_success_data(
        api_client.weight_check(
            pack_order_id,
            create_weight_check_payload(
                cases_packed,
                sample_weights_g=sample_weights_g or [360.0, 360.0, 360.0],
            ),
            PACK,
        )
    )


def seal_pack_order(pack_order_id: str) -> dict:
    return get_success_data(api_client.seal_pack_order(pack_order_id, PACK))


def setup_sealed_pack(cases_packed: int = 20, planned_cases: int = 50,
                      allocated_kg: float = 388.8, cases_planned: int = None,
                      product_overrides=None, line_overrides=None,
                      run_overrides=None) -> dict:
    """Full chain through a SEALED pack order (sealed on 2026-08-01, the
    default PROPIONATE product giving expires_on 2026-08-21).

    Returns dict: lot, batch, product, line, run, pack_order.
    """
    ctx = setup_in_progress_run(
        planned_cases=planned_cases,
        allocated_kg=allocated_kg,
        product_overrides=product_overrides,
        line_overrides=line_overrides,
        run_overrides=run_overrides,
    )
    pack_order = create_pack_order(
        ctx["run"]["id"], cases_planned=cases_planned or cases_packed
    )
    pack_order = pack_order_pass_weight_check(pack_order["id"], cases_packed)
    pack_order = seal_pack_order(pack_order["id"])
    ctx["pack_order"] = pack_order
    return ctx


# ─── Tier 4/5: route / stop shortcuts ───────────────────────────────


def setup_route_with_stop(requested_cases: int = 10, cases_packed: int = 20,
                          customer_overrides=None, route_overrides=None,
                          **pack_kwargs) -> dict:
    """Sealed pack + GOOD customer + PLANNED route with one ALLOCATED stop.

    Returns dict: lot, batch, product, line, run, pack_order, customer, route,
    stop.
    """
    ctx = setup_sealed_pack(cases_packed=cases_packed, **pack_kwargs)
    customer = create_customer(**(customer_overrides or {}))
    route = create_route(**(route_overrides or {}))
    stop = create_stop(route["id"], customer["id"], ctx["pack_order"]["id"],
                       requested_cases=requested_cases)
    ctx.update({"customer": customer, "route": route, "stop": stop})
    return ctx


def setup_dispatched_route_with_stop(**kwargs) -> dict:
    """setup_route_with_stop + dispatch. Route is DISPATCHED; stop ALLOCATED."""
    ctx = setup_route_with_stop(**kwargs)
    ctx["route"] = get_success_data(api_client.dispatch_route(ctx["route"]["id"], DISP))
    return ctx
