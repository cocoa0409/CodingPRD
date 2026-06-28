"""Composite setup helpers for multi-step test prerequisites.

The harness restarts the server (empty database) before every test, so each
fixture builds its preconditions from scratch using only PRD-declared endpoints.
Fixtures use get_success_data() (lenient validator) internally so setup failures
surface as clear "setup failed" errors rather than confusing assertion failures.

Identity threading: the Customer role is entity_backed (PRD §2.1). Ownership-
gated calls (quote accept, record payment, open/cancel callback) thread
make_customer_headers(customer["id"]) using the real Customer.id. OpsAdmin,
SalesRep, and Scheduler are opaque and use the shared constants.

A single STANDARD project built from the canonical measure (gross 600, run 20,
roll_width 15) yields net_area 648.00 and, with depth 3 / drainage NONE, a quote
total of 431568 cents, deposit (0.30) of 129470, and a balance of 302098.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from . import factories as f
from .test_users import TEST_USERS, make_customer_headers

ADMIN = TEST_USERS["ops_admin_headers"]
SALES = TEST_USERS["sales_rep_headers"]
SCHED = TEST_USERS["scheduler_headers"]

# Canonical figures for the default STANDARD build (net 648, depth 3, NONE drainage).
STD_TOTAL_CENTS = 431_568
STD_DEPOSIT_CENTS = 129_470
STD_BALANCE_CENTS = 302_098


# ─── Atomic building blocks ──────────────────────────────────────────────────
def create_customer(**overrides):
    return get_success_data(api_client.create_customer(f.create_customer_payload(**overrides), ADMIN))


def create_turf_product(**overrides):
    return get_success_data(
        api_client.create_turf_product(f.create_turf_product_payload(**overrides), ADMIN)
    )


def create_infill_product(**overrides):
    return get_success_data(
        api_client.create_infill_product(f.create_infill_product_payload(**overrides), ADMIN)
    )


def create_crew(**overrides):
    return get_success_data(api_client.create_crew(f.create_crew_payload(**overrides), ADMIN))


def create_project(customer_id, **overrides):
    return get_success_data(
        api_client.create_project(f.create_project_payload(customer_id, **overrides), SALES)
    )


def create_site_measure(project_id, **overrides):
    return get_success_data(
        api_client.create_site_measure(project_id, f.create_site_measure_payload(**overrides), SALES)
    )


def create_design_layout(project_id, site_measure_id, turf_id, infill_id, variant, **overrides):
    return get_success_data(
        api_client.create_design_layout(
            project_id,
            f.create_design_layout_payload(site_measure_id, turf_id, infill_id, variant, **overrides),
            SALES,
        )
    )


def accept_design_layout(project_id, design_id):
    return get_success_data(api_client.accept_design_layout(project_id, design_id, SALES))


def create_base_prep_scope(project_id, design_id, base_depth_in=3, **overrides):
    return get_success_data(
        api_client.create_base_prep_scope(
            project_id, f.create_base_prep_scope_payload(design_id, base_depth_in, **overrides), SALES
        )
    )


def finalize_base_prep_scope(project_id, scope_id):
    return get_success_data(api_client.finalize_base_prep_scope(project_id, scope_id, SALES))


def create_quote(project_id, design_id, scope_id, **overrides):
    return get_success_data(
        api_client.create_quote(
            project_id, f.create_quote_payload(design_id, scope_id, **overrides), SALES
        )
    )


def send_quote(project_id, quote_id):
    return get_success_data(api_client.send_quote(project_id, quote_id, SALES))


def project_version(project_id):
    return get_success_data(api_client.get_project(project_id, ADMIN))["version"]


def accept_quote(project_id, quote_id, customer_id, expected_version=None):
    if expected_version is None:
        expected_version = project_version(project_id)
    return get_success_data(
        api_client.accept_quote(
            project_id,
            quote_id,
            f.accept_quote_payload(expected_version),
            make_customer_headers(customer_id),
        )
    )


def record_payment(project_id, customer_id, kind, amount_cents):
    return get_success_data(
        api_client.create_payment(
            project_id, f.create_payment_payload(kind, amount_cents), make_customer_headers(customer_id)
        )
    )


def settle_payment(payment_id):
    return get_success_data(api_client.settle_payment(f.settle_payment_payload(payment_id), ADMIN))


def create_warranty_plan(project_id, tier):
    return get_success_data(
        api_client.create_warranty_plan(project_id, f.create_warranty_plan_payload(tier), SALES)
    )


def create_install_job(project_id, crew_id, scheduled_start, scheduled_end):
    return get_success_data(
        api_client.create_install_job(
            project_id, f.create_install_job_payload(crew_id, scheduled_start, scheduled_end), SCHED
        )
    )


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(f.clock_payload(to_iso8601), ADMIN))


# ─── Tier 1/2: catalog + measured project ────────────────────────────────────
def setup_catalog(turf_overrides=None, infill_overrides=None):
    """Create one turf product and one infill product. Returns (turf, infill)."""
    turf = create_turf_product(**(turf_overrides or {}))
    infill = create_infill_product(**(infill_overrides or {}))
    return turf, infill


def setup_measured_project(measure_overrides=None, customer_overrides=None):
    """Customer + DRAFT project + first RECORDED measure -> MEASURED.
    Returns (customer, project, measure)."""
    customer = create_customer(**(customer_overrides or {}))
    project = create_project(customer["id"])
    measure = create_site_measure(project["id"], **(measure_overrides or {}))
    return customer, project, measure


def setup_designed_project(
    variant="STANDARD",
    measure_overrides=None,
    turf_overrides=None,
    infill_overrides=None,
):
    """Measured project with an ACCEPTED design (project advances to DESIGNED).
    Returns dict with customer, project, measure, turf, infill, design."""
    turf, infill = setup_catalog(turf_overrides, infill_overrides)
    customer, project, measure = setup_measured_project(measure_overrides)
    design = create_design_layout(
        project["id"], measure["id"], turf["id"], infill["id"], variant
    )
    accept_design_layout(project["id"], design["id"])
    return {
        "customer": customer,
        "project": project,
        "measure": measure,
        "turf": turf,
        "infill": infill,
        "design": design,
    }


def setup_finalized_scope_project(
    variant="STANDARD",
    base_depth_in=3,
    measure_overrides=None,
    turf_overrides=None,
    infill_overrides=None,
):
    """Designed project + a FINALIZED BasePrepScope. Returns the setup_designed_project
    dict plus 'scope'."""
    ctx = setup_designed_project(variant, measure_overrides, turf_overrides, infill_overrides)
    scope = create_base_prep_scope(ctx["project"]["id"], ctx["design"]["id"], base_depth_in)
    finalize_base_prep_scope(ctx["project"]["id"], scope["id"])
    ctx["scope"] = scope
    return ctx


# ─── Tier 3: quote lifecycle shortcuts ───────────────────────────────────────
def setup_sent_quote_project(
    variant="STANDARD",
    base_depth_in=3,
    quote_overrides=None,
    measure_overrides=None,
    turf_overrides=None,
    infill_overrides=None,
):
    """Finalized-scope project with one DRAFT quote SENT (project -> QUOTED).
    Returns the ctx dict plus 'quote' (the sent quote, re-read)."""
    ctx = setup_finalized_scope_project(
        variant, base_depth_in, measure_overrides, turf_overrides, infill_overrides
    )
    quote = create_quote(
        ctx["project"]["id"], ctx["design"]["id"], ctx["scope"]["id"], **(quote_overrides or {})
    )
    sent = send_quote(ctx["project"]["id"], quote["id"])
    ctx["quote"] = sent
    return ctx


def setup_deposit_paid_project(
    variant="STANDARD",
    base_depth_in=3,
    deposit_cents=STD_DEPOSIT_CENTS,
    quote_overrides=None,
    measure_overrides=None,
    turf_overrides=None,
    infill_overrides=None,
    warranty_tier=None,
):
    """Full pipeline through DEPOSIT_PAID/DEPOSIT_SETTLED: accept the sent quote,
    record + settle a sufficient DEPOSIT payment. Optionally author a PENDING
    warranty plan before acceptance. Returns ctx with 'quote', 'deposit_payment',
    and (if requested) 'warranty'."""
    qo = dict(quote_overrides or {})
    qo.setdefault("deposit_pct", 0.30)
    ctx = setup_sent_quote_project(
        variant, base_depth_in, qo, measure_overrides, turf_overrides, infill_overrides
    )
    if warranty_tier is not None:
        ctx["warranty"] = create_warranty_plan(ctx["project"]["id"], warranty_tier)
    accept_quote(ctx["project"]["id"], ctx["quote"]["id"], ctx["customer"]["id"])
    dep = record_payment(ctx["project"]["id"], ctx["customer"]["id"], "DEPOSIT", deposit_cents)
    settle_payment(dep["id"])
    ctx["deposit_payment"] = dep
    return ctx


def setup_scheduled_project(
    crew_overrides=None,
    scheduled_start="2026-04-10T09:00:00Z",
    scheduled_end="2026-04-10T17:00:00Z",
    variant="STANDARD",
    base_depth_in=3,
    deposit_cents=STD_DEPOSIT_CENTS,
    warranty_tier=None,
    measure_overrides=None,
    turf_overrides=None,
    infill_overrides=None,
):
    """Deposit-paid project with one SCHEDULED install job. Returns ctx with
    'crew' and 'install_job'."""
    ctx = setup_deposit_paid_project(
        variant=variant,
        base_depth_in=base_depth_in,
        deposit_cents=deposit_cents,
        measure_overrides=measure_overrides,
        turf_overrides=turf_overrides,
        infill_overrides=infill_overrides,
        warranty_tier=warranty_tier,
    )
    crew = create_crew(**(crew_overrides or {}))
    job = create_install_job(ctx["project"]["id"], crew["id"], scheduled_start, scheduled_end)
    ctx["crew"] = crew
    ctx["install_job"] = job
    return ctx


def setup_installed_project(
    scheduled_start="2026-04-10T09:00:00Z",
    scheduled_end="2026-04-10T17:00:00Z",
    variant="STANDARD",
    base_depth_in=3,
    deposit_cents=STD_DEPOSIT_CENTS,
    warranty_tier=None,
    crew_overrides=None,
    measure_overrides=None,
    turf_overrides=None,
    infill_overrides=None,
):
    """Scheduled project whose install is started and COMPLETED (project ->
    INSTALLED, finance -> BALANCE_DUE, any PENDING warranty -> ACTIVE). The clock
    is left at startup default 2026-04-01; the default scheduled_start of
    2026-04-10 is reached by advancing the clock here so start() is permitted.
    Returns the scheduled ctx with the install job re-read."""
    ctx = setup_scheduled_project(
        crew_overrides=crew_overrides,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        variant=variant,
        base_depth_in=base_depth_in,
        deposit_cents=deposit_cents,
        warranty_tier=warranty_tier,
        measure_overrides=measure_overrides,
        turf_overrides=turf_overrides,
        infill_overrides=infill_overrides,
    )
    set_clock(scheduled_start)
    pid = ctx["project"]["id"]
    jid = ctx["install_job"]["id"]
    get_success_data(api_client.start_install_job(pid, jid, SCHED))
    ctx["install_job"] = get_success_data(api_client.complete_install_job(pid, jid, SCHED))
    return ctx


def setup_paid_in_full_project(
    balance_cents=STD_BALANCE_CENTS,
    scheduled_start="2026-04-10T09:00:00Z",
    scheduled_end="2026-04-10T17:00:00Z",
    deposit_cents=STD_DEPOSIT_CENTS,
    warranty_tier=None,
    crew_overrides=None,
):
    """Installed STANDARD project advanced to PAID_IN_FULL by recording and
    settling a BALANCE payment that covers the contract total. Returns the
    installed ctx with 'balance_payment'."""
    ctx = setup_installed_project(
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        deposit_cents=deposit_cents,
        warranty_tier=warranty_tier,
        crew_overrides=crew_overrides,
    )
    bal = record_payment(ctx["project"]["id"], ctx["customer"]["id"], "BALANCE", balance_cents)
    settle_payment(bal["id"])
    ctx["balance_payment"] = bal
    return ctx
