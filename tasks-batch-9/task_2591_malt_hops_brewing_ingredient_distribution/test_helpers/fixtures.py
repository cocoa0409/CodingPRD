"""Composite setup helpers.

Every helper drives the public API only and uses the lenient ``get_success_data``
validator, so a broken precondition surfaces as a setup failure rather than as a
confusing assertion inside a test body.

Two rules are honoured throughout:

* the logical clock is pinned explicitly by ``pin_clock`` before anything else,
  because every temporal rule in the PRD reads that clock (PRD §2.5);
* a ``Brewer`` actor's ``X-User-ID`` is the id of the acting ``Brewer`` entity
  (PRD §2.1), so every ownership-gated call goes through
  ``make_brewer_headers(brewer["id"])``.
"""
from itertools import count

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .test_users import (
    TEST_USERS,
    make_allocation_manager_headers,
    make_brewer_headers,
    make_warehouse_operator_headers,
)

# ── Shared operator headers ───────────────────────────────────────────────
AM_HEADERS = TEST_USERS["allocation_manager_headers"]
CM_HEADERS = TEST_USERS["credit_manager_headers"]
WH_HEADERS = TEST_USERS["warehouse_operator_headers"]
PA_HEADERS = TEST_USERS["platform_admin_headers"]

# Two distinct warehouse identities, for the malt-lot release segregation gate.
ANALYST_USER_ID = "qa-analyst-1"
RELEASER_USER_ID = "qa-analyst-2"
ANALYST_HEADERS = make_warehouse_operator_headers(ANALYST_USER_ID)
RELEASER_HEADERS = make_warehouse_operator_headers(RELEASER_USER_ID)

# Two distinct hop-desk identities, for the resale segregation gate.
ALLOC_1_USER_ID = "alloc-mgr-1"
ALLOC_2_USER_ID = "alloc-mgr-2"
ALLOC_1_HEADERS = make_allocation_manager_headers(ALLOC_1_USER_ID)
ALLOC_2_HEADERS = make_allocation_manager_headers(ALLOC_2_USER_ID)

_SEQ = count(1)


def _next(prefix: str) -> str:
    return f"{prefix}-{next(_SEQ):04d}"


# ── Tier 0: the logical clock ─────────────────────────────────────────────
def pin_clock(instant: str = DEFAULT_CLOCK) -> dict:
    """Pin the logical clock. PlatformAdmin-only capability (PRD §2.5)."""
    return get_success_data(api_client.set_clock(instant, PA_HEADERS))


# ── Tier 1: single reference-data rows ────────────────────────────────────
def create_brewer(name="Test Brewing Co", credit_limit_cents=5000000,
                  cold_chain_certified=True, legacy_trailing_lbs=0,
                  credit_terms_days=30, **overrides) -> dict:
    payload = {
        "name": name,
        "brewery_license_no": _next("BR"),
        "credit_terms_days": credit_terms_days,
        "credit_limit_cents": credit_limit_cents,
        "cold_chain_certified": cold_chain_certified,
        "legacy_trailing_lbs": legacy_trailing_lbs,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_brewer(payload, CM_HEADERS))


def create_program(crop_year=2026, **overrides) -> dict:
    payload = {
        "crop_year": crop_year,
        "contract_open_date": f"{crop_year}-01-15T00:00:00Z",
        "harvest_report_due_date": f"{crop_year}-10-01T00:00:00Z",
    }
    payload.update(overrides)
    return get_success_data(
        api_client.create_crop_year_program(payload, AM_HEADERS))


def create_variety(variety_code="CITRA", name="Citra",
                   substitution_group="AROMA_HIGH_ALPHA",
                   alpha_acid_target_pct=12.50, spot_price_cents_per_lb=51.00,
                   available_spot_lbs=20000, cold_storage_required=True,
                   pallet_quantity_lbs=880, min_order_lbs=44,
                   **overrides) -> dict:
    payload = {
        "variety_code": variety_code,
        "name": name,
        "substitution_group": substitution_group,
        "alpha_acid_target_pct": alpha_acid_target_pct,
        "spot_price_cents_per_lb": spot_price_cents_per_lb,
        "available_spot_lbs": available_spot_lbs,
        "cold_storage_required": cold_storage_required,
        "pallet_quantity_lbs": pallet_quantity_lbs,
        "min_order_lbs": min_order_lbs,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_hop_variety(payload, AM_HEADERS))


def create_malt_product(sku="PALE-ALE", name="Pale Ale Malt", malt_class="BASE",
                        list_price_cents_per_lb=68.50, max_moisture_pct=5.0,
                        min_diastatic_power=60.0, pallet_quantity_lbs=2200,
                        min_order_lbs=55, **overrides) -> dict:
    payload = {
        "sku": sku,
        "name": name,
        "malt_class": malt_class,
        "list_price_cents_per_lb": list_price_cents_per_lb,
        "max_moisture_pct": max_moisture_pct,
        "min_diastatic_power": min_diastatic_power,
        "pallet_quantity_lbs": pallet_quantity_lbs,
        "min_order_lbs": min_order_lbs,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_malt_product(payload, WH_HEADERS))


def create_strain(strain_code="WLP001", name="California Ale",
                  fermentation_type="ALE", propagation_lead_time_days=7,
                  list_price_cents_per_l=1200.00, viability_pct_at_ship=92.0,
                  cells_per_ml_slurry_billion=1.2, min_batch_l=20.0,
                  vessel_max_l=2000.0, **overrides) -> dict:
    payload = {
        "strain_code": strain_code,
        "name": name,
        "fermentation_type": fermentation_type,
        "propagation_lead_time_days": propagation_lead_time_days,
        "list_price_cents_per_l": list_price_cents_per_l,
        "viability_pct_at_ship": viability_pct_at_ship,
        "cells_per_ml_slurry_billion": cells_per_ml_slurry_billion,
        "min_batch_l": min_batch_l,
        "vessel_max_l": vessel_max_l,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_yeast_strain(payload, WH_HEADERS))


def create_zone(zone_code="Z1", temp_setpoint_c=2.0, capacity_pallets=10,
                tolerance_c=2.0, **overrides) -> dict:
    payload = {
        "zone_code": zone_code,
        "temp_setpoint_c": temp_setpoint_c,
        "capacity_pallets": capacity_pallets,
        "tolerance_c": tolerance_c,
    }
    payload.update(overrides)
    return get_success_data(
        api_client.create_cold_storage_zone(payload, WH_HEADERS))


# ── Tier 2: malt lots walked through their state machine ──────────────────
PASSING_ANALYSIS = {
    "color_lovibond": 2.60,
    "extract_pct": 79.90,
    "moisture_pct": 4.20,
    "protein_pct": 11.10,
    "diastatic_power": 92.00,
}


def create_lot(malt_product_id, quantity_lbs=20000, lot_code=None,
               **overrides) -> dict:
    payload = {
        "malt_product_id": malt_product_id,
        "lot_code": lot_code or _next("LOT"),
        "quantity_lbs": quantity_lbs,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_malt_lot(payload, WH_HEADERS))


def analyse_lot(lot_id, headers=None, **analysis) -> dict:
    """File an analysis sheet. Defaults to a sheet that passes BASE malt."""
    payload = dict(PASSING_ANALYSIS)
    payload.update(analysis)
    return get_success_data(
        api_client.record_analysis(lot_id, payload, headers or ANALYST_HEADERS))


def release_lot(lot_id, headers=None, release_note="cleared for picking") -> dict:
    """Release a PASSED lot as a *different* operator (PRD §2.9)."""
    return get_success_data(api_client.release_malt_lot(
        lot_id, {"release_note": release_note}, headers or RELEASER_HEADERS))


def create_passed_lot(malt_product_id, quantity_lbs=20000, lot_code=None,
                      **analysis) -> dict:
    """Lot in PASSED: received then analysed by qa-analyst-1."""
    lot = create_lot(malt_product_id, quantity_lbs=quantity_lbs,
                     lot_code=lot_code)
    return analyse_lot(lot["id"], **analysis)


def create_released_lot(malt_product_id, quantity_lbs=20000, lot_code=None,
                        **analysis) -> dict:
    """Lot in RELEASED: analysed by qa-analyst-1, released by qa-analyst-2."""
    lot = create_passed_lot(malt_product_id, quantity_lbs=quantity_lbs,
                            lot_code=lot_code, **analysis)
    return release_lot(lot["id"])


def create_quarantined_lot(malt_product_id, quantity_lbs=20000, lot_code=None,
                           **analysis) -> dict:
    """Lot in QUARANTINED via a moisture sheet above the product ceiling."""
    failing = {"moisture_pct": 6.10}
    failing.update(analysis)
    return create_passed_lot(malt_product_id, quantity_lbs=quantity_lbs,
                             lot_code=lot_code, **failing)


# ── Tier 2: contracts and crop-year programs ──────────────────────────────
def create_contract(brewer_id, variety_id, crop_year_program_id,
                    contracted_lbs=5000, price_per_lb_cents=250.00,
                    contract_type="FIXED_CROP_YEAR",
                    delivery_window_start="2026-09-01T00:00:00Z",
                    delivery_window_end="2026-12-31T00:00:00Z",
                    **overrides) -> dict:
    payload = {
        "brewer_id": brewer_id,
        "variety_id": variety_id,
        "crop_year_program_id": crop_year_program_id,
        "contract_type": contract_type,
        "contracted_lbs": contracted_lbs,
        "price_per_lb_cents": price_per_lb_cents,
        "delivery_window_start": delivery_window_start,
        "delivery_window_end": delivery_window_end,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_hop_contract(payload, AM_HEADERS))


def report_harvest(program_id, harvest_yield_pct=100.00,
                   reported_note="full crop") -> dict:
    payload = {"harvest_yield_pct": harvest_yield_pct,
               "reported_note": reported_note}
    return get_success_data(
        api_client.report_harvest(program_id, payload, AM_HEADERS))


def declare_default(contract_id, default_reason="brewer walked away",
                    headers=None) -> dict:
    return get_success_data(api_client.declare_default(
        contract_id, {"default_reason": default_reason},
        headers or ALLOC_1_HEADERS))


def request_carry_forward(contract_id, brewer_id, target_program_id,
                          requested_lbs, justification="tank space") -> dict:
    payload = {
        "carry_forward_target_program_id": target_program_id,
        "requested_lbs": requested_lbs,
        "justification": justification,
    }
    return get_success_data(api_client.request_carry_forward(
        contract_id, payload, make_brewer_headers(brewer_id)))


def decide_carry_forward(contract_id, decision, decision_note="decided") -> dict:
    return get_success_data(api_client.decide_carry_forward(
        contract_id, {"decision": decision, "decision_note": decision_note},
        AM_HEADERS))


def contract_version(contract_id) -> int:
    return get_success_data(
        api_client.get_hop_contract(contract_id, AM_HEADERS))["version"]

# ── Tier 2: credit posture ────────────────────────────────────────────────
def set_credit_limit(brewer_id, credit_limit_cents, **overrides) -> dict:
    """Re-profile a brewer. Carries the OCC guard the PRD requires (PRD §2.7)."""
    current = get_success_data(api_client.get_brewer(brewer_id, CM_HEADERS))
    payload = {
        "expected_brewer_version": current["version"],
        "credit_limit_cents": credit_limit_cents,
    }
    payload.update(overrides)
    return get_success_data(
        api_client.update_credit_profile(brewer_id, payload, CM_HEADERS))


def set_trailing_volume(brewer_id, legacy_trailing_lbs, note="backfill") -> dict:
    payload = {"legacy_trailing_lbs": legacy_trailing_lbs, "note": note}
    return get_success_data(
        api_client.post_volume_adjustment(brewer_id, payload, PA_HEADERS))


def get_brewer(brewer_id) -> dict:
    return get_success_data(api_client.get_brewer(brewer_id, CM_HEADERS))


# ── Tier 2: recipes and yeast propagation jobs ────────────────────────────
def create_recipe(brewer_id, malt_product_id, yeast_strain_id,
                  name="House Ale", batch_volume_bbl=30.00,
                  original_gravity_plato=15.00, target_color_lovibond=3.00,
                  target_extract_pct=80.00, target_protein_pct=10.50,
                  requested_pitch_rate_million_cells_per_ml_per_plato=0.75,
                  **overrides) -> dict:
    payload = {
        "brewer_id": brewer_id,
        "malt_product_id": malt_product_id,
        "yeast_strain_id": yeast_strain_id,
        "name": name,
        "batch_volume_bbl": batch_volume_bbl,
        "original_gravity_plato": original_gravity_plato,
        "target_color_lovibond": target_color_lovibond,
        "target_extract_pct": target_extract_pct,
        "target_protein_pct": target_protein_pct,
    }
    if requested_pitch_rate_million_cells_per_ml_per_plato is not None:
        payload["requested_pitch_rate_million_cells_per_ml_per_plato"] = \
            requested_pitch_rate_million_cells_per_ml_per_plato
    payload.update(overrides)
    return get_success_data(api_client.create_brewer_recipe(
        payload, make_brewer_headers(brewer_id)))


def create_job(brewer_id, recipe_id, yeast_strain_id,
               pitch_date="2026-08-22T00:00:00Z", **overrides) -> dict:
    payload = {
        "brewer_id": brewer_id,
        "recipe_id": recipe_id,
        "yeast_strain_id": yeast_strain_id,
        "pitch_date": pitch_date,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_propagation_job(
        payload, make_brewer_headers(brewer_id)))


def complete_propagation(job_id, outcome="READY", failure_reason=None) -> dict:
    payload = {"outcome": outcome}
    if failure_reason is not None:
        payload["failure_reason"] = failure_reason
    return get_success_data(
        api_client.complete_propagation(job_id, payload, WH_HEADERS))


def create_ready_job(brewer_id, recipe_id, yeast_strain_id,
                     pitch_date="2026-08-22T00:00:00Z", **overrides) -> dict:
    """A propagation job walked REQUESTED -> PROPAGATING -> READY."""
    job = create_job(brewer_id, recipe_id, yeast_strain_id,
                     pitch_date=pitch_date, **overrides)
    get_success_data(api_client.start_propagation(job["id"], WH_HEADERS))
    return complete_propagation(job["id"], outcome="READY")


# ── Tier 2: sales orders and their lines ──────────────────────────────────
def create_order(brewer_id, requested_ship_date="2026-09-15T00:00:00Z",
                 **overrides) -> dict:
    payload = {"brewer_id": brewer_id,
               "requested_ship_date": requested_ship_date}
    payload.update(overrides)
    return get_success_data(api_client.create_sales_order(
        payload, make_brewer_headers(brewer_id)))


def add_line(order_id, brewer_id, payload) -> dict:
    return get_success_data(api_client.add_order_line(
        order_id, payload, make_brewer_headers(brewer_id)))


def add_spot_hop_line(order_id, brewer_id, hop_variety_id, quantity,
                      **overrides) -> dict:
    payload = {
        "item_type": "HOP",
        "quantity": quantity,
        "uom": "LB",
        "allocation_source": "SPOT",
        "hop_variety_id": hop_variety_id,
    }
    payload.update(overrides)
    return add_line(order_id, brewer_id, payload)


def add_contract_hop_line(order_id, brewer_id, hop_variety_id, hop_contract_id,
                          quantity, **overrides) -> dict:
    payload = {
        "item_type": "HOP",
        "quantity": quantity,
        "uom": "LB",
        "allocation_source": "CONTRACT",
        "hop_variety_id": hop_variety_id,
        "hop_contract_id": hop_contract_id,
    }
    payload.update(overrides)
    return add_line(order_id, brewer_id, payload)


def add_malt_line(order_id, brewer_id, malt_lot_id, quantity, **overrides) -> dict:
    payload = {
        "item_type": "MALT",
        "quantity": quantity,
        "uom": "LB",
        "malt_lot_id": malt_lot_id,
    }
    payload.update(overrides)
    return add_line(order_id, brewer_id, payload)


def add_yeast_line(order_id, brewer_id, job_id, quantity, **overrides) -> dict:
    payload = {
        "item_type": "YEAST",
        "quantity": quantity,
        "uom": "L",
        "yeast_propagation_job_id": job_id,
    }
    payload.update(overrides)
    return add_line(order_id, brewer_id, payload)


def confirm_order(order_id, brewer_id) -> dict:
    return get_success_data(api_client.confirm_order(
        order_id, make_brewer_headers(brewer_id)))


def approve_credit(order_id, note="within limit") -> dict:
    return get_success_data(api_client.record_credit_decision(
        order_id, {"decision": "APPROVE", "decision_note": note}, CM_HEADERS))


def hold_credit(order_id, note="over limit") -> dict:
    return get_success_data(api_client.record_credit_decision(
        order_id, {"decision": "HOLD", "decision_note": note}, CM_HEADERS))


def pick_order(order_id) -> dict:
    return get_success_data(api_client.pick_order(order_id, WH_HEADERS))


def ship_order(order_id) -> dict:
    return get_success_data(api_client.ship_order(order_id, WH_HEADERS))


def deliver_order(order_id) -> dict:
    return get_success_data(api_client.deliver_order(order_id, WH_HEADERS))


def cancel_order(order_id, headers=None, cancel_reason="brewer withdrew") -> dict:
    return get_success_data(api_client.cancel_order(
        order_id, {"cancel_reason": cancel_reason}, headers or AM_HEADERS))


def order_version(order_id, headers=None) -> int:
    return get_success_data(
        api_client.get_sales_order(order_id, headers or AM_HEADERS))["version"]


def get_order(order_id, headers=None) -> dict:
    return get_success_data(
        api_client.get_sales_order(order_id, headers or AM_HEADERS))


# ── Tier 2: cold-chain staging and transit ────────────────────────────────
def stage_shipment(order_id, zone_id, pallet_count=4,
                   stage_from="2026-08-01T08:00:00Z",
                   stage_until="2026-08-01T16:00:00Z",
                   reefer_setpoint_c=2.00, **overrides) -> dict:
    """Stage a shipment, reading the order's current version for the guard."""
    payload = {
        "sales_order_id": order_id,
        "cold_storage_zone_id": zone_id,
        "expected_sales_order_version": order_version(order_id),
        "pallet_count": pallet_count,
        "stage_from": stage_from,
        "stage_until": stage_until,
        "reefer_setpoint_c": reefer_setpoint_c,
    }
    payload.update(overrides)
    return get_success_data(api_client.stage_shipment(payload, WH_HEADERS))


def depart_shipment(shipment_id) -> dict:
    return get_success_data(api_client.depart_shipment(shipment_id, WH_HEADERS))


def add_reading(shipment_id, temp_c, recorded_at, **overrides) -> dict:
    payload = {"temp_c": temp_c, "recorded_at": recorded_at}
    payload.update(overrides)
    return get_success_data(
        api_client.add_reading(shipment_id, payload, WH_HEADERS))


def get_zone(zone_id) -> dict:
    return get_success_data(
        api_client.get_cold_storage_zone(zone_id, WH_HEADERS))


def get_shipment(shipment_id) -> dict:
    return get_success_data(api_client.get_shipment(shipment_id, WH_HEADERS))


# ── Tier 3: a pinned world of reference data ──────────────────────────────
def base_world(clock=DEFAULT_CLOCK, **brewer_overrides) -> dict:
    """Pin the clock and mint one row of every reference entity.

    Returns a dict with keys ``brewer``, ``program``, ``variety``,
    ``malt_product``, ``strain`` and ``zone``. Every caller may override any
    single row afterwards; the brewer keywords are forwarded so credit posture
    and cold-chain certification can be dialled in up front.
    """
    pin_clock(clock)
    return {
        "brewer": create_brewer(**brewer_overrides),
        "program": create_program(),
        "variety": create_variety(),
        "malt_product": create_malt_product(),
        "strain": create_strain(),
        "zone": create_zone(),
    }


# ── Tier 4: orders parked at a named lifecycle state ──────────────────────
def setup_confirmed_malt_order(quantity_lbs=1000, lot_quantity_lbs=20000,
                               approve=True, **brewer_overrides) -> dict:
    """A CONFIRMED order carrying one MALT line drawn from a RELEASED lot."""
    world = base_world(**brewer_overrides)
    brewer, product = world["brewer"], world["malt_product"]
    lot = create_released_lot(product["id"], quantity_lbs=lot_quantity_lbs)
    order = create_order(brewer["id"])
    line = add_malt_line(order["id"], brewer["id"], lot["id"], quantity_lbs)
    order = confirm_order(order["id"], brewer["id"])
    if approve:
        order = approve_credit(order["id"])
    world.update({"lot": lot, "order": order, "line": line})
    return world


def setup_confirmed_spot_hop_order(quantity_lbs=880, approve=True,
                                   **brewer_overrides) -> dict:
    """A CONFIRMED order carrying one SPOT hop line for a cold-stored variety."""
    world = base_world(**brewer_overrides)
    brewer, variety = world["brewer"], world["variety"]
    order = create_order(brewer["id"])
    line = add_spot_hop_line(order["id"], brewer["id"], variety["id"],
                             quantity_lbs)
    order = confirm_order(order["id"], brewer["id"])
    if approve:
        order = approve_credit(order["id"])
    world.update({"order": order, "line": line})
    return world


def setup_picked_order(quantity_lbs=880, **brewer_overrides) -> dict:
    """A PICKED order, ready to be staged into a cold-storage zone."""
    world = setup_confirmed_spot_hop_order(quantity_lbs=quantity_lbs,
                                           **brewer_overrides)
    world["order"] = pick_order(world["order"]["id"])
    return world


def setup_staged_shipment(quantity_lbs=880, pallet_count=4,
                          stage_from="2026-08-01T08:00:00Z",
                          stage_until="2026-08-01T16:00:00Z",
                          **brewer_overrides) -> dict:
    """A PICKED order with a STAGED shipment occupying zone pallet space."""
    world = setup_picked_order(quantity_lbs=quantity_lbs, **brewer_overrides)
    world["shipment"] = stage_shipment(
        world["order"]["id"], world["zone"]["id"], pallet_count=pallet_count,
        stage_from=stage_from, stage_until=stage_until)
    return world


def setup_in_transit_shipment(quantity_lbs=880, pallet_count=4,
                              **brewer_overrides) -> dict:
    """A departed shipment, i.e. one that can accept temperature readings."""
    world = setup_staged_shipment(quantity_lbs=quantity_lbs,
                                  pallet_count=pallet_count, **brewer_overrides)
    world["shipment"] = depart_shipment(world["shipment"]["id"])
    return world


# ── Tier 4: contracts parked at a named lifecycle state ───────────────────
def setup_active_contract(contracted_lbs=5000, price_per_lb_cents=250.00,
                          **brewer_overrides) -> dict:
    """An ACTIVE fixed-crop-year contract on a 2026 program still OPEN."""
    world = base_world(**brewer_overrides)
    world["contract"] = create_contract(
        world["brewer"]["id"], world["variety"]["id"], world["program"]["id"],
        contracted_lbs=contracted_lbs, price_per_lb_cents=price_per_lb_cents)
    return world


def setup_shortfall_adjusted_contract(contracted_lbs=5000,
                                      price_per_lb_cents=250.00,
                                      harvest_yield_pct=80.00,
                                      **brewer_overrides) -> dict:
    """An ACTIVE contract trimmed by a short harvest on its crop-year program."""
    world = setup_active_contract(contracted_lbs=contracted_lbs,
                                  price_per_lb_cents=price_per_lb_cents,
                                  **brewer_overrides)
    world["program"] = report_harvest(world["program"]["id"],
                                      harvest_yield_pct=harvest_yield_pct)
    world["contract"] = get_success_data(
        api_client.get_hop_contract(world["contract"]["id"], AM_HEADERS))
    return world


def setup_defaulted_contract(contracted_lbs=5000, price_per_lb_cents=250.00,
                             harvest_yield_pct=100.00,
                             **brewer_overrides) -> dict:
    """A DEFAULTED contract, with its settlement posted against the brewer."""
    world = setup_active_contract(contracted_lbs=contracted_lbs,
                                  price_per_lb_cents=price_per_lb_cents,
                                  **brewer_overrides)
    world["program"] = report_harvest(world["program"]["id"],
                                      harvest_yield_pct=harvest_yield_pct)
    world["contract"] = declare_default(world["contract"]["id"])
    return world


def setup_carry_forward_pending(contracted_lbs=5000, requested_lbs=1250,
                                **brewer_overrides) -> dict:
    """A contract in CARRY_FORWARD_PENDING with a 2027 successor program open."""
    world = setup_active_contract(contracted_lbs=contracted_lbs,
                                  **brewer_overrides)
    world["program_next"] = create_program(crop_year=2027)
    world["contract"] = request_carry_forward(
        world["contract"]["id"], world["brewer"]["id"],
        world["program_next"]["id"], requested_lbs)
    return world


# ── Tier 5: a brewer forced onto credit HOLD ───────────────────────────────
def setup_credit_hold_brewer(quantity_lbs=880, credit_limit_cents=100000,
                             **brewer_overrides) -> dict:
    """A CONFIRMED order whose exposure pushes its brewer's posture to HOLD.

    The limit is re-profiled *after* the order is confirmed so that the exposure
    the order books is what trips the posture, rather than the confirmation
    being refused up front.
    """
    world = setup_confirmed_spot_hop_order(quantity_lbs=quantity_lbs,
                                           approve=False, **brewer_overrides)
    world["brewer"] = set_credit_limit(world["brewer"]["id"],
                                      credit_limit_cents)
    return world
