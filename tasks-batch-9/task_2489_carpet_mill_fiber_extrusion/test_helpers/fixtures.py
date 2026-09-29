"""Composite setup helpers.

Reaching a testable state in this domain takes a long chain of calls: polymer is
received, spun into fibre and released; a style is created and activated; a
tufter and a vessel are registered; a run is scheduled, set up, tufted to greige
and backed; a dye lot is formulated, dyed, measured and approved; a roll is
doffed, lab-tested, certified and released; only then can an account place an
order and have it allocated. These helpers encapsulate those chains so tests can
concentrate on the rule under test.

Every helper takes ``**overrides`` for the values a test needs to control and
uses the lenient ``get_success_data`` validator, so a broken preamble surfaces as
a clear setup failure.
"""

from typing import Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import (
    DYE_WINDOW_OPEN_UTC,
    RUN_WINDOW_OPEN_UTC,
    TEST_DEFAULTS,
)
from .test_users import TEST_USERS, make_dealer_buyer_headers

PLANNER = TEST_USERS["mill_planner_headers"]
EXTRUDER = TEST_USERS["extrusion_operator_headers"]
DYER = TEST_USERS["dye_house_operator_headers"]
QA = TEST_USERS["qa_lab_technician_headers"]
CERTIFIER = TEST_USERS["certification_officer_headers"]
ADMIN = TEST_USERS["plant_admin_headers"]


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


def set_clock(to_iso8601: str, headers: Optional[dict] = None) -> dict:
    """Move the logical clock. Only PlantAdmin may do this."""
    return get_success_data(
        api_client.set_clock(f.set_clock_payload(to_iso8601), headers or ADMIN)
    )


# ---------------------------------------------------------------------------
# Tier 1 — single-entity builders
# ---------------------------------------------------------------------------


def create_account(**overrides) -> dict:
    return get_success_data(
        api_client.create_account(f.create_account_payload(**overrides), PLANNER)
    )


def create_polymer_lot(**overrides) -> dict:
    return get_success_data(
        api_client.create_polymer_lot(f.create_polymer_lot_payload(**overrides), EXTRUDER)
    )


def create_recycled_polymer_lot(**overrides) -> dict:
    """A fully recycled, segregated lot — the kind physical segregation counts."""
    payload = dict(
        lot_code="PL-RECYCLED-01",
        recycled_content_pct=100.00,
        segregated=True,
        reclaim_source="POST_CONSUMER",
    )
    payload.update(overrides)
    return create_polymer_lot(**payload)


def create_reclamation_batch(**overrides) -> dict:
    return get_success_data(
        api_client.create_reclamation_batch(
            f.create_reclamation_batch_payload(**overrides), EXTRUDER
        )
    )


def depolymerize_reclamation_batch(reclamation_batch_id: str) -> dict:
    return get_success_data(
        api_client.depolymerize_reclamation_batch(reclamation_batch_id, EXTRUDER)
    )


def create_fiber_batch(polymer_lot_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_fiber_batch(
            f.create_fiber_batch_payload(polymer_lot_id, **overrides), EXTRUDER
        )
    )


def create_released_fiber_batch(
    polymer_lot_id: Optional[str] = None,
    extrude_overrides: Optional[dict] = None,
    **overrides,
) -> dict:
    """Receive polymer if needed, queue a batch, extrude it and release it.

    Returns the RELEASED FiberBatch. The default numbers put denier_actual
    exactly on denier_target, so the release gate is never the thing under test.
    """
    if polymer_lot_id is None:
        polymer_lot_id = create_polymer_lot()["id"]
    batch = create_fiber_batch(polymer_lot_id, **overrides)
    get_success_data(
        api_client.extrude_fiber_batch(
            batch["id"], f.extrude_fiber_batch_payload(**(extrude_overrides or {})), EXTRUDER
        )
    )
    return get_success_data(
        api_client.disposition_fiber_batch(
            batch["id"], f.disposition_fiber_batch_payload("RELEASE"), EXTRUDER
        )
    )


def create_style(**overrides) -> dict:
    return get_success_data(
        api_client.create_style(f.create_style_payload(**overrides), PLANNER)
    )


def create_active_style(**overrides) -> dict:
    """Create a style and activate it. Returns the ACTIVE style."""
    style = create_style(**overrides)
    return get_success_data(api_client.activate_style(style["id"], PLANNER))


def create_active_piece_dyed_style(**overrides) -> dict:
    style = get_success_data(
        api_client.create_style(
            f.create_piece_dyed_style_payload(**overrides), PLANNER
        )
    )
    return get_success_data(api_client.activate_style(style["id"], PLANNER))


def create_tufting_machine(**overrides) -> dict:
    return get_success_data(
        api_client.create_tufting_machine(
            f.create_tufting_machine_payload(**overrides), PLANNER
        )
    )


def create_dye_vessel(**overrides) -> dict:
    return get_success_data(
        api_client.create_dye_vessel(f.create_dye_vessel_payload(**overrides), DYER)
    )


def create_scheduled_run(
    style_id: str, machine_id: str, fiber_batch_id: str, **overrides
) -> dict:
    return get_success_data(
        api_client.create_production_run(
            f.create_production_run_payload(
                style_id, machine_id, fiber_batch_id, **overrides
            ),
            PLANNER,
        )
    )


# ---------------------------------------------------------------------------
# Tier 2 / 3 — run lifecycle shortcuts
# ---------------------------------------------------------------------------


def advance_run_to_tufting(
    production_run_id: str,
    clock_to: Optional[str] = RUN_WINDOW_OPEN_UTC,
    **load_setup_overrides,
) -> dict:
    """Open the run's window on the logical clock, then load the tufter."""
    if clock_to is not None:
        set_clock(clock_to)
    return get_success_data(
        api_client.load_setup_production_run(
            production_run_id, f.load_setup_payload(**load_setup_overrides), PLANNER
        )
    )


def advance_run_to_greige(
    production_run_id: str,
    clock_to: Optional[str] = RUN_WINDOW_OPEN_UTC,
    load_setup_overrides: Optional[dict] = None,
    **greige_overrides,
) -> dict:
    advance_run_to_tufting(
        production_run_id, clock_to=clock_to, **(load_setup_overrides or {})
    )
    return get_success_data(
        api_client.complete_greige_production_run(
            production_run_id, f.complete_greige_payload(**greige_overrides), PLANNER
        )
    )


def apply_backing(production_run_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.apply_backing_production_run(
            production_run_id, f.apply_backing_payload(**overrides), PLANNER
        )
    )


def advance_run_to_backed(
    production_run_id: str,
    clock_to: Optional[str] = RUN_WINDOW_OPEN_UTC,
    load_setup_overrides: Optional[dict] = None,
    greige_overrides: Optional[dict] = None,
    **backing_overrides,
) -> dict:
    """Walk a SCHEDULED run all the way to BACKED."""
    advance_run_to_greige(
        production_run_id,
        clock_to=clock_to,
        load_setup_overrides=load_setup_overrides,
        **(greige_overrides or {}),
    )
    return apply_backing(production_run_id, **backing_overrides)


def setup_backed_solution_dyed_run(
    style_overrides: Optional[dict] = None,
    machine_overrides: Optional[dict] = None,
    fiber_overrides: Optional[dict] = None,
    run_overrides: Optional[dict] = None,
    load_setup_overrides: Optional[dict] = None,
    greige_overrides: Optional[dict] = None,
    backing_overrides: Optional[dict] = None,
    polymer_lot_id: Optional[str] = None,
) -> Dict[str, dict]:
    """Solution-dyed style with a run walked to BACKED.

    Returns a context dict with keys: polymer_lot, fiber_batch, style, machine, run.
    """
    if polymer_lot_id is None:
        polymer_lot = create_polymer_lot()
        polymer_lot_id = polymer_lot["id"]
    else:
        polymer_lot = get_success_data(
            api_client.get_polymer_lot(polymer_lot_id, EXTRUDER)
        )
    fiber_batch = create_released_fiber_batch(
        polymer_lot_id, **(fiber_overrides or {})
    )
    style = create_active_style(**(style_overrides or {}))
    machine = create_tufting_machine(**(machine_overrides or {}))
    run = create_scheduled_run(
        style["id"], machine["id"], fiber_batch["id"], **(run_overrides or {})
    )
    run = advance_run_to_backed(
        run["id"],
        load_setup_overrides=load_setup_overrides,
        greige_overrides=greige_overrides,
        **(backing_overrides or {}),
    )
    return {
        "polymer_lot": polymer_lot,
        "fiber_batch": fiber_batch,
        "style": style,
        "machine": machine,
        "run": run,
    }


def setup_backed_piece_dyed_run(
    style_overrides: Optional[dict] = None,
    machine_overrides: Optional[dict] = None,
    fiber_overrides: Optional[dict] = None,
    run_overrides: Optional[dict] = None,
    vessel_overrides: Optional[dict] = None,
) -> Dict[str, dict]:
    """Piece-dyed style with a run walked to BACKED, plus a registered vessel.

    Returns a context dict with keys: polymer_lot, fiber_batch, style, machine,
    vessel, run.
    """
    polymer_lot = create_polymer_lot()
    fiber_defaults = {"dye_method": "PIECE_DYED_READY", "solution_color_code": None}
    fiber_defaults.update(fiber_overrides or {})
    fiber_batch = create_released_fiber_batch(polymer_lot["id"], **fiber_defaults)
    style = create_active_piece_dyed_style(**(style_overrides or {}))
    machine = create_tufting_machine(**(machine_overrides or {}))
    vessel = create_dye_vessel(**(vessel_overrides or {}))
    run = create_scheduled_run(
        style["id"], machine["id"], fiber_batch["id"], **(run_overrides or {})
    )
    run = advance_run_to_backed(run["id"])
    return {
        "polymer_lot": polymer_lot,
        "fiber_batch": fiber_batch,
        "style": style,
        "machine": machine,
        "vessel": vessel,
        "run": run,
    }


# ---------------------------------------------------------------------------
# Tier 3 — dye lot lifecycle
# ---------------------------------------------------------------------------


def create_dye_lot(production_run_id: str, vessel_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_dye_lot(
            f.create_dye_lot_payload(production_run_id, vessel_id, **overrides), DYER
        )
    )


def start_dyeing(
    dye_lot_id: str, clock_to: Optional[str] = DYE_WINDOW_OPEN_UTC
) -> dict:
    """Open the lot's dye window on the logical clock, then charge the vessel."""
    if clock_to is not None:
        set_clock(clock_to)
    return get_success_data(api_client.start_dyeing(dye_lot_id, DYER))


def record_measurement(dye_lot_id: str, expected_dye_lot_version: int, **overrides) -> dict:
    return get_success_data(
        api_client.record_dye_lot_measurement(
            dye_lot_id,
            f.measurement_payload(expected_dye_lot_version, **overrides),
            DYER,
        )
    )


def disposition_dye_lot(dye_lot_id: str, disposition: str = "APPROVE") -> dict:
    return get_success_data(
        api_client.disposition_dye_lot(
            dye_lot_id, f.disposition_dye_lot_payload(disposition), DYER
        )
    )


def create_measured_dye_lot(
    production_run_id: str,
    vessel_id: str,
    measurement_overrides: Optional[dict] = None,
    clock_to: Optional[str] = DYE_WINDOW_OPEN_UTC,
    **lot_overrides,
) -> dict:
    """Formulate a lot, dye it and record one reading. Returns the MEASURED lot.

    With no measurement override the reading equals the target, so delta_e is
    0.00 and the lot lands in shade band A.
    """
    lot = create_dye_lot(production_run_id, vessel_id, **lot_overrides)
    dyeing = start_dyeing(lot["id"], clock_to=clock_to)
    return record_measurement(
        lot["id"], dyeing["version"], **(measurement_overrides or {})
    )


def create_approved_dye_lot(
    production_run_id: str,
    vessel_id: str,
    measurement_overrides: Optional[dict] = None,
    clock_to: Optional[str] = DYE_WINDOW_OPEN_UTC,
    **lot_overrides,
) -> dict:
    """Formulate, dye, measure and approve a lot. Returns the APPROVED lot."""
    lot = create_measured_dye_lot(
        production_run_id,
        vessel_id,
        measurement_overrides=measurement_overrides,
        clock_to=clock_to,
        **lot_overrides,
    )
    return disposition_dye_lot(lot["id"], "APPROVE")


def requeue_dye_lot_for_redye(dye_lot_id: str) -> dict:
    """Send a MEASURED lot back for a re-dye. Returns the REDYE_QUEUED lot."""
    return disposition_dye_lot(dye_lot_id, "REDYE")


def redye_cycle(
    dye_lot_id: str,
    measurement_overrides: Optional[dict] = None,
    clock_to: Optional[str] = None,
) -> dict:
    """Take a REDYE_QUEUED lot through dyeing and one more reading.

    Returns the MEASURED lot after the cycle. The clock is left alone by default,
    because the lot's window was already opened on the first pass.
    """
    dyeing = start_dyeing(dye_lot_id, clock_to=clock_to)
    return record_measurement(
        dye_lot_id, dyeing["version"], **(measurement_overrides or {})
    )


# ---------------------------------------------------------------------------
# Tier 3 — roll goods, lab tests and certificates
# ---------------------------------------------------------------------------


def doff_roll_good(
    production_run_id: str, dye_lot_id: Optional[str] = None, **overrides
) -> dict:
    """Doff a roll off a BACKED run. Piece-dyed rolls must name their dye lot."""
    payload = f.doff_roll_good_payload(**overrides)
    if dye_lot_id is not None:
        payload["dye_lot_id"] = dye_lot_id
    return get_success_data(api_client.doff_roll_good(production_run_id, payload, PLANNER))


def qa_disposition_roll_good(roll_good_id: str, disposition: str = "RELEASE") -> dict:
    return get_success_data(
        api_client.qa_disposition_roll_good(
            roll_good_id, f.qa_disposition_payload(disposition), QA
        )
    )


def release_roll_good(roll_good_id: str) -> dict:
    """Pass a roll through inspection. Returns the PASSED / AVAILABLE roll."""
    return qa_disposition_roll_good(roll_good_id, "RELEASE")


def record_product_test(style_id: str, roll_good_id: str, **overrides) -> dict:
    """Record one lab result. Recorded by the QA technician, never the officer."""
    return get_success_data(
        api_client.create_product_test(
            f.create_product_test_payload(style_id, roll_good_id, **overrides), QA
        )
    )


def issue_certification(style_id: str, source_test_ids: List[str], **overrides) -> dict:
    """Issue a certificate. The officer is a different person from the technician
    who produced the evidence, so segregation of duties is satisfied."""
    return get_success_data(
        api_client.create_certification(
            f.create_certification_payload(style_id, source_test_ids, **overrides),
            CERTIFIER,
        )
    )


def issue_flammability_certification(
    style_id: str, roll_good_id: str, **overrides
) -> Tuple[dict, dict]:
    """Record a passing pill test and issue the DOC FF 1-70 certificate from it.

    Returns (certification, product_test).
    """
    test = record_product_test(
        style_id,
        roll_good_id,
        test_type="FLAMMABILITY_PILL",
        result_value=TEST_DEFAULTS["FLAMMABILITY_PASS_VALUE"],
    )
    cert = issue_certification(
        style_id, [test["id"]], cert_type="DOC_FF_1_70", **overrides
    )
    return cert, test


def revoke_certification(certification_id: str) -> dict:
    return get_success_data(
        api_client.revoke_certification(
            certification_id, f.revoke_certification_payload(), CERTIFIER
        )
    )


# ---------------------------------------------------------------------------
# Tier 4 — sellable inventory
# ---------------------------------------------------------------------------


def setup_available_solution_dyed_roll(
    roll_overrides: Optional[dict] = None,
    certify: bool = True,
    **run_kwargs,
) -> Dict[str, dict]:
    """A solution-dyed style with one PASSED / AVAILABLE roll in stock.

    When ``certify`` is true the style also carries an effective DOC FF 1-70
    certificate, which allocation requires.

    Returns a context dict with keys: polymer_lot, fiber_batch, style, machine,
    run, roll_good, and (when certified) certification and product_test.
    """
    ctx = setup_backed_solution_dyed_run(**run_kwargs)
    roll = doff_roll_good(ctx["run"]["id"], **(roll_overrides or {}))
    if certify:
        cert, test = issue_flammability_certification(ctx["style"]["id"], roll["id"])
        ctx["certification"] = cert
        ctx["product_test"] = test
    ctx["roll_good"] = release_roll_good(roll["id"])
    return ctx


def setup_available_piece_dyed_roll(
    roll_overrides: Optional[dict] = None,
    dye_lot_overrides: Optional[dict] = None,
    measurement_overrides: Optional[dict] = None,
    certify: bool = True,
    **run_kwargs,
) -> Dict[str, dict]:
    """A piece-dyed style with one approved dye lot and one PASSED / AVAILABLE roll.

    Returns a context dict with keys: polymer_lot, fiber_batch, style, machine,
    vessel, run, dye_lot, roll_good, and (when certified) certification and
    product_test.
    """
    ctx = setup_backed_piece_dyed_run(**run_kwargs)
    lot = create_approved_dye_lot(
        ctx["run"]["id"],
        ctx["vessel"]["id"],
        measurement_overrides=measurement_overrides,
        **(dye_lot_overrides or {}),
    )
    ctx["dye_lot"] = lot
    roll = doff_roll_good(
        ctx["run"]["id"], dye_lot_id=lot["id"], **(roll_overrides or {})
    )
    if certify:
        cert, test = issue_flammability_certification(ctx["style"]["id"], roll["id"])
        ctx["certification"] = cert
        ctx["product_test"] = test
    ctx["roll_good"] = release_roll_good(roll["id"])
    return ctx


def add_roll_good_to_run(
    ctx: Dict[str, dict], dye_lot_id: Optional[str] = None, **overrides
) -> dict:
    """Doff and release one more roll off the run already in ``ctx``.

    Use this to build the multi-roll candidate sets the allocation waterfall
    ranks. The style is already certified by the composite fixtures, so the roll
    only needs doffing and inspecting.
    """
    roll = doff_roll_good(ctx["run"]["id"], dye_lot_id=dye_lot_id, **overrides)
    return release_roll_good(roll["id"])


# ---------------------------------------------------------------------------
# Tier 4 — orders
# ---------------------------------------------------------------------------


def create_cut_order(account_id: str, style_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_cut_order(
            f.create_cut_order_payload(account_id, style_id, **overrides), PLANNER
        )
    )


def create_cut_order_as_dealer(account_id: str, style_id: str, **overrides) -> dict:
    """Submit the order as the DealerBuyer that owns the account."""
    return get_success_data(
        api_client.create_cut_order(
            f.create_cut_order_payload(account_id, style_id, **overrides),
            make_dealer_buyer_headers(account_id),
        )
    )


def setup_submitted_cut_order(
    account_overrides: Optional[dict] = None,
    order_overrides: Optional[dict] = None,
    piece_dyed: bool = False,
    **inventory_kwargs,
) -> Dict[str, dict]:
    """Sellable inventory plus an open account plus one SUBMITTED order.

    Returns the inventory context extended with keys: account, cut_order.
    """
    ctx = (
        setup_available_piece_dyed_roll(**inventory_kwargs)
        if piece_dyed
        else setup_available_solution_dyed_roll(**inventory_kwargs)
    )
    ctx["account"] = create_account(**(account_overrides or {}))
    ctx["cut_order"] = create_cut_order(
        ctx["account"]["id"], ctx["style"]["id"], **(order_overrides or {})
    )
    return ctx


def allocate_cut_order(cut_order_id: str) -> dict:
    return get_success_data(api_client.allocate_cut_order(cut_order_id, PLANNER))


def create_manual_allocation(
    cut_order_id: str, roll_good_id: str, yards: float, expected_roll_good_version: int
) -> dict:
    return get_success_data(
        api_client.create_manual_allocation(
            cut_order_id,
            f.manual_allocation_payload(
                roll_good_id, yards, expected_roll_good_version
            ),
            PLANNER,
        )
    )


def setup_allocated_cut_order(**kwargs) -> Dict[str, dict]:
    """An order carried through automatic allocation.

    Returns the submitted-order context with cut_order refreshed to ALLOCATED and
    an ``allocations`` list of the order's lines.
    """
    ctx = setup_submitted_cut_order(**kwargs)
    ctx["cut_order"] = allocate_cut_order(ctx["cut_order"]["id"])
    ctx["allocations"] = list_allocations_for_order(ctx["cut_order"]["id"])
    return ctx


def cut_cut_order(cut_order_id: str) -> dict:
    return get_success_data(api_client.cut_cut_order(cut_order_id, PLANNER))


def ship_cut_order(cut_order_id: str) -> dict:
    return get_success_data(api_client.ship_cut_order(cut_order_id, PLANNER))


def cancel_cut_order(cut_order_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.cancel_cut_order(
            cut_order_id, f.cancel_cut_order_payload(), headers or PLANNER
        )
    )


def setup_cut_order_with_remnant(
    initial_yards: float = 200.0,
    requested_yards: float = 180.0,
    **kwargs,
) -> Dict[str, dict]:
    """Cut an order so that the sourced roll leaves a residual under the remnant
    threshold, minting a remnant child roll.

    With the defaults the 200.0-yard roll is drawn down by 180.0 yards, leaving a
    20.0-yard residual: below 30.0, so a remnant child is split off and the
    parent is depleted.

    Returns the order context extended with ``remnant`` (the child roll) and
    ``parent_roll`` (the depleted parent).
    """
    roll_overrides = dict(kwargs.pop("roll_overrides", {}) or {})
    roll_overrides.setdefault("initial_yards", initial_yards)
    order_overrides = dict(kwargs.pop("order_overrides", {}) or {})
    order_overrides.setdefault("requested_yards", requested_yards)
    ctx = setup_allocated_cut_order(
        roll_overrides=roll_overrides, order_overrides=order_overrides, **kwargs
    )
    ctx["cut_order"] = cut_cut_order(ctx["cut_order"]["id"])
    parent_id = ctx["roll_good"]["id"]
    ctx["parent_roll"] = get_success_data(api_client.get_roll_good(parent_id, QA))
    rolls, _ = _paginate(api_client.list_roll_goods, QA)
    ctx["remnant"] = next(
        (r for r in rolls if r.get("parent_roll_id") == parent_id), None
    )
    return ctx


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


def _paginate(list_method, headers: dict, params: Optional[dict] = None):
    """Read one page with an explicit limit, returning (data, meta)."""
    query = {"limit": 100, "offset": 0}
    query.update(params or {})
    response = list_method(headers, params=query)
    body = get_success_data(response)
    meta = response.json().get("meta", {})
    return body, meta


def list_allocations_for_order(cut_order_id: str) -> List[dict]:
    data, _ = _paginate(
        api_client.list_cut_allocations, PLANNER, {"cut_order_id": cut_order_id}
    )
    return data


def list_allocations_for_roll(roll_good_id: str) -> List[dict]:
    data, _ = _paginate(
        api_client.list_cut_allocations, PLANNER, {"roll_good_id": roll_good_id}
    )
    return data


def list_orders_for_account(account_id: str) -> List[dict]:
    data, _ = _paginate(api_client.list_cut_orders, PLANNER, {"account_id": account_id})
    return data


def refresh_account(account_id: str) -> dict:
    return get_success_data(api_client.get_account(account_id, PLANNER))


def refresh_style(style_id: str) -> dict:
    return get_success_data(api_client.get_style(style_id, PLANNER))


def refresh_run(production_run_id: str) -> dict:
    return get_success_data(api_client.get_production_run(production_run_id, PLANNER))


def refresh_dye_lot(dye_lot_id: str) -> dict:
    return get_success_data(api_client.get_dye_lot(dye_lot_id, DYER))


def refresh_roll_good(roll_good_id: str) -> dict:
    return get_success_data(api_client.get_roll_good(roll_good_id, QA))


def refresh_cut_order(cut_order_id: str) -> dict:
    return get_success_data(api_client.get_cut_order(cut_order_id, PLANNER))


def refresh_certification(certification_id: str) -> dict:
    return get_success_data(api_client.get_certification(certification_id, CERTIFIER))


def refresh_polymer_lot(polymer_lot_id: str) -> dict:
    return get_success_data(api_client.get_polymer_lot(polymer_lot_id, EXTRUDER))


def refresh_fiber_batch(fiber_batch_id: str) -> dict:
    return get_success_data(api_client.get_fiber_batch(fiber_batch_id, EXTRUDER))


def get_recycled_content(style_id: str, params: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_style_recycled_content(style_id, CERTIFIER, params=params)
    )
