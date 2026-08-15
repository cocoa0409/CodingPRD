"""Composite setup helpers for the forging-plant pipeline.

Each helper builds preconditions from scratch using only PRD-declared
endpoints (the server starts empty before every test). Setup steps validate
with the lenient get_success_data() so failures surface as clear setup errors.
"""
from datetime import datetime, timedelta

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from . import factories
from .api_client import api_client
from .constants import DEFAULT_CHARGE_TEMP_F, DEFAULT_SOAK_MINUTES
from .test_users import TEST_USERS

PM = TEST_USERS["plant_manager_headers"]
SAW = TEST_USERS["saw_operator_headers"]
FURN = TEST_USERS["furnace_operator_headers"]
FORGE = TEST_USERS["forge_operator_headers"]
DIE = TEST_USERS["die_tech_headers"]
QE = TEST_USERS["quality_engineer_headers"]
QE2 = TEST_USERS["quality_engineer_2_headers"]
SP = TEST_USERS["sales_planner_headers"]

# Canonical windows: furnace charges on 2026-08-02, forge runs on 2026-08-03.
DEFAULT_CHARGE_START = "2026-08-02T08:00:00Z"
DEFAULT_CHARGE_END = "2026-08-02T12:00:00Z"
DEFAULT_RUN_START = "2026-08-03T09:00:00Z"
DEFAULT_RUN_END = "2026-08-03T10:30:00Z"


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _to_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

def set_logical_clock(to_iso8601: str) -> dict:
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, PM))


# ---------------------------------------------------------------------------
# Catalog entities
# ---------------------------------------------------------------------------

def new_alloy(**overrides) -> dict:
    return get_success_data(api_client.create_alloy_spec(
        factories.alloy_spec_payload(**overrides), PM))


def new_surcharge_index(alloy_spec_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_surcharge_index(
        factories.surcharge_index_payload(alloy_spec_id, **overrides), PM))


def new_furnace(furnace_code: str = "FUR-1", capacity_lbs: float = 5000) -> dict:
    return get_success_data(api_client.create_furnace(
        factories.furnace_payload(furnace_code, capacity_lbs), PM))


def new_work_center(code: str = "WC-1", type: str = "PRESS",
                    rated_tonnage: int = 500) -> dict:
    return get_success_data(api_client.create_work_center(
        factories.work_center_payload(code, type, rated_tonnage), PM))


def new_die_set(die_set_code: str = "DIE-1", wear_limit_hits: int = 300,
                max_resinks: int = 2, part_family: str = "FLG-4") -> dict:
    return get_success_data(api_client.create_die_set(
        factories.die_set_payload(die_set_code, part_family,
                                  wear_limit_hits, max_resinks), DIE))


def install_die(die_id: str, work_center_id: str) -> dict:
    return get_success_data(api_client.install_die_set(
        die_id, {"work_center_id": work_center_id}, DIE))


# ---------------------------------------------------------------------------
# Heat intake and cutting
# ---------------------------------------------------------------------------

def new_heat(alloy_spec_id: str, heat_number: str = "H-1001", **overrides) -> dict:
    """Register a heat lot (lands in RECEIVED)."""
    return get_success_data(api_client.create_mill_heat(
        factories.mill_heat_payload(alloy_spec_id, heat_number, **overrides), PM))


def verify_heat(heat_id: str, carbon_pct: float = 0.40,
                manganese_pct: float = 0.90) -> dict:
    return get_success_data(api_client.verify_heat_cert(
        heat_id, factories.verify_cert_payload(carbon_pct, manganese_pct), QE))


def new_certified_heat(alloy_spec_id: str, heat_number: str = "H-1001",
                       **overrides) -> dict:
    heat = new_heat(alloy_spec_id, heat_number, **overrides)
    return verify_heat(heat["id"])


def cut_billets(heat_id: str, cut_length_in: float = 20.0, quantity: int = 1) -> list:
    """One cut line of `quantity` pieces. Returns the created billets in order."""
    return get_success_data(api_client.cut_billets(
        heat_id, factories.cut_lines_payload(cut_length_in, quantity), SAW))


def cut_billet_lines(heat_id: str, cuts: list) -> list:
    """Multiple cut lines, e.g. [(20.0, 2), (10.5, 1)]. Returns all billets."""
    payload = {"cuts": [{"cut_length_in": length, "quantity": qty}
                        for length, qty in cuts]}
    return get_success_data(api_client.cut_billets(heat_id, payload, SAW))


# ---------------------------------------------------------------------------
# Furnace charges
# ---------------------------------------------------------------------------

def new_charge(furnace_id: str, billet_ids: list, planned_load_start: str,
               planned_unload: str, target_temp_f: int = DEFAULT_CHARGE_TEMP_F,
               soak_minutes: int = DEFAULT_SOAK_MINUTES) -> dict:
    """Create a charge (LOADING) at the current logical clock."""
    return get_success_data(api_client.create_furnace_charge(
        factories.furnace_charge_payload(
            furnace_id, billet_ids, planned_load_start, planned_unload,
            target_temp_f, soak_minutes), FURN))


def new_ready_charges(furnace_id: str, specs: list,
                      target_temp_f: int = DEFAULT_CHARGE_TEMP_F,
                      soak_minutes: int = DEFAULT_SOAK_MINUTES) -> list:
    """Create several charges on one furnace and walk them all to READY.

    specs: list of (billet_ids, planned_load_start, planned_unload) tuples.
    The clock is set to the earliest load start, all charges are created and
    closed, the clock advances past the soak window, and each is marked READY.
    """
    earliest = min(_parse_iso(start) for _, start, _ in specs)
    set_logical_clock(_to_iso(earliest))
    charges = []
    for billet_ids, start, unload in specs:
        charges.append(new_charge(furnace_id, billet_ids, start, unload,
                                  target_temp_f, soak_minutes))
    for charge in charges:
        get_success_data(api_client.close_charge_loading(charge["id"], FURN))
    set_logical_clock(_to_iso(earliest + timedelta(minutes=soak_minutes)))
    ready = []
    for charge in charges:
        ready.append(get_success_data(api_client.mark_charge_ready(charge["id"], FURN)))
    return ready


def new_ready_charge(furnace_id: str, billet_ids: list,
                     planned_load_start: str = DEFAULT_CHARGE_START,
                     planned_unload: str = DEFAULT_CHARGE_END,
                     target_temp_f: int = DEFAULT_CHARGE_TEMP_F,
                     soak_minutes: int = DEFAULT_SOAK_MINUTES) -> dict:
    """Single charge walked to READY."""
    return new_ready_charges(
        furnace_id, [(billet_ids, planned_load_start, planned_unload)],
        target_temp_f, soak_minutes)[0]


# ---------------------------------------------------------------------------
# Work orders and forge runs
# ---------------------------------------------------------------------------

def new_work_order(alloy_spec_id: str, order_number: str = "WO-1",
                   **overrides) -> dict:
    return get_success_data(api_client.create_work_order(
        factories.work_order_payload(alloy_spec_id, order_number, **overrides), SP))


def get_wo_version(wo_id: str) -> int:
    return get_success_data(api_client.get_work_order(wo_id, SP))["version"]


def new_forge_run(wo_id: str, die_set_id: str, planned_start: str = DEFAULT_RUN_START,
                  planned_end: str = DEFAULT_RUN_END, planned_qty: int = 10,
                  work_center_id=None,
                  expected_work_order_version=None) -> dict:
    """Schedule a run. When the expected version is not given, the order is
    re-read so the OCC precondition holds."""
    if expected_work_order_version is None:
        expected_work_order_version = get_wo_version(wo_id)
    return get_success_data(api_client.create_forge_run(
        factories.forge_run_payload(
            wo_id, die_set_id, planned_start, planned_end, planned_qty,
            expected_work_order_version, work_center_id), FORGE))


def start_run(run_id: str, operator_headers=None) -> dict:
    return get_success_data(api_client.start_forge_run(
        run_id, operator_headers or FORGE))


def record_heat(run_id: str, furnace_charge_id: str, billet_ids: list,
                parts_good: int, parts_scrapped: int = 0,
                operator_headers=None) -> dict:
    return get_success_data(api_client.record_forge_heat(
        run_id,
        factories.forge_heat_payload(furnace_charge_id, billet_ids,
                                     parts_good, parts_scrapped),
        operator_headers or FORGE))


def finish_run(run_id: str, operator_headers=None) -> dict:
    return get_success_data(api_client.finish_forging(
        run_id, operator_headers or FORGE))


# ---------------------------------------------------------------------------
# Trim tickets and parts
# ---------------------------------------------------------------------------

def open_trim_ticket(run_id: str) -> dict:
    return get_success_data(api_client.create_trim_ticket(run_id, FORGE))


def record_trim(ticket_id: str, gross_as_forged_lbs: float, net_trimmed_lbs: float,
                pierce_loss_lbs: float) -> dict:
    return get_success_data(api_client.record_trim_ticket(
        ticket_id,
        factories.trim_record_payload(gross_as_forged_lbs, net_trimmed_lbs,
                                      pierce_loss_lbs),
        FORGE))


def approve_deviation(ticket_id: str,
                      deviation_reason: str = "customer-approved overflash") -> dict:
    return get_success_data(api_client.approve_trim_deviation(
        ticket_id, {"deviation_reason": deviation_reason}, QE))


def order_parts(wo_id: str) -> list:
    data, _meta = validate_paginated(
        api_client.list_work_order_parts(wo_id, SP))
    return data


# ---------------------------------------------------------------------------
# Quality certification
# ---------------------------------------------------------------------------

def first_order_cert(wo_id: str) -> dict:
    data, _meta = validate_paginated(
        api_client.list_work_order_certs(wo_id, QE))
    assert len(data) >= 1, "expected at least one quality cert on the order"
    return data[0]


def submit_cert(cert_id: str, grain_flow_rating: int = 6,
                macro_etch_result: str = "PASS", submitter_headers=None) -> dict:
    return get_success_data(api_client.submit_quality_cert(
        cert_id,
        factories.quality_cert_submit_payload(grain_flow_rating, macro_etch_result),
        submitter_headers or QE))


def certify_cert(cert_id: str, certifier_headers=None) -> dict:
    return get_success_data(api_client.certify_quality_cert(
        cert_id, certifier_headers or QE2))


def certify_order(wo_id: str, grain_flow_rating: int = 6,
                  macro_etch_result: str = "PASS") -> dict:
    """Submit (qe-1) and certify (qe-2) the order's auto-created cert,
    satisfying segregation of duties against run operator op-1."""
    cert = first_order_cert(wo_id)
    submit_cert(cert["id"], grain_flow_rating, macro_etch_result, QE)
    return certify_cert(cert["id"], QE2)


# ---------------------------------------------------------------------------
# Shipping
# ---------------------------------------------------------------------------

def inspect_and_ship_all(wo_id: str) -> list:
    """Inspect every part of the order, then ship them all. Returns the parts
    as listed before shipping."""
    parts = order_parts(wo_id)
    for part in parts:
        get_success_data(api_client.inspect_part_serial(part["id"], QE))
    get_success_data(api_client.ship_work_order(
        wo_id, {"part_serial_ids": [p["id"] for p in parts]}, SP))
    return parts


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

def new_invoice(wo_id: str) -> dict:
    """Create the provisional invoice, re-reading the order version for OCC."""
    version = get_wo_version(wo_id)
    return get_success_data(api_client.create_invoice(
        wo_id, factories.invoice_payload(version), SP))


# ---------------------------------------------------------------------------
# Composite production pipelines
# ---------------------------------------------------------------------------

def setup_production_ctx(
    qty: int = 2,
    cut_length_in: float = 20.0,
    received_weight_lbs: float = 20000.00,
    die_wear_limit: int = 300,
    die_max_resinks: int = 2,
    wc_tonnage: int = 500,
    order_overrides: dict = None,
    trim_gross: float = 100.00,
    trim_net: float = 86.00,
    trim_pierce: float = 2.00,
    record_trim_ticket: bool = True,
    heat_number: str = "H-1001",
    die_code: str = "DIE-1",
    wc_code: str = "WC-1",
    order_number: str = "WO-1",
    furnace_code: str = "FUR-1",
) -> dict:
    """Full shop-floor line through run FORGED with `qty` parts (one charge,
    one heat, all good), optionally with the trim ticket recorded.

    Returns a ctx dict: alloy, heat, billets, furnace, charge, die, wc, wo,
    run, forge_heat, and (when record_trim_ticket) ticket + parts.
    """
    alloy = new_alloy()
    heat = new_certified_heat(alloy["id"], heat_number,
                              received_weight_lbs=received_weight_lbs)
    billets = cut_billets(heat["id"], cut_length_in, qty)
    furnace = new_furnace(furnace_code)
    charge = new_ready_charge(furnace["id"], [b["id"] for b in billets])
    die = new_die_set(die_code, die_wear_limit, die_max_resinks)
    wc = new_work_center(wc_code, "PRESS", wc_tonnage)
    install_die(die["id"], wc["id"])
    wo = new_work_order(alloy["id"], order_number, ordered_qty=qty,
                        **(order_overrides or {}))
    run = new_forge_run(wo["id"], die["id"], planned_qty=qty,
                        work_center_id=wc["id"])
    run = start_run(run["id"])
    forge_heat = record_heat(run["id"], charge["id"],
                             [b["id"] for b in billets], parts_good=qty)
    run = finish_run(run["id"])
    ctx = {
        "alloy": alloy, "heat": heat, "billets": billets, "furnace": furnace,
        "charge": charge, "die": die, "wc": wc, "wo": wo, "run": run,
        "forge_heat": forge_heat,
    }
    if record_trim_ticket:
        ticket = open_trim_ticket(run["id"])
        ctx["ticket"] = record_trim(ticket["id"], trim_gross, trim_net, trim_pierce)
        ctx["parts"] = order_parts(wo["id"])
    return ctx


def setup_certified_ctx(**kwargs) -> dict:
    """Production through PRODUCED, then cert submitted + certified (order
    CERTIFIED)."""
    ctx = setup_production_ctx(**kwargs)
    ctx["cert"] = certify_order(ctx["wo"]["id"])
    return ctx


def setup_shipped_ctx(**kwargs) -> dict:
    """Certified order with every part inspected and shipped."""
    ctx = setup_certified_ctx(**kwargs)
    ctx["shipped_parts"] = inspect_and_ship_all(ctx["wo"]["id"])
    return ctx
