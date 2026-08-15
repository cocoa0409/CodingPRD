"""Composite setup helpers (PRD §3 lifecycle walks).

Every fixture builds preconditions from scratch using only PRD-declared
endpoints (the harness restarts the server before every test, so each test
starts against an empty database). Setup calls use get_success_data so a
broken precondition fails with a clear "Setup failed" message.

Conventions:
- Programs default to the 1%/month composite AFUDC parameters and HALF_MONTH /
  NET_OF_CIAC methods (see factories.create_capital_program_payload).
- The seed estimate is always fetched fresh via the estimates list filter
  (PRD §3.4: estimates may be listed filtered by work_order_id).
- expected_work_order_version is always read live (PRD §2.7 OCC), never
  hard-coded.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_accounting_period_payload,
    create_capital_program_payload,
    create_ciac_agreement_payload,
    create_cost_charge_payload,
    create_estimate_payload,
    create_overhead_schedule_payload,
    create_regulatory_asset_payload,
    create_unit_catalog_payload,
    create_work_order_payload,
    make_unitization_line,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
ENGINEER = TEST_USERS["engineer_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
CONTROLLER = TEST_USERS["controller_headers"]
CLERK = TEST_USERS["clerk_headers"]
RATES = TEST_USERS["rates_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ---------------------------------------------------------------------------
# Tier 0: single-resource creation shortcuts
# ---------------------------------------------------------------------------

def create_program(admin_headers=ADMIN, **overrides):
    """Create an OPEN capital program (PRD §3.1). Returns the program."""
    return get_success_data(api_client.create_capital_program(
        create_capital_program_payload(**overrides), admin_headers))


def create_catalog_entry(admin_headers=ADMIN, **overrides):
    """Create a unit catalog row (PRD §3.1)."""
    return get_success_data(api_client.create_unit_catalog_entry(
        create_unit_catalog_payload(**overrides), admin_headers))


def create_schedule(admin_headers=ADMIN, **overrides):
    """Create an overhead schedule row (PRD §3.1)."""
    return get_success_data(api_client.create_overhead_schedule(
        create_overhead_schedule_payload(**overrides), admin_headers))


def create_period(admin_headers=ADMIN, **overrides):
    """Create an accounting period (PRD §3.2); defaults to 2026-08."""
    return get_success_data(api_client.create_accounting_period(
        create_accounting_period_payload(**overrides), admin_headers))


def close_period(period_id, controller_headers=CONTROLLER):
    """Close an OPEN/REOPENED period (PRD §3.9). Returns the period."""
    return get_success_data(
        api_client.close_accounting_period(period_id, controller_headers))


def reopen_period(period_id, controller_headers=CONTROLLER):
    """Reopen the latest CLOSED period (PRD §3.9). Returns the period."""
    return get_success_data(
        api_client.reopen_accounting_period(period_id, controller_headers))


# ---------------------------------------------------------------------------
# Tier 1: work-order state progression (PRD §3.3)
# ---------------------------------------------------------------------------

def get_work_order(work_order_id, headers=AUDITOR):
    return get_success_data(api_client.get_work_order(work_order_id, headers))


def get_program(program_id, headers=AUDITOR):
    return get_success_data(api_client.get_capital_program(program_id, headers))


def get_estimate_for_order(work_order_id, headers=AUDITOR):
    """Return the seed estimate created with the work order (PRD §3.3:
    creation seeds estimate number one)."""
    data = get_success_data(
        api_client.list_estimates(headers, params={"work_order_id": work_order_id}))
    assert data, f"expected a seed estimate for work order {work_order_id}"
    return data[0]


def create_work_order(program_id, engineer_headers=ENGINEER, **overrides):
    """Create a DRAFT work order with its PROPOSED seed estimate (PRD §3.3).
    Returns the work order."""
    return get_success_data(api_client.create_work_order(
        create_work_order_payload(program_id=program_id, **overrides),
        engineer_headers))


def submit(work_order_id, engineer_headers=ENGINEER):
    return get_success_data(
        api_client.submit_work_order(work_order_id, engineer_headers))


def create_submitted_work_order(program_id, engineer_headers=ENGINEER,
                                **overrides):
    """DRAFT -> SUBMITTED. Returns (work_order, seed_estimate)."""
    wo = create_work_order(program_id, engineer_headers=engineer_headers,
                           **overrides)
    wo = submit(wo["id"], engineer_headers=engineer_headers)
    est = get_estimate_for_order(wo["id"])
    return wo, est


def approve_estimate(estimate_id, work_order_id, approver_headers=SUPERVISOR):
    """Approve an estimate at the work order's current version (PRD §2.7).
    Returns the approved estimate."""
    version = get_work_order(work_order_id)["version"]
    return get_success_data(api_client.approve_estimate(
        estimate_id, version, approver_headers))


def create_approved_work_order(program_id, engineer_headers=ENGINEER,
                               approver_headers=SUPERVISOR, **overrides):
    """SUBMITTED order with its seed estimate APPROVED (PRD §3.4).
    Returns (work_order, estimate)."""
    wo, est = create_submitted_work_order(program_id,
                                          engineer_headers=engineer_headers,
                                          **overrides)
    est = approve_estimate(est["id"], wo["id"], approver_headers)
    return get_work_order(wo["id"]), est


def create_authorized_work_order(program_id, engineer_headers=ENGINEER,
                                 approver_headers=SUPERVISOR,
                                 authorizer_headers=SUPERVISOR, **overrides):
    """SUBMITTED -> AUTHORIZED (PRD §3.3). Returns the AUTHORIZED order."""
    wo, _est = create_approved_work_order(
        program_id, engineer_headers=engineer_headers,
        approver_headers=approver_headers, **overrides)
    return get_success_data(
        api_client.authorize_work_order(wo["id"], authorizer_headers))


def create_in_progress_work_order(program_id, engineer_headers=ENGINEER,
                                  approver_headers=SUPERVISOR,
                                  authorizer_headers=SUPERVISOR, **overrides):
    """AUTHORIZED -> IN_PROGRESS (PRD §3.3). Returns the IN_PROGRESS order."""
    wo = create_authorized_work_order(
        program_id, engineer_headers=engineer_headers,
        approver_headers=approver_headers, authorizer_headers=authorizer_headers,
        **overrides)
    return get_success_data(api_client.start_work_order(wo["id"], SUPERVISOR))


def post_charge(work_order_id, clerk_headers=CLERK, **overrides):
    """Post a cost charge (PRD §3.5). Returns the POSTED charge row."""
    return get_success_data(api_client.create_cost_charge(
        create_cost_charge_payload(work_order_id=work_order_id, **overrides),
        clerk_headers))


def complete_work_order(work_order_id, in_service_date="2026-08-20",
                        supervisor_headers=SUPERVISOR):
    """IN_PROGRESS -> COMPLETED (PRD §3.7). Returns the COMPLETED order."""
    return get_success_data(api_client.complete_work_order(
        work_order_id, in_service_date, supervisor_headers))


def closeout_work_order(work_order_id, unitization_lines,
                        controller_headers=CONTROLLER):
    """COMPLETED -> CLOSED (PRD §3.8). Returns the CLOSED order."""
    return get_success_data(api_client.closeout_work_order(
        work_order_id, unitization_lines, controller_headers))


# ---------------------------------------------------------------------------
# Tier 2: the standard "charging-enabled" world
# ---------------------------------------------------------------------------

def setup_charging_world(estimate_cents=9_000_000, order_type="CAPITAL",
                         cost_type="MATERIAL", rate_pct=0.0,
                         program_overrides=None, period_overrides=None,
                         engineer_headers=ENGINEER):
    """Program + overhead schedule + OPEN 2026-08 period + IN_PROGRESS work
    order. Returns dict(program, period, work_order, estimate)."""
    program = create_program(**(program_overrides or {}))
    create_schedule(cost_type=cost_type,
                    order_type=order_type, rate_pct=rate_pct)
    period = create_period(**(period_overrides or {}))
    wo = create_in_progress_work_order(
        program["id"], order_type=order_type,
        initial_estimated_cost_cents=estimate_cents,
        engineer_headers=engineer_headers)
    est = get_estimate_for_order(wo["id"])
    return {"program": program, "period": period, "work_order": wo,
            "estimate": est}


def setup_completed_work_order(charges=(), in_service_date="2026-08-20",
                               **world_kwargs):
    """Charging world + posted charges + COMPLETED order (PRD §3.7).
    `charges` is an iterable of cost-charge payload overrides.
    Returns dict(world..., charges=[...])."""
    world = setup_charging_world(**world_kwargs)
    posted = [post_charge(world["work_order"]["id"], **c) for c in charges]
    wo = complete_work_order(world["work_order"]["id"], in_service_date)
    world["work_order"] = wo
    world["charges"] = posted
    return world


def setup_closed_work_order(unitization_lines, controller_headers=CONTROLLER,
                            **kwargs):
    """Full lifecycle through CLOSED (PRD §3.8). Returns dict(world..., units)."""
    world = setup_completed_work_order(**kwargs)
    wo = closeout_work_order(world["work_order"]["id"], unitization_lines,
                             controller_headers=controller_headers)
    units = get_success_data(api_client.list_fixed_asset_units(
        AUDITOR, params={"work_order_id": wo["id"]}))
    world["work_order"] = wo
    world["units"] = units
    return world


# ---------------------------------------------------------------------------
# Tier 3: CIAC and regulatory assets
# ---------------------------------------------------------------------------

def create_ciac(work_order_id, rates_headers=RATES, **overrides):
    """Pledge a CIAC agreement (PRD §3.6). Returns the PLEDGED agreement."""
    return get_success_data(api_client.create_ciac_agreement(
        create_ciac_agreement_payload(work_order_id=work_order_id, **overrides),
        rates_headers))


def receive_ciac(ciac_id, rates_headers=RATES):
    """PLEDGED -> RECEIVED (PRD §3.6)."""
    return get_success_data(
        api_client.receive_ciac_agreement(ciac_id, rates_headers))


def create_received_ciac(work_order_id, rates_headers=RATES, **overrides):
    """Pledge + receive. Returns the RECEIVED agreement."""
    ciac = create_ciac(work_order_id, rates_headers=rates_headers, **overrides)
    return receive_ciac(ciac["id"], rates_headers=rates_headers)


def create_reg_asset(rates_headers=RATES, **overrides):
    """Propose a regulatory asset (PRD §3.7). Returns the PROPOSED asset."""
    return get_success_data(api_client.create_regulatory_asset(
        create_regulatory_asset_payload(**overrides), rates_headers))


def approve_reg_asset(reg_asset_id, controller_headers=CONTROLLER):
    """PROPOSED -> APPROVED (PRD §3.7)."""
    return get_success_data(
        api_client.approve_regulatory_asset(reg_asset_id, controller_headers))


def create_approved_reg_asset(rates_headers=RATES,
                              controller_headers=CONTROLLER, **overrides):
    ra = create_reg_asset(rates_headers=rates_headers, **overrides)
    return approve_reg_asset(ra["id"], controller_headers=controller_headers)


# ---------------------------------------------------------------------------
# Tier 4: re-estimates and reads
# ---------------------------------------------------------------------------

def create_estimate(work_order_id, estimated_cost_cents,
                    engineer_headers=ENGINEER, notes=None):
    """Create a re-estimate at the work order's current version (PRD §3.4).
    Withdraws the currently PROPOSED estimate. Returns the new estimate."""
    version = get_work_order(work_order_id)["version"]
    payload = create_estimate_payload(
        work_order_id=work_order_id,
        estimated_cost_cents=estimated_cost_cents,
        expected_work_order_version=version)
    if notes is not None:
        payload["notes"] = notes
    return get_success_data(api_client.create_estimate(payload, engineer_headers))


def list_afudc_entries(work_order_id=None, accounting_period_id=None,
                       status=None, headers=AUDITOR):
    params = {}
    if work_order_id is not None:
        params["work_order_id"] = work_order_id
    if accounting_period_id is not None:
        params["accounting_period_id"] = accounting_period_id
    if status is not None:
        params["status"] = status
    return get_success_data(api_client.list_afudc_entries(headers, params=params))


def list_depreciation_entries(fixed_asset_unit_id=None, accounting_period_id=None,
                              status=None, headers=AUDITOR):
    params = {}
    if fixed_asset_unit_id is not None:
        params["fixed_asset_unit_id"] = fixed_asset_unit_id
    if accounting_period_id is not None:
        params["accounting_period_id"] = accounting_period_id
    if status is not None:
        params["status"] = status
    return get_success_data(
        api_client.list_depreciation_entries(headers, params=params))


def list_amortization_entries(regulatory_asset_id=None, accounting_period_id=None,
                              status=None, headers=AUDITOR):
    params = {}
    if regulatory_asset_id is not None:
        params["regulatory_asset_id"] = regulatory_asset_id
    if accounting_period_id is not None:
        params["accounting_period_id"] = accounting_period_id
    if status is not None:
        params["status"] = status
    return get_success_data(
        api_client.list_amortization_entries(headers, params=params))


# ---------------------------------------------------------------------------
# Tier 5: named composite scenarios (shared by several test families)
# ---------------------------------------------------------------------------

def setup_variance_hold_world(estimate_cents=10_000,
                              charge_bases=(10_000, 1_001)):
    """IN_PROGRESS CAPITAL order whose posted charges push actuals strictly
    past 110% of the approved estimate, so variance_posture is
    RE_ESTIMATE_REQUIRED (PRD §3.5). Returns the charging world dict with
    the posted charges under key "charges"."""
    world = setup_charging_world(estimate_cents=estimate_cents)
    posted = []
    for i, base in enumerate(charge_bases):
        posted.append(post_charge(world["work_order"]["id"],
                                  base_amount_cents=base,
                                  charge_date=f"2026-08-{5 + i:02d}"))
    world["charges"] = posted
    return world


def setup_closeout_overrun_world(coverage_cents=None, coverage_approved=False,
                                 rates_headers=RATES):
    """CAPITAL order approved at 100,000c with 116,000c of actuals, COMPLETED
    in period 2026-08 — the PRD §3.8 worked instance: a 15,000c tolerance and
    a 1,000c coverage requirement. Optionally attaches one regulatory asset of
    `coverage_cents` sourced to the order. Returns dict with keys program,
    period, work_order, estimate, charges, catalog, reg_asset (or None)."""
    world = setup_charging_world(estimate_cents=100_000)
    catalog = create_catalog_entry()  # TRANSFORMER 50,000c @ 12%/yr
    world["catalog"] = catalog
    posted = [
        post_charge(world["work_order"]["id"], base_amount_cents=10_000,
                    charge_date="2026-08-05"),
        post_charge(world["work_order"]["id"], base_amount_cents=106_000,
                    charge_date="2026-08-06"),
    ]
    world["charges"] = posted
    world["work_order"] = complete_work_order(world["work_order"]["id"])
    ra = None
    if coverage_cents is not None:
        ra = create_reg_asset(rates_headers=rates_headers,
                              description="Excess cost deferral",
                              original_cents=coverage_cents,
                              amortization_months=12,
                              source_work_order_id=world["work_order"]["id"])
        if coverage_approved:
            ra = approve_reg_asset(ra["id"])
    world["reg_asset"] = ra
    return world


def setup_unitized_transformer_world(catalog_overrides=None, **kwargs):
    """A CLOSED CAPITAL order with one TRANSFORMER unit (PRD §3.8).
    Returns the closed-world dict."""
    catalog = create_catalog_entry(**(catalog_overrides or {}))
    world = setup_completed_work_order(**kwargs)
    wo = closeout_work_order(world["work_order"]["id"],
                             [make_unitization_line(catalog["id"], 1)])
    units = get_success_data(api_client.list_fixed_asset_units(
        AUDITOR, params={"work_order_id": wo["id"]}))
    world.update({"work_order": wo, "catalog": catalog, "units": units})
    return world
