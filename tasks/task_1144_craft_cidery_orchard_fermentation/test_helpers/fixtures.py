"""Composite setup helpers for multi-step test prerequisites.

Every fixture builds its preconditions from scratch via PRD-declared endpoints
(the runner restarts the server before each test, so nothing carries over).
Setup calls use get_success_data() so failures surface as clear setup errors.
"""
import uuid as _uuid

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_variety_payload, create_contract_payload, create_harvest_lot_payload,
    create_blend_line, create_press_batch_payload, create_tank_payload,
    create_yeast_program_payload, create_fermentation_batch_payload,
    create_product_payload, create_label_approval_payload, create_license_payload,
    create_packaging_run_payload, create_order_payload,
)
from .test_users import TEST_USERS, make_packaging_operator_headers

OM = TEST_USERS["orchard_manager_headers"]
CL = TEST_USERS["cellar_lead_headers"]
CO = TEST_USERS["compliance_officer_headers"]
PO = TEST_USERS["packaging_operator_headers"]
SR = TEST_USERS["sales_rep_headers"]
PA = TEST_USERS["platform_admin_headers"]

# Completer identity differs from the default scheduler identity so the
# segregation-of-duties check (creator X-User-ID != completer X-User-ID) passes.
COMPLETER = make_packaging_operator_headers("test-packaging-completer-1")


def _tok() -> str:
    return _uuid.uuid4().hex[:8].upper()


# ─── Tier 0: clock ──────────────────────────────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the server logical clock; returns the reported now_iso8601."""
    res = api_client.set_clock({"to_iso8601": to_iso8601}, PA)
    return get_success_data(res)


# ─── Tier 1: reference data + contract lifecycle ────────────────────────────

def create_variety(**overrides) -> dict:
    return get_success_data(api_client.create_variety(create_variety_payload(**overrides), OM))


def create_yeast_program(**overrides) -> dict:
    return get_success_data(api_client.create_yeast_program(
        create_yeast_program_payload(**overrides), CL))


def create_active_contract(**overrides) -> dict:
    """Create an OrchardContract and activate it (OCC-guarded). Returns ACTIVE contract."""
    contract = get_success_data(api_client.create_contract(create_contract_payload(**overrides), OM))
    res = api_client.activate_contract(
        contract["id"], {"expected_contract_version": contract["version"]}, OM)
    return get_success_data(res)


def create_harvest_lot(contract_id: str, variety_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_harvest_lot(
        contract_id, create_harvest_lot_payload(variety_id, **overrides), OM))


def create_tank(**overrides) -> dict:
    return get_success_data(api_client.create_tank(create_tank_payload(**overrides), CL))


# ─── Tier 2: press pipeline ─────────────────────────────────────────────────

def create_press_batch(blend_lines, **overrides) -> dict:
    """Create a PLANNED press batch with the given blend lines."""
    return get_success_data(api_client.create_press_batch(
        create_press_batch_payload(blend_lines=blend_lines, **overrides), CL))


def create_complete_press_batch(lot_id: str, weight_lbs: int, actual_juice_liters: int,
                                **overrides) -> dict:
    """PLANNED -> PRESSING -> COMPLETE for a single-lot press batch."""
    batch = create_press_batch([create_blend_line(lot_id, weight_lbs, 1)], **overrides)
    get_success_data(api_client.start_press_batch(batch["id"], CL))
    return get_success_data(api_client.complete_press_batch(
        batch["id"], {"actual_juice_liters": actual_juice_liters}, CL))


def setup_pressed_lot(weight_lbs: int = 1000, measured_brix: float = 13.0,
                      actual_juice_liters: int = None, committed_weight_lbs: int = None):
    """Active contract + one fully PRESSED lot + COMPLETE press batch.

    Returns dict(contract, variety, lot, press_batch).
    """
    variety = create_variety(code=f"V-{_tok()}", brix_at_harvest=measured_brix)
    contract = create_active_contract(
        grower_name=f"G-{_tok()}",
        committed_weight_lbs=committed_weight_lbs or weight_lbs)
    lot = create_harvest_lot(contract["id"], variety["id"],
                             weight_lbs=weight_lbs, measured_brix=measured_brix)
    press_batch = create_complete_press_batch(
        lot["id"], weight_lbs, actual_juice_liters or weight_lbs // 2)
    return {"contract": contract, "variety": variety, "lot": lot, "press_batch": press_batch}


# ─── Tier 3: fermentation lifecycle ─────────────────────────────────────────

def create_pitched_batch(press_batch_id: str, volume_liters: int,
                         tank_capacity: int = None, **yeast_overrides) -> dict:
    """Pitch a COMPLETE press batch into a fresh tank. Returns dict(tank, yeast, batch)."""
    tank = create_tank(code=f"T-{_tok()}",
                       capacity_liters=tank_capacity or max(volume_liters * 2, 100))
    yeast = create_yeast_program(code=f"Y-{_tok()}", **yeast_overrides)
    batch = get_success_data(api_client.create_fermentation_batch(
        create_fermentation_batch_payload(press_batch_id, tank["id"], yeast["id"]), CL))
    return {"tank": tank, "yeast": yeast, "batch": batch}


def setup_fermenting_batch(weight_lbs: int = 200, measured_brix: float = 13.0,
                           actual_juice_liters: int = 50, gravity_brix: float = 4.0,
                           committed_weight_lbs: int = None) -> dict:
    """Full chain to a FERMENTING batch (one reading below original gravity).

    Returns dict(contract, variety, lot, press_batch, tank, yeast, batch).
    """
    chain = setup_pressed_lot(weight_lbs=weight_lbs, measured_brix=measured_brix,
                              actual_juice_liters=actual_juice_liters,
                              committed_weight_lbs=committed_weight_lbs)
    pitch = create_pitched_batch(chain["press_batch"]["id"], actual_juice_liters)
    batch = get_success_data(api_client.record_reading(
        pitch["batch"]["id"], {"gravity_brix": gravity_brix}, CL))
    return {**chain, "tank": pitch["tank"], "yeast": pitch["yeast"], "batch": batch}


def setup_ready_batch(weight_lbs: int = 200, measured_brix: float = 13.0,
                      actual_juice_liters: int = 50, gravity_brix: float = 4.0,
                      age_at: str = "2026-10-01T00:00:00Z",
                      ready_at: str = "2026-10-20T00:00:00Z",
                      committed_weight_lbs: int = None) -> dict:
    """Full chain to a READY fermentation batch.

    aging duration between age_at and ready_at must be >= 14 days on the
    logical clock (the default gap is 19 days).
    """
    set_clock(age_at)
    chain = setup_fermenting_batch(
        weight_lbs=weight_lbs, measured_brix=measured_brix,
        actual_juice_liters=actual_juice_liters, gravity_brix=gravity_brix,
        committed_weight_lbs=committed_weight_lbs)
    batch = get_success_data(api_client.age_batch(chain["batch"]["id"], CL))
    assert batch["status"] == "AGING", f"Setup failed: batch not AGING, got {batch['status']}"
    set_clock(ready_at)
    batch = get_success_data(api_client.ready_batch(batch["id"], CL))
    assert batch["status"] == "READY", f"Setup failed: batch not READY, got {batch['status']}"
    return {**chain, "batch": batch}


# ─── Tier 4: product / label / license ──────────────────────────────────────

def setup_active_product(target_abv_pct: float = 5.0,
                         extra_markets=(), **product_overrides) -> dict:
    """ACTIVE product with an APPROVED FEDERAL_TTB label (plus any extra markets,
    each submitted and approved). Returns dict(product, labels)."""
    product = get_success_data(api_client.create_product(
        create_product_payload(sku=f"SKU-{_tok()}", target_abv_pct=target_abv_pct,
                               **product_overrides), CO))
    labels = {}
    federal = get_success_data(api_client.create_label_approval(
        product["id"], create_label_approval_payload(
            market="FEDERAL_TTB", application_number=f"TTB-{_tok()}"), CO))
    labels["FEDERAL_TTB"] = get_success_data(api_client.approve_label(federal["id"], CO))
    for market in extra_markets:
        label = get_success_data(api_client.create_label_approval(
            product["id"], create_label_approval_payload(
                market=market, application_number=f"{market}-{_tok()}"), CO))
        labels[market] = get_success_data(api_client.approve_label(label["id"], CO))
    product = get_success_data(api_client.activate_product(product["id"], CO))
    assert product["status"] == "ACTIVE", f"Setup failed: product not ACTIVE"
    return {"product": product, "labels": labels}


def create_license(**overrides) -> dict:
    return get_success_data(api_client.create_license(create_license_payload(**overrides), CO))


# ─── Tier 5: packaging pipeline ─────────────────────────────────────────────

def setup_packaging_ready(volume_liters: int = 50, measured_brix: float = 13.0,
                          gravity_brix: float = 4.0, target_abv_pct: float = 5.0,
                          license_overrides=None, extra_markets=(),
                          package_format: str = "BOTTLE_500ML",
                          run_volume_liters: int = None,
                          creator_headers=None) -> dict:
    """READY batch + ACTIVE product (FEDERAL_TTB approved) + ACTIVE license +
    one SCHEDULED packaging run drawing `run_volume_liters` (default: all of
    `volume_liters`). Returns the full context dict."""
    chain = setup_ready_batch(actual_juice_liters=volume_liters,
                              measured_brix=measured_brix, gravity_brix=gravity_brix)
    prod = setup_active_product(target_abv_pct=target_abv_pct, extra_markets=extra_markets)
    license_ = create_license(**(license_overrides or {}))
    run = get_success_data(api_client.create_packaging_run(
        create_packaging_run_payload(
            prod["product"]["id"], chain["batch"]["id"],
            prod["labels"]["FEDERAL_TTB"]["id"], license_["id"],
            package_format=package_format,
            volume_liters=run_volume_liters or volume_liters),
        creator_headers or PO))
    return {**chain, **prod, "license": license_, "run": run}


def complete_run(run_id: str, batch_id: str, headers=None) -> dict:
    """Complete a SCHEDULED run, threading the batch's current version for OCC.
    Defaults to a completer identity distinct from the scheduling operator."""
    batch = get_success_data(api_client.get_fermentation_batch(batch_id, PO))
    return get_success_data(api_client.complete_packaging_run(
        run_id, {"expected_batch_version": batch["version"]}, headers or COMPLETER))


def setup_completed_packaging_run(volume_liters: int = 50, **kwargs) -> dict:
    """Packaging pipeline driven through to a COMPLETED run."""
    ctx = setup_packaging_ready(volume_liters=volume_liters, **kwargs)
    ctx["run"] = complete_run(ctx["run"]["id"], ctx["batch"]["id"])
    assert ctx["run"]["status"] == "COMPLETED", "Setup failed: run not COMPLETED"
    ctx["batch"] = get_success_data(
        api_client.get_fermentation_batch(ctx["batch"]["id"], PO))
    return ctx
