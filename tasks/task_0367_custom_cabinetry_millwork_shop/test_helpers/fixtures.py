"""Composite setup helpers.

Most test claims require the system to be several API calls deep into the
design-to-install lifecycle: a project must be measured, quoted, contracted,
have its deposit issued and paid, enter production, etc. These helpers encapsulate
those multi-step preambles so test bodies focus on the assertion under test.

All setup calls use get_success_data() (lenient 2xx validator) so a broken
precondition surfaces as a clear "Setup step failed" error rather than a
confusing downstream assertion failure. Every entity-backed Customer call threads
the real Customer.id through make_customer_headers() per the PRD ownership rule.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_customer_headers
from . import factories as F


ADMIN = TEST_USERS["shop_admin_headers"]
MANAGER = TEST_USERS["shop_manager_headers"]
DESIGNER = TEST_USERS["designer_headers"]
INSTALLER = TEST_USERS["installer_headers"]


# ---------------------------------------------------------------------------
# Tier 0 — primitive creators
# ---------------------------------------------------------------------------
def create_shop(**shop_overrides):
    """Create a shop. Returns the shop dict."""
    resp = api_client.create_shop(F.create_shop_payload(**shop_overrides), ADMIN)
    return get_success_data(resp)


def set_clock(shop_id, to_iso8601):
    """Set the shop test clock. Returns the shop dict."""
    resp = api_client.set_clock({"shop_id": shop_id, "to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(resp)


def create_material(shop_id, restock=0, **mat_overrides):
    """Create a material; optionally restock it with `restock` sheets.
    Returns the material dict (after restock if requested)."""
    mat = get_success_data(api_client.create_material(shop_id, F.create_material_payload(**mat_overrides), MANAGER))
    if restock:
        mat = get_success_data(api_client.restock_material(shop_id, mat["id"], {"sheets": restock}, MANAGER))
    return mat


def create_machine(shop_id, **mach_overrides):
    return get_success_data(api_client.create_machine(shop_id, F.create_machine_payload(**mach_overrides), MANAGER))


def create_customer(shop_id, **cust_overrides):
    return get_success_data(api_client.create_customer(shop_id, F.create_customer_payload(**cust_overrides), MANAGER))


def create_project(shop_id, customer_id, **proj_overrides):
    return get_success_data(api_client.create_project(shop_id, customer_id, F.create_project_payload(**proj_overrides), DESIGNER))


def add_spec(shop_id, project_id, material_id, **spec_overrides):
    return get_success_data(api_client.create_spec(shop_id, project_id, F.create_spec_payload(material_id, **spec_overrides), DESIGNER))


def add_finish(shop_id, project_id, finish_code="STAIN", **overrides):
    return get_success_data(api_client.create_finish_selection(shop_id, project_id, F.create_finish_selection_payload(finish_code, **overrides), DESIGNER))


# ---------------------------------------------------------------------------
# Tier 1 — state progression toward the contract
# ---------------------------------------------------------------------------
def setup_base_shop(shop_overrides=None):
    """Shop + material + customer. Returns (shop, material, customer).
    The shop defaults to tax_rate_bps=0, deposit_pct_bps=3000 unless overridden."""
    so = {"tax_rate_bps": 0, "deposit_pct_bps": 3000}
    if shop_overrides:
        so.update(shop_overrides)
    shop = create_shop(**so)
    material = create_material(shop["id"])
    customer = create_customer(shop["id"])
    return shop, material, customer


def setup_quoted_project(
    shop_overrides=None,
    project_overrides=None,
    specs=None,
    finish_code="STAIN",
    restock=0,
):
    """Build a project all the way to QUOTED.

    `specs` is a list of spec-override dicts (each merged onto the spec factory
    defaults). Defaults to a single qty=2 spec so the simplest STAIN qty2 totals
    (contract_total 291600, deposit 87480) are reproduced by default.

    Returns a dict with: shop, material, customer, project (at QUOTED),
    spec_ids, and the project version captured right after quote (`quote_version`).
    """
    shop, material, customer = setup_base_shop(shop_overrides)
    if restock:
        material = get_success_data(api_client.restock_material(shop["id"], material["id"], {"sheets": restock}, MANAGER))
    project = create_project(shop["id"], customer["id"], **(project_overrides or {}))
    if specs is None:
        specs = [{"quantity": 2}]
    spec_ids = []
    for s in specs:
        spec_ids.append(add_spec(shop["id"], project["id"], material["id"], **s)["id"])
    add_finish(shop["id"], project["id"], finish_code)
    get_success_data(api_client.measure_project(shop["id"], project["id"], DESIGNER))
    quoted = get_success_data(api_client.quote_project(shop["id"], project["id"], DESIGNER))
    return {
        "shop": shop,
        "material": material,
        "customer": customer,
        "project": quoted,
        "spec_ids": spec_ids,
        "quote_version": quoted["version"],
    }


def setup_contracted_project(**kwargs):
    """QUOTED project then contracted by the owning customer.

    Returns the setup_quoted_project dict plus: project (now CONTRACTED),
    deposit_draw (the auto-created DEPOSIT draw in PENDING).
    """
    ctx = setup_quoted_project(**kwargs)
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    cust_headers = make_customer_headers(ctx["customer"]["id"])
    contracted = get_success_data(
        api_client.contract_project(shop_id, proj_id, {"expected_project_version": ctx["quote_version"]}, cust_headers)
    )
    ctx["project"] = contracted
    draws, _ = _list_draws(shop_id, proj_id)
    deposit = next(d for d in draws if d["draw_type"] == "DEPOSIT")
    ctx["deposit_draw"] = deposit
    return ctx


def _list_draws(shop_id, project_id):
    body = api_client.list_draws(shop_id, project_id, MANAGER).json()
    return body["data"], body["meta"]


def issue_and_pay_deposit(ctx):
    """Issue and pay the deposit draw for a contracted-project ctx. Mutates and
    returns ctx with the paid deposit reflected (re-reads the project)."""
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    dep_id = ctx["deposit_draw"]["id"]
    cust_headers = make_customer_headers(ctx["customer"]["id"])
    get_success_data(api_client.issue_draw(shop_id, proj_id, dep_id, MANAGER))
    get_success_data(api_client.pay_draw(shop_id, proj_id, dep_id, cust_headers))
    ctx["project"] = get_success_data(api_client.get_project(shop_id, proj_id, MANAGER))
    return ctx


# ---------------------------------------------------------------------------
# Tier 2 — into production
# ---------------------------------------------------------------------------
def setup_in_production_project(
    machine_overrides=None,
    build_start="2026-07-01T09:00:00Z",
    build_end="2026-07-01T12:00:00Z",
    **quoted_kwargs,
):
    """Full path to IN_PRODUCTION: contract -> issue+pay deposit -> create a
    machine -> schedule the first build job (which drives the project to
    IN_PRODUCTION). Defaults the project to a qty=4 STANDARD/PAINT spec so the
    canonical contract_total 628992 (tax800) is reproducible when the caller
    passes the matching shop/spec overrides.

    Returns the contracted-project ctx plus: machine, build_job (SCHEDULED),
    and project re-read at IN_PRODUCTION.
    """
    quoted_kwargs.setdefault("specs", [{"quantity": 4}])
    quoted_kwargs.setdefault("finish_code", "PAINT")
    ctx = setup_contracted_project(**quoted_kwargs)
    ctx = issue_and_pay_deposit(ctx)
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    machine = create_machine(shop_id, **(machine_overrides or {"changeover_buffer_min": 0}))
    bj = get_success_data(
        api_client.create_build_job(shop_id, proj_id, F.create_build_job_payload(machine["id"], build_start, build_end), MANAGER)
    )
    ctx["machine"] = machine
    ctx["build_job"] = bj
    ctx["project"] = get_success_data(api_client.get_project(shop_id, proj_id, MANAGER))
    return ctx


def setup_committed_reservation(reservation_sheets=5, restock=8, **prod_kwargs):
    """IN_PRODUCTION project with a started build job and one COMMITTED
    reservation of `reservation_sheets` against a material restocked to `restock`.

    Returns the in-production ctx plus: reservation (COMMITTED), and the
    build_job left in IN_PROGRESS (started, not completed).
    """
    # Use a STAIN/qty2 project to keep contract math simple; the material is
    # restocked so the reservation fits.
    prod_kwargs.setdefault("specs", [{"quantity": 2}])
    prod_kwargs.setdefault("finish_code", "STAIN")
    prod_kwargs.setdefault("restock", restock)
    ctx = setup_in_production_project(**prod_kwargs)
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    res = get_success_data(
        api_client.create_reservation(shop_id, proj_id, F.create_reservation_payload(ctx["material"]["id"], reservation_sheets), MANAGER)
    )
    res = get_success_data(api_client.commit_reservation(shop_id, proj_id, res["id"], MANAGER))
    started = get_success_data(api_client.start_build_job(shop_id, proj_id, ctx["build_job"]["id"], MANAGER))
    ctx["reservation"] = res
    ctx["build_job"] = started
    return ctx


# ---------------------------------------------------------------------------
# Tier 3 — change-order lifecycle
# ---------------------------------------------------------------------------
def setup_submitted_change_order(spec_price_delta_cents=50000, **prod_kwargs):
    """IN_PRODUCTION project with a ChangeOrder driven to SUBMITTED (project at
    CHANGE_PENDING). Returns the production ctx plus: change_order (SUBMITTED),
    and project re-read at CHANGE_PENDING (`project`), with the project version
    captured right after submit (`submit_version`)."""
    ctx = setup_in_production_project(**prod_kwargs)
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    co = get_success_data(
        api_client.create_change_order(shop_id, proj_id, F.create_change_order_payload(spec_price_delta_cents), MANAGER)
    )
    pv = get_success_data(api_client.get_project(shop_id, proj_id, MANAGER))["version"]
    co = get_success_data(
        api_client.submit_change_order(shop_id, proj_id, co["id"], {"expected_project_version": pv}, MANAGER)
    )
    ctx["change_order"] = co
    ctx["project"] = get_success_data(api_client.get_project(shop_id, proj_id, MANAGER))
    ctx["submit_version"] = ctx["project"]["version"]
    return ctx


# ---------------------------------------------------------------------------
# Tier 4 — through delivery / install
# ---------------------------------------------------------------------------
def setup_ready_for_delivery_project(install_overrides=None, **prod_kwargs):
    """Drive a project to READY_FOR_DELIVERY: in-production -> start+complete the
    build job -> mark-ready. Returns the production ctx with project re-read at
    READY_FOR_DELIVERY (`project`)."""
    ctx = setup_in_production_project(**prod_kwargs)
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    bj_id = ctx["build_job"]["id"]
    get_success_data(api_client.start_build_job(shop_id, proj_id, bj_id, MANAGER))
    get_success_data(api_client.complete_build_job(shop_id, proj_id, bj_id, MANAGER))
    get_success_data(api_client.mark_ready(shop_id, proj_id, MANAGER))
    ctx["project"] = get_success_data(api_client.get_project(shop_id, proj_id, MANAGER))
    return ctx


def setup_installation_punch_pending(
    install_date="2026-09-10",
    window_start="2026-09-10T08:00:00Z",
    window_end="2026-09-10T12:00:00Z",
    **ready_kwargs,
):
    """READY_FOR_DELIVERY project with an Installation walked through to
    PUNCH_PENDING. Returns the ready ctx plus: installation (PUNCH_PENDING)."""
    ctx = setup_ready_for_delivery_project(**ready_kwargs)
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    inst = get_success_data(
        api_client.create_installation(shop_id, proj_id, F.create_installation_payload(install_date, window_start, window_end), INSTALLER)
    )
    get_success_data(api_client.start_installation(shop_id, proj_id, inst["id"], INSTALLER))
    inst = get_success_data(api_client.walkthrough_installation(shop_id, proj_id, inst["id"], INSTALLER))
    ctx["installation"] = inst
    return ctx


def add_punch_item(shop_id, project_id, installation_id, description="Defect", severity=None):
    """Add a punch item to an installation. Returns the punch item dict.
    `severity` may be 'MINOR' or 'MAJOR'; omitted lets the server apply its default."""
    payload = F.create_punch_item_payload(description=description)
    if severity is not None:
        payload["severity"] = severity
    return get_success_data(
        api_client.create_punch_item(shop_id, project_id, installation_id, payload, INSTALLER)
    )


def setup_installed_project(deposit_only=True, **inst_kwargs):
    """Drive a project to INSTALLED (installation completed with no open punch,
    bubbling the project to INSTALLED and creating a RETAINAGE draw). Only the
    deposit has been paid, so the balance is still outstanding.

    Returns the installation ctx with project re-read at INSTALLED (`project`)."""
    ctx = setup_installation_punch_pending(**inst_kwargs)
    shop_id = ctx["shop"]["id"]
    proj_id = ctx["project"]["id"]
    inst_id = ctx["installation"]["id"]
    get_success_data(api_client.complete_installation(shop_id, proj_id, inst_id, INSTALLER))
    ctx["project"] = get_success_data(api_client.get_project(shop_id, proj_id, MANAGER))
    return ctx
