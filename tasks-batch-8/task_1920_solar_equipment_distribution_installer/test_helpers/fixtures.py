"""Composite setup helpers.

The harness restarts the API server before every test, so each helper builds
its preconditions from scratch using only PRD-declared endpoints. Setup calls
use the lenient get_success_data validator; a failed precondition raises a
clear "Setup failed" assertion naming the step.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_allocation_payload,
    create_compatibility_rule_payload,
    create_container_line_payload,
    create_container_payload,
    create_installer_payload,
    create_inverter_payload,
    create_product_payload,
    create_project_payload,
    create_rma_claim_payload,
    create_tariff_rate_payload,
)
from .test_users import TEST_USERS, make_installer_rep_headers

ADMIN = TEST_USERS["admin_headers"]
MANAGER = TEST_USERS["manager_headers"]
OFFICER = TEST_USERS["officer_headers"]


def _ok(resp, step: str):
    assert resp.status_code < 300, (
        f"Setup failed at {step}: {resp.status_code} {resp.text}"
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 0: clock + catalog primitives
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = TEST_DEFAULTS["DEFAULT_CLOCK"]):
    return _ok(api_client.set_current_utc(to_iso8601, ADMIN), "set clock")


def create_tariff(hts_code: str, duty_rate_bp: int,
                  effective_from: str = TEST_DEFAULTS["TARIFF_EFFECTIVE_FROM"],
                  effective_to=None):
    payload = create_tariff_rate_payload(
        hts_code=hts_code, duty_rate_bp=duty_rate_bp,
        effective_from=effective_from,
    )
    if effective_to is not None:
        payload["effective_to"] = effective_to
    return _ok(api_client.create_tariff_rate(payload, ADMIN),
               f"create tariff {hts_code}")


def create_module_product(**overrides):
    return _ok(api_client.create_product(create_product_payload(**overrides), ADMIN),
               "create module product")


def create_inverter_product(**overrides):
    return _ok(api_client.create_product(create_inverter_payload(**overrides), ADMIN),
               "create inverter product")


def create_compatibility_rule(module_product_id, inverter_product_id,
                              min_modules=TEST_DEFAULTS["RULE_MIN_MODULES"],
                              max_modules=TEST_DEFAULTS["RULE_MAX_MODULES"],
                              effective_from=TEST_DEFAULTS["TARIFF_EFFECTIVE_FROM"],
                              effective_to=None):
    payload = create_compatibility_rule_payload(
        module_product_id, inverter_product_id,
        min_modules_per_inverter=min_modules,
        max_modules_per_inverter=max_modules,
        effective_from=effective_from,
    )
    if effective_to is not None:
        payload["effective_to"] = effective_to
    return _ok(api_client.create_compatibility_rule(payload, ADMIN),
               "create compatibility rule")


def seed_catalog(min_modules=TEST_DEFAULTS["RULE_MIN_MODULES"],
                 max_modules=TEST_DEFAULTS["RULE_MAX_MODULES"],
                 module_overrides=None, inverter_overrides=None,
                 rule_effective_from=TEST_DEFAULTS["TARIFF_EFFECTIVE_FROM"],
                 rule_effective_to=None):
    """Tariff rates (module 10% / inverter 5% effective 2026-07-01) + one
    MODULE and one INVERTER product + one ACTIVE compatibility rule."""
    module_overrides = module_overrides or {}
    inverter_overrides = inverter_overrides or {}
    mod_tariff = create_tariff(TEST_DEFAULTS["HTS_MODULE"],
                               TEST_DEFAULTS["MODULE_DUTY_RATE_BP"])
    inv_tariff = create_tariff(TEST_DEFAULTS["HTS_INVERTER"],
                               TEST_DEFAULTS["INVERTER_DUTY_RATE_BP"])
    module = create_module_product(**module_overrides)
    inverter = create_inverter_product(**inverter_overrides)
    rule = create_compatibility_rule(
        module["id"], inverter["id"],
        min_modules=min_modules, max_modules=max_modules,
        effective_from=rule_effective_from, effective_to=rule_effective_to,
    )
    return {
        "module_tariff": mod_tariff, "inverter_tariff": inv_tariff,
        "module": module, "inverter": inverter, "rule": rule,
    }


# ---------------------------------------------------------------------------
# Tier 1: installer + project state progression
# ---------------------------------------------------------------------------

def create_active_installer(**overrides):
    installer = _ok(
        api_client.create_installer(create_installer_payload(**overrides), MANAGER),
        "create installer",
    )
    activated = _ok(api_client.activate_installer(installer["id"], MANAGER),
                    "activate installer")
    return activated


def create_project(installer_id, module_product_id, inverter_product_id,
                   module_qty=5, inverter_qty=1, as_manager=False, **overrides):
    headers = MANAGER if as_manager else make_installer_rep_headers(installer_id)
    payload = create_project_payload(
        module_product_id, inverter_product_id,
        module_qty=module_qty, inverter_qty=inverter_qty, **overrides,
    )
    return _ok(api_client.create_project(installer_id, payload, headers),
               "create project")


def create_locked_project(installer_id, module_product_id, inverter_product_id,
                          module_qty=5, inverter_qty=1, **overrides):
    project = create_project(installer_id, module_product_id,
                             inverter_product_id, module_qty=module_qty,
                             inverter_qty=inverter_qty, **overrides)
    locked = _ok(
        api_client.lock_design(
            project["id"], make_installer_rep_headers(installer_id)
        ),
        "lock design",
    )
    return locked


# ---------------------------------------------------------------------------
# Tier 2: containers, lines, lots
# ---------------------------------------------------------------------------

def book_container(freight_cost_cents=0, insurance_cost_cents=0, **overrides):
    payload = create_container_payload(
        freight_cost_cents=freight_cost_cents,
        insurance_cost_cents=insurance_cost_cents,
        **overrides,
    )
    return _ok(api_client.create_container(payload, ADMIN), "book container")


def add_container_line(container_id, product_id, qty_booked,
                       declared_unit_value_cents=TEST_DEFAULTS[
                           "MODULE_DECLARED_UNIT_VALUE_CENTS"]):
    payload = create_container_line_payload(
        product_id, qty_booked=qty_booked,
        declared_unit_value_cents=declared_unit_value_cents,
    )
    return _ok(api_client.create_container_line(container_id, payload, ADMIN),
               "add container line")


def receive_container(container_id, line_receipts):
    """depart -> arrive -> receive. line_receipts: [{container_line_id,
    qty_received, qty_damaged}]. Returns the received container."""
    _ok(api_client.depart_container(container_id, ADMIN), "depart container")
    arrived = _ok(api_client.arrive_container(container_id, ADMIN),
                  "arrive container")
    payload = {
        "expected_container_version": arrived["version"],
        "line_receipts": line_receipts,
    }
    return _ok(api_client.receive_container(container_id, payload, ADMIN),
               "receive container")


def get_lot(lot_id):
    return _ok(api_client.get_inventory_lot(lot_id, ADMIN), "get lot")


def receive_single_line_lot(product_id, qty_booked=5,
                            declared_unit_value_cents=TEST_DEFAULTS[
                                "MODULE_DECLARED_UNIT_VALUE_CENTS"],
                            freight_cost_cents=0, insurance_cost_cents=0,
                            qty_received=None, qty_damaged=0):
    """Book a one-line container, run it through receipt, return
    (container, line, lot) with the lot ON_HAND."""
    if qty_received is None:
        qty_received = qty_booked - qty_damaged
    container = book_container(freight_cost_cents=freight_cost_cents,
                               insurance_cost_cents=insurance_cost_cents)
    line = add_container_line(container["id"], product_id, qty_booked,
                              declared_unit_value_cents)
    container = receive_container(
        container["id"],
        [{"container_line_id": line["id"], "qty_received": qty_received,
          "qty_damaged": qty_damaged}],
    )
    lot = get_lot(line["inventory_lot_id"])
    return container, line, lot


# ---------------------------------------------------------------------------
# Tier 3: project + inventory scenario
# ---------------------------------------------------------------------------

def setup_project_with_on_hand_lot(module_qty=5, lot_qty=5,
                                   declared_unit_value_cents=TEST_DEFAULTS[
                                       "MODULE_DECLARED_UNIT_VALUE_CENTS"],
                                   progress_payment_pct_bp=TEST_DEFAULTS[
                                       "INSTALLER_PROGRESS_PCT_BP"],
                                   credit_limit_cents=TEST_DEFAULTS[
                                       "INSTALLER_CREDIT_LIMIT_CENTS"],
                                   freight_cost_cents=0,
                                   insurance_cost_cents=0,
                                   rule_min=TEST_DEFAULTS["RULE_MIN_MODULES"],
                                   rule_max=TEST_DEFAULTS["RULE_MAX_MODULES"],
                                   start_clock=TEST_DEFAULTS["DEFAULT_CLOCK"]):
    """Catalog + ACTIVE installer + design-locked project + one ON_HAND lot.

    With the default 10% module tariff, zero freight/insurance and a declared
    value of 50000c, each received module carries a final landed cost of
    55000c (base 50000 + duty 5000).
    """
    set_clock(start_clock)
    catalog = seed_catalog(min_modules=rule_min, max_modules=rule_max)
    installer = create_active_installer(
        credit_limit_cents=credit_limit_cents,
        progress_payment_pct_bp=progress_payment_pct_bp,
    )
    project = create_locked_project(
        installer["id"], catalog["module"]["id"], catalog["inverter"]["id"],
        module_qty=module_qty,
    )
    container, line, lot = receive_single_line_lot(
        catalog["module"]["id"], qty_booked=lot_qty,
        declared_unit_value_cents=declared_unit_value_cents,
        freight_cost_cents=freight_cost_cents,
        insurance_cost_cents=insurance_cost_cents,
    )
    return {
        **catalog,
        "installer": installer,
        "project": project,
        "container": container,
        "line": line,
        "lot": lot,
    }


def allocate_current_version(project_id, installer_id, lot_id, qty,
                             as_manager=False):
    """Read the lot's current version, then place the allocation with that
    OCC guard value. Returns the created Allocation."""
    lot = get_lot(lot_id)
    headers = MANAGER if as_manager else make_installer_rep_headers(installer_id)
    payload = create_allocation_payload(lot_id, qty, lot["version"])
    return _ok(api_client.create_allocation(project_id, payload, headers),
               "create allocation")


def ship_allocation(allocation_id):
    return _ok(api_client.ship_allocation(allocation_id, ADMIN),
               "ship allocation")


def setup_shipped_project(**overrides):
    """Project + ON_HAND lot + allocate all modules + ship -> SHIPPED with a
    PROGRESS invoice issued. Returns the scenario context plus the allocation
    and the progress invoice."""
    ctx = setup_project_with_on_hand_lot(**overrides)
    inst_id = ctx["installer"]["id"]
    proj_id = ctx["project"]["id"]
    qty = overrides.get("module_qty", 5)
    allocation = allocate_current_version(proj_id, inst_id,
                                          ctx["lot"]["id"], qty)
    allocation = ship_allocation(allocation["id"])
    invoices = _ok(
        api_client.list_project_invoices(proj_id, MANAGER,
                                         params={"invoice_kind": "PROGRESS"}),
        "list progress invoices",
    )
    assert len(invoices) == 1, (
        f"Setup failed: expected exactly one PROGRESS invoice, got {invoices}"
    )
    ctx["allocation"] = allocation
    ctx["progress_invoice"] = invoices[0]
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: permit + PTO lifecycle
# ---------------------------------------------------------------------------

def approve_permit_for_project(project_id, installer_id):
    """Find the auto-created permit package, upload every required document
    slug the package itself lists, submit, and approve. Returns the APPROVED
    package."""
    rep = make_installer_rep_headers(installer_id)
    packages = _ok(
        api_client.list_project_permit_packages(project_id, MANAGER),
        "list permit packages",
    )
    assert len(packages) == 1, (
        f"Setup failed: expected exactly one permit package, got {packages}"
    )
    package = packages[0]
    for slug in package["required_documents"]:
        _ok(api_client.upload_permit_document(
            package["id"], {"document_slug": slug}, rep,
        ), f"upload permit document {slug}")
    _ok(api_client.submit_permit_package(package["id"], rep),
        "submit permit package")
    return _ok(api_client.approve_permit_package(package["id"], MANAGER),
               "approve permit package")


def setup_pto_billed_project(**overrides):
    """Shipped project + permit APPROVED + PTO invoice issued."""
    ctx = setup_shipped_project(**overrides)
    inst_id = ctx["installer"]["id"]
    proj_id = ctx["project"]["id"]
    ctx["permit_package"] = approve_permit_for_project(proj_id, inst_id)
    ctx["pto_invoice"] = _ok(api_client.invoice_pto(proj_id, MANAGER),
                             "issue PTO invoice")
    return ctx


def setup_paid_in_full_project(**overrides):
    """PTO-billed project with every invoice paid in full ->
    payment_status PAID_IN_FULL while fulfillment stays SHIPPED."""
    ctx = setup_pto_billed_project(**overrides)
    proj_id = ctx["project"]["id"]
    for invoice in _ok(api_client.list_project_invoices(proj_id, MANAGER),
                       "list project invoices"):
        _ok(api_client.post_payment(
            invoice["id"], {"amount_cents": invoice["balance_due_cents"]},
            OFFICER,
        ), f"pay invoice {invoice['id']}")
    ctx["project"] = _ok(api_client.get_project(proj_id, MANAGER),
                         "re-read project")
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: RMA helpers
# ---------------------------------------------------------------------------

def create_submitted_rma(installer_id, product_id, allocation_id, qty_claimed):
    rep = make_installer_rep_headers(installer_id)
    claim = _ok(api_client.create_rma_claim(
        create_rma_claim_payload(installer_id, product_id, allocation_id,
                                 qty_claimed),
        rep,
    ), "create RMA claim")
    return _ok(api_client.submit_rma_claim(claim["id"], rep),
               "submit RMA claim")


def create_approved_rma(installer_id, product_id, allocation_id, qty_claimed,
                        qty_approved=None):
    if qty_approved is None:
        qty_approved = qty_claimed
    claim = create_submitted_rma(installer_id, product_id, allocation_id,
                                 qty_claimed)
    return _ok(api_client.approve_rma_claim(
        claim["id"], {"qty_approved": qty_approved}, MANAGER,
    ), "approve RMA claim")
