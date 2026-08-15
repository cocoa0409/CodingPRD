"""Composite setup helpers for multi-step test prerequisites.

All helpers build state exclusively through PRD-declared endpoints and use
get_success_data() (lenient) so a setup failure surfaces as a clear setup
error rather than a confusing assertion failure.

The mill reads a single logical clock (PRD Section 2.5) that starts at
2026-08-01T00:00:00Z on every freshly launched server; helpers move it
forward explicitly whenever a time-dependent precondition must be met.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated
from .api_client import api_client
from .factories import (
    create_log_load_payload,
    scale_payload,
    dispute_payload,
    package_entry_payload,
    create_sawing_run_payload,
    complete_sawing_run_payload,
    create_kiln_charge_payload,
    kiln_reading_payload,
    create_grade_inspection_payload,
    create_price_list_payload,
    create_sales_contract_payload,
    create_sales_order_payload,
    create_byproduct_sale_payload,
)
from .test_users import (
    make_scaler_headers,
    make_sawyer_headers,
    make_kiln_operator_headers,
    make_grader_headers,
    make_sales_rep_headers,
    make_mill_manager_headers,
)
from .constants import KILN_WINDOW, DEFAULT_TARGET_MOISTURE_PCT


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the mill logical clock (MillManager)."""
    res = api_client.set_clock({"to_iso8601": to_iso8601}, make_mill_manager_headers())
    return get_success_data(res)


def create_log_load(**overrides):
    """Receive a log load as Scaler; returns the LogLoad at RECEIVED."""
    res = api_client.create_log_load(create_log_load_payload(**overrides), make_scaler_headers())
    return get_success_data(res)


def scale_load(load_id, scaled_mbf=100, price_per_mbf_cents=25000):
    """Scale a RECEIVED load as Scaler; returns the LogLoad at SCALED."""
    res = api_client.scale_log_load(
        load_id,
        scale_payload(scaled_mbf=scaled_mbf, price_per_mbf_cents=price_per_mbf_cents),
        make_scaler_headers(),
    )
    return get_success_data(res)


def dispute_load(load_id, reason="supplier contests Scribner short"):
    """Dispute a SCALED load as Scaler; returns the LogLoad at DISPUTED."""
    res = api_client.dispute_log_load(load_id, dispute_payload(reason=reason), make_scaler_headers())
    return get_success_data(res)


def deck_load(load_id):
    """Deck a SCALED load as Scaler; returns the LogLoad at DECKED."""
    res = api_client.deck_log_load(load_id, make_scaler_headers())
    return get_success_data(res)


def create_decked_load(scaled_mbf=100, price_per_mbf_cents=25000, **overrides):
    """Full receive -> scale -> deck chain; returns the LogLoad at DECKED."""
    load = create_log_load(**overrides)
    scale_load(load["id"], scaled_mbf=scaled_mbf, price_per_mbf_cents=price_per_mbf_cents)
    return deck_load(load["id"])


def publish_price_list(**overrides):
    """Publish a spot price row as MillManager; returns the PriceList row."""
    res = api_client.create_price_list(create_price_list_payload(**overrides), make_mill_manager_headers())
    return get_success_data(res)


def create_contract(**overrides):
    """Create a sales contract as MillManager; returns the contract at DRAFT."""
    res = api_client.create_sales_contract(create_sales_contract_payload(**overrides), make_mill_manager_headers())
    return get_success_data(res)


def create_active_contract(**overrides):
    """Create + activate a sales contract; returns the contract at ACTIVE."""
    contract = create_contract(**overrides)
    res = api_client.activate_sales_contract(contract["id"], make_mill_manager_headers())
    return get_success_data(res)


def place_order(**overrides):
    """Place a sales order as SalesRep; returns the order at PLACED."""
    res = api_client.create_sales_order(create_sales_order_payload(**overrides), make_sales_rep_headers())
    return get_success_data(res)


def sell_byproduct(**overrides):
    """Record a byproduct sale as SalesRep; returns the ByproductSale row."""
    res = api_client.create_byproduct_sale(create_byproduct_sale_payload(**overrides), make_sales_rep_headers())
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 2: saw floor — runs and packages
# ---------------------------------------------------------------------------

def create_planned_run(load_ids, **overrides):
    """Plan a sawing run over DECKED loads as Sawyer; returns the PLANNED run."""
    res = api_client.create_sawing_run(
        create_sawing_run_payload(load_ids, **overrides), make_sawyer_headers()
    )
    return get_success_data(res)


def list_run_packages(run_id):
    """List the LumberPackages produced by a run (filter sawing_run_id)."""
    res = api_client.list_lumber_packages(make_sawyer_headers(), params={"sawing_run_id": run_id})
    data, _meta = validate_paginated(res)
    return data


def create_completed_run(package_specs, scaled_mbf=100, price_per_mbf_cents=25000,
                         load_overrides=None, run_overrides=None, complete_overrides=None):
    """Full chain: one decked load -> planned run -> completed run.

    package_specs: list of package entry dicts (species/dimension/length_ft/
    pieces/green_mbf). Returns (run, packages) with packages re-read from the
    list endpoint in created order.
    """
    load_overrides = load_overrides or {}
    run_overrides = run_overrides or {}
    complete_overrides = complete_overrides or {}
    species = package_specs[0].get("species", "DOUGLAS_FIR") if package_specs else "DOUGLAS_FIR"
    load_overrides.setdefault("species", species)
    load = create_decked_load(scaled_mbf=scaled_mbf, price_per_mbf_cents=price_per_mbf_cents,
                              **load_overrides)
    run = create_planned_run([load["id"]], **run_overrides)
    entries = [package_entry_payload(**spec) for spec in package_specs]
    run = get_success_data(api_client.complete_sawing_run(
        run["id"], complete_sawing_run_payload(entries, **complete_overrides), make_sawyer_headers()
    ))
    return run, list_run_packages(run["id"])


# ---------------------------------------------------------------------------
# Tier 3: kiln lifecycle
# ---------------------------------------------------------------------------

def create_kiln_charge(package_ids, **overrides):
    """Schedule a kiln charge as KilnOperator; returns the SCHEDULED charge.

    Charged packages flip GREEN -> IN_KILN as part of creation.
    """
    res = api_client.create_kiln_charge(
        create_kiln_charge_payload(package_ids, **overrides), make_kiln_operator_headers()
    )
    return get_success_data(res)


def start_charge(charge_id, scheduled_start=None):
    """Move the clock to the charge window (if given) and start the charge."""
    if scheduled_start is not None:
        set_clock(scheduled_start)
    res = api_client.start_kiln_charge(charge_id, make_kiln_operator_headers())
    return get_success_data(res)


def complete_charge(charge_id, readings, scheduled_end=None):
    """Move the clock to the charge end (if given) and complete the charge.

    readings: list of dicts {package_id, exit_moisture_pct, measured_dry_mbf}.
    """
    if scheduled_end is not None:
        set_clock(scheduled_end)
    payload = {"readings": [kiln_reading_payload(**r) for r in readings]}
    res = api_client.complete_kiln_charge(charge_id, payload, make_kiln_operator_headers())
    return get_success_data(res)


def run_kiln_cycle(charge_id, readings, scheduled_start=KILN_WINDOW["START"],
                   scheduled_end=KILN_WINDOW["END"]):
    """Start then complete a charge, driving the clock through its window."""
    start_charge(charge_id, scheduled_start=scheduled_start)
    return complete_charge(charge_id, readings, scheduled_end=scheduled_end)


def stamp_package(package_id, inspector_grade="NO_2", action="STAMP", **overrides):
    """Record a grade inspection as Grader; returns the GradeInspection row."""
    res = api_client.create_grade_inspection(
        package_id,
        create_grade_inspection_payload(inspector_grade=inspector_grade, action=action, **overrides),
        make_grader_headers(),
    )
    return get_success_data(res)


def get_package(package_id):
    res = api_client.get_lumber_package(package_id, make_kiln_operator_headers())
    return get_success_data(res)


def get_run(run_id):
    res = api_client.get_sawing_run(run_id, make_sawyer_headers())
    return get_success_data(res)


def get_order(order_id):
    res = api_client.get_sales_order(order_id, make_sales_rep_headers())
    return get_success_data(res)


def get_contract(contract_id):
    res = api_client.get_sales_contract(contract_id, make_mill_manager_headers())
    return get_success_data(res)


def get_load(load_id):
    res = api_client.get_log_load(load_id, make_scaler_headers())
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 4: full pipeline shortcuts (package produced, dried, stamped)
# ---------------------------------------------------------------------------

def produce_dry_packages(package_specs, measured, scaled_mbf=100,
                         price_per_mbf_cents=25000, chamber="KILN_1",
                         target_moisture_pct=DEFAULT_TARGET_MOISTURE_PCT,
                         exit_moisture_pct=14.0,
                         load_overrides=None, run_overrides=None):
    """Produce packages via a completed run and dry them through one charge.

    package_specs: list of package entry dicts.
    measured: list of measured_dry_mbf values, parallel to package_specs.
    Returns (run, packages) with all packages DRY and actual_dry_mbf recorded.
    """
    run, packages = create_completed_run(
        package_specs, scaled_mbf=scaled_mbf, price_per_mbf_cents=price_per_mbf_cents,
        load_overrides=load_overrides, run_overrides=run_overrides,
    )
    charge = create_kiln_charge(
        [p["id"] for p in packages],
        chamber=chamber,
        species=package_specs[0].get("species", "DOUGLAS_FIR"),
        target_moisture_pct=target_moisture_pct,
    )
    readings = [
        {"package_id": p["id"], "exit_moisture_pct": exit_moisture_pct,
         "measured_dry_mbf": m}
        for p, m in zip(packages, measured)
    ]
    run_kiln_cycle(charge["id"], readings)
    return run, [get_package(p["id"]) for p in packages]


def produce_stamped_packages(package_specs, measured, grade="NO_2", **kwargs):
    """produce_dry_packages + STAMP each package. Returns (run, packages)."""
    grades = grade if isinstance(grade, list) else [grade] * len(package_specs)
    run, packages = produce_dry_packages(package_specs, measured, **kwargs)
    stamped = []
    for p, g in zip(packages, grades):
        stamp_package(p["id"], inspector_grade=g, action="STAMP")
        stamped.append(get_package(p["id"]))
    return run, stamped


def setup_order_with_allocation(package_specs, measured, order_overrides,
                                grade="NO_2", price_list=True, contract=None, **kwargs):
    """Stamped packages + one PLACED order + allocation.

    Returns (order_after_allocate, packages, run).
    """
    if price_list and contract is None:
        publish_price_list()
    run, packages = produce_stamped_packages(package_specs, measured, grade=grade, **kwargs)
    if contract is not None:
        order_overrides = dict(order_overrides)
        order_overrides["contract_id"] = contract["id"]
    order = place_order(**order_overrides)
    order = get_success_data(api_client.allocate_sales_order(order["id"], make_sales_rep_headers()))
    return order, packages, run


# ---------------------------------------------------------------------------
# Tier 5: ops checkpoint
# ---------------------------------------------------------------------------

def run_ops_checkpoint():
    """Invoke the ops checkpoint as MillManager; returns its response data."""
    res = api_client.create_ops_run(make_mill_manager_headers())
    return get_success_data(res)


def byproduct_inventory_map():
    """GET /api/byproduct-inventory keyed by product name."""
    res = api_client.get_byproduct_inventory(make_sales_rep_headers())
    data = get_success_data(res)
    items = data["items"] if isinstance(data, dict) else data
    return {item["product"]: item for item in items}
