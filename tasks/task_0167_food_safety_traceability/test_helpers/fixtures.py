"""Composite setup helpers for multi-step test prerequisites.

Most interesting claims require the system to be in a specific state that takes
several API calls to reach (facility + supplier + ingredient + received lot +
release + production-run + consumed-lots + finalize, etc.). These helpers
encapsulate those preambles so tests focus on assertions.

Uses get_success_data() (lenient validator) internally, so setup failures
produce clear "Setup step failed" errors instead of confusing assertion
failures. The harness restarts the server (empty DB) before every test, so each
helper builds its preconditions from scratch.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_facility_payload,
    create_supplier_payload,
    create_ingredient_payload,
    create_allergen_profile_payload,
    create_lot_payload,
    create_coa_payload,
    decide_coa_payload,
    create_production_run_payload,
    create_consumed_lot_payload,
    finalize_payload,
    create_hold_order_payload,
    resolve_hold_payload,
    create_zone_payload,
    create_booking_payload,
    advance_clock_payload,
)
from .test_users import TEST_USERS

QM = TEST_USERS["quality_manager_headers"]
CLERK = TEST_USERS["receiving_clerk_headers"]
OP = TEST_USERS["production_operator_headers"]
AUDITOR = TEST_USERS["safety_auditor_headers"]


# ─── Tier 1: Base resources ───────────────────────────────────────────────

def create_facility(initial_utc="2026-01-01T00:00:00Z", **overrides):
    """Create a facility seeded to initial_utc. Returns the facility dict."""
    res = api_client.create_facility(
        create_facility_payload(initial_utc=initial_utc, **overrides), QM)
    return get_success_data(res)


def advance_clock(facility_id, to_utc):
    """Step the facility clock forward; returns the facility dict."""
    res = api_client.advance_clock(facility_id, advance_clock_payload(to_utc), QM)
    return get_success_data(res)


def create_supplier(facility_id, coa_required=False, **overrides):
    res = api_client.create_supplier(
        create_supplier_payload(facility_id, coa_required=coa_required, **overrides), QM)
    return get_success_data(res)


def create_ingredient(facility_id, **overrides):
    res = api_client.create_ingredient(
        create_ingredient_payload(facility_id, **overrides), QM)
    return get_success_data(res)


def create_allergen_profile(facility_id, code, severity_rank, **overrides):
    res = api_client.create_allergen_profile(
        create_allergen_profile_payload(facility_id, code, severity_rank, **overrides), QM)
    return get_success_data(res)


def setup_facility_supplier_ingredient(initial_utc="2026-01-01T00:00:00Z",
                                       coa_required=False, ingredient_overrides=None,
                                       supplier_overrides=None):
    """Facility + one supplier + one ingredient. Returns (facility, supplier, ingredient)."""
    facility = create_facility(initial_utc=initial_utc)
    supplier = create_supplier(facility["id"], coa_required=coa_required,
                               **(supplier_overrides or {}))
    ingredient = create_ingredient(facility["id"], **(ingredient_overrides or {}))
    return facility, supplier, ingredient


# ─── Tier 2: Lots ─────────────────────────────────────────────────────────

def receive_lot(facility_id, ingredient_id, lot_code, supplier_id=None, **overrides):
    """Receive a RAW_MATERIAL lot. Returns the lot dict."""
    payload = create_lot_payload(facility_id, ingredient_id, lot_code, **overrides)
    if supplier_id is not None:
        payload["supplier_id"] = supplier_id
    res = api_client.create_lot(payload, CLERK)
    return get_success_data(res)


def release_lot(lot_id):
    res = api_client.release_lot(lot_id, QM)
    return get_success_data(res)


def setup_released_lot(coa_required=False, initial_utc="2026-01-01T00:00:00Z",
                       lot_overrides=None, ingredient_overrides=None):
    """Facility + supplier + ingredient + one RELEASED raw lot.

    Returns (facility, supplier, ingredient, lot). The returned lot dict is the
    post-release representation.
    """
    facility, supplier, ingredient = setup_facility_supplier_ingredient(
        initial_utc=initial_utc, coa_required=coa_required,
        ingredient_overrides=ingredient_overrides)
    lot = receive_lot(facility["id"], ingredient["id"], "L",
                      supplier_id=supplier["id"], **(lot_overrides or {}))
    released = release_lot(lot["id"])
    return facility, supplier, ingredient, released


# ─── Tier 3: Certificates of Analysis ─────────────────────────────────────

def attach_coa(lot_id, **overrides):
    res = api_client.create_coa(create_coa_payload(lot_id, **overrides), CLERK)
    return get_success_data(res)


def decide_coa(coa_id, decision):
    res = api_client.decide_coa(coa_id, decide_coa_payload(decision), QM)
    return get_success_data(res)


def setup_supplier_suspended(initial_utc="2026-01-01T00:00:00Z"):
    """Drive a coa_required supplier to SUSPENDED via three consecutive rejected COAs.

    Returns (facility, supplier_id, ingredient). The supplier is SUSPENDED
    (failed_coa_streak == 3) after this returns.
    """
    facility = create_facility(initial_utc=initial_utc)
    supplier = create_supplier(facility["id"], coa_required=True)
    ingredient = create_ingredient(facility["id"], declared_allergen_codes=["SOY"],
                                   shelf_life_days=365)
    for i in range(3):
        lot = receive_lot(facility["id"], ingredient["id"], f"SUS{i}",
                          supplier_id=supplier["id"], received_qty=5)
        coa = attach_coa(lot["id"], measured_allergen_codes=["SOY"], pathogen_pass=True,
                         declared_shelf_life_days=365)
        decide_coa(coa["id"], "REJECT")
    return facility, supplier["id"], ingredient


# ─── Tier 4: Production runs and finished-lot genealogy ────────────────────

def open_run(facility_id, ingredient_id, planned_output_qty=10, **overrides):
    res = api_client.create_production_run(
        create_production_run_payload(facility_id, ingredient_id,
                                      planned_output_qty=planned_output_qty, **overrides), OP)
    return get_success_data(res)


def add_consumed_lot(run_id, source_lot_id, quantity):
    res = api_client.add_consumed_lot(
        run_id, create_consumed_lot_payload(source_lot_id, quantity), OP)
    return get_success_data(res)


def current_run_version(run_id):
    res = api_client.get_production_run(run_id, OP)
    return get_success_data(res)["version"]


def finalize_run(run_id, expected_version=None):
    """Finalize a run, capturing the current version if not supplied. Returns run dict."""
    if expected_version is None:
        expected_version = current_run_version(run_id)
    res = api_client.finalize_production_run(run_id, finalize_payload(expected_version), OP)
    return get_success_data(res)


def produce_finished_lot(facility_id, ingredient_id, source_lot_id, quantity,
                         planned_output_qty):
    """Open a run, draw `quantity` from source_lot_id, finalize, return finished lot id.

    Returns (run_dict, output_lot_id).
    """
    run = open_run(facility_id, ingredient_id, planned_output_qty=planned_output_qty)
    add_consumed_lot(run["id"], source_lot_id, quantity)
    finalized = finalize_run(run["id"])
    return finalized, finalized["output_lot_id"]


def setup_two_finished_lots_from_one_source(initial_utc="2026-01-01T00:00:00Z"):
    """One released raw lot R (qty 100), two finished lots F1 (qty 50) and F2 (qty 30),
    each produced by a FINALIZED run consuming R.

    Returns (facility, ingredient, lotR_id, f1_lot_id, f2_lot_id, run2_id).
    """
    facility = create_facility(initial_utc=initial_utc)
    supplier = create_supplier(facility["id"], coa_required=False)
    ingredient = create_ingredient(facility["id"], shelf_life_days=10,
                                   declared_allergen_codes=["WHEAT"])
    lotR = receive_lot(facility["id"], ingredient["id"], "R",
                       supplier_id=supplier["id"], received_qty=100)
    release_lot(lotR["id"])
    _, f1_lot = produce_finished_lot(facility["id"], ingredient["id"], lotR["id"],
                                     quantity=30, planned_output_qty=50)
    run2, f2_lot = produce_finished_lot(facility["id"], ingredient["id"], lotR["id"],
                                        quantity=20, planned_output_qty=30)
    return facility, ingredient, lotR["id"], f1_lot, f2_lot, run2["id"]


def setup_three_hop_genealogy(initial_utc="2026-01-01T00:00:00Z"):
    """Released raw lot R (100). Finished F1 consumes R; finished F2 consumes F1.
    Both runs FINALIZED.

    Each tier uses its own recipe ingredient (raw R, mid F1, top F2) so that no
    finalize ever bypasses an earlier-expiring SAME-ingredient released-free lot —
    keeping the chain off the FEFO rotation gate (PRD 3.4) while preserving the
    R -> F1 -> F2 genealogy. R stays RELEASED/FREE (non-terminal) throughout.

    Returns (facility, raw_ingredient, lotR_id, f1_lot_id, f2_lot_id).
    """
    facility = create_facility(initial_utc=initial_utc)
    supplier = create_supplier(facility["id"], coa_required=False)
    ing_raw = create_ingredient(facility["id"], name="Raw", shelf_life_days=365,
                                storage_target_c=20, storage_tolerance_c=5,
                                declared_allergen_codes=[])
    ing_mid = create_ingredient(facility["id"], name="Mid", shelf_life_days=365,
                                storage_target_c=20, storage_tolerance_c=5,
                                declared_allergen_codes=[])
    ing_top = create_ingredient(facility["id"], name="Top", shelf_life_days=365,
                                storage_target_c=20, storage_tolerance_c=5,
                                declared_allergen_codes=[])
    lotR = receive_lot(facility["id"], ing_raw["id"], "R",
                       supplier_id=supplier["id"], received_qty=100)
    release_lot(lotR["id"])
    _, f1_lot = produce_finished_lot(facility["id"], ing_mid["id"], lotR["id"],
                                     quantity=50, planned_output_qty=50)
    release_lot(f1_lot)
    _, f2_lot = produce_finished_lot(facility["id"], ing_top["id"], f1_lot,
                                     quantity=20, planned_output_qty=20)
    return facility, ing_raw, lotR["id"], f1_lot, f2_lot


# ─── Tier 5: Hold orders ───────────────────────────────────────────────────

def issue_hold(facility_id, target_lot_id, reason="OTHER"):
    res = api_client.create_hold_order(
        create_hold_order_payload(facility_id, target_lot_id, reason), QM)
    return get_success_data(res)


def resolve_hold(hold_id, disposition, expected_version):
    res = api_client.resolve_hold_order(
        hold_id, resolve_hold_payload(disposition, expected_version), QM)
    return get_success_data(res)


def setup_released_lot_under_hold(reason="OTHER", initial_utc="2026-01-01T00:00:00Z",
                                  received_qty=100, lot_overrides=None):
    """Facility + supplier + ingredient + released raw lot + one ACTIVE hold on it.

    Returns (facility, ingredient, lot_id, hold_dict).
    """
    facility, supplier, ingredient = setup_facility_supplier_ingredient(
        initial_utc=initial_utc, coa_required=False,
        ingredient_overrides={"shelf_life_days": 30, "storage_target_c": 20,
                              "storage_tolerance_c": 5})
    overrides = dict(lot_overrides or {})
    overrides.setdefault("received_qty", received_qty)
    lot = receive_lot(facility["id"], ingredient["id"], "L",
                      supplier_id=supplier["id"], **overrides)
    release_lot(lot["id"])
    hold = issue_hold(facility["id"], lot["id"], reason=reason)
    return facility, ingredient, lot["id"], hold


# ─── Tier 6: Storage zones ─────────────────────────────────────────────────

def create_zone(facility_id, zone_code, capacity_units, **overrides):
    res = api_client.create_zone(
        create_zone_payload(facility_id, zone_code, capacity_units, **overrides), QM)
    return get_success_data(res)


def create_booking(zone_id, lot_id, start_utc, end_utc, capacity_units):
    res = api_client.create_booking(
        zone_id, create_booking_payload(lot_id, start_utc, end_utc, capacity_units), QM)
    return get_success_data(res)


def setup_zone_with_lots(capacity_units=100, num_lots=2, initial_utc="2026-01-01T00:00:00Z"):
    """Facility + zone (capacity_units) + N raw lots (not released).

    Returns (facility, zone_id, [lot_ids]).
    """
    facility = create_facility(initial_utc=initial_utc)
    supplier = create_supplier(facility["id"], coa_required=False)
    ingredient = create_ingredient(facility["id"], storage_target_c=2,
                                   storage_tolerance_c=2, shelf_life_days=30)
    zone = create_zone(facility["id"], "Z1", capacity_units, target_temp_c=2)
    lots = []
    for i in range(num_lots):
        lot = receive_lot(facility["id"], ingredient["id"], f"LZ{i}",
                          supplier_id=supplier["id"], received_qty=5)
        lots.append(lot["id"])
    return facility, zone["id"], lots


# ─── Tier 7: CCP readings ───────────────────────────────────────────────────

def post_reading(lot_id, measured_value_c, measured_at):
    from .factories import create_ccp_reading_payload
    res = api_client.create_ccp_reading(
        create_ccp_reading_payload(lot_id, measured_value_c, measured_at), OP)
    return get_success_data(res)


def setup_released_lot_for_readings(target_c=4, tolerance_c=2, clock_utc="2026-01-02T05:00:00Z",
                                    shelf_life_days=30, declared_allergen_codes=None):
    """Facility (clock advanced) + supplier + ingredient + one RELEASED raw lot, ready
    for CCP readings.

    Returns (facility, ingredient, lot_id).
    """
    facility = create_facility(initial_utc="2026-01-01T00:00:00Z")
    advance_clock(facility["id"], clock_utc)
    supplier = create_supplier(facility["id"], coa_required=False)
    ingredient = create_ingredient(
        facility["id"], storage_target_c=target_c, storage_tolerance_c=tolerance_c,
        shelf_life_days=shelf_life_days,
        declared_allergen_codes=declared_allergen_codes or [])
    lot = receive_lot(facility["id"], ingredient["id"], "L",
                      supplier_id=supplier["id"], received_qty=10)
    release_lot(lot["id"])
    return facility, ingredient, lot["id"]
