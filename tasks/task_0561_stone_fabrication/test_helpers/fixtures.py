"""Composite setup helpers.

Each pytest test runs against a freshly restarted server with an empty database, so every
helper here builds all of its preconditions from scratch using only PRD-declared endpoints.
Helpers use get_success_data() (lenient 2xx validator) so setup failures surface clearly.

Canonical "standard job" used throughout the difficulty setups:
  PREMIUM project, quote est_sqft=40 / OGEE / edge_linear_ft=25 / 2 SINK cutouts
    -> quote_total_cents = 6500*40 + 2000*25 + 2*15000 = 340000  (above 80000 floor)
    -> deposit required = round_half_up(340000 * 0.50) = 170000
  Template measured 40 / OGEE / 25 with two SINK cutouts, approved
    -> final_invoice_cents = 282750 + 54375 + 16313 + 16313 = 369751 (tax rounded per line)
  Slab nominal 50; pieces [25, 15]
    -> actual_consumed_sqft = 25 + 15 + 0.10*2 = 40.20 ; remaining 9.80
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS
from .factories import (
    create_project_payload,
    create_quote_payload,
    create_template_payload,
    create_cutout_payload,
    create_slab_payload,
    create_bay_payload,
    create_crew_payload,
    create_fabrication_order_payload,
    create_install_job_payload,
    create_payment_payload,
    create_change_order_payload,
    create_warranty_claim_payload,
)

SALESREP = TEST_USERS["salesrep_headers"]
FABRICATOR = TEST_USERS["fabricator_headers"]
INSTALLER = TEST_USERS["installer_headers"]
SHOPMANAGER = TEST_USERS["shopmanager_headers"]

STD_QUOTE = dict(
    est_sqft=40,
    material_grade="PREMIUM",
    edge_profile="OGEE",
    edge_linear_ft=25,
    sink_count=2,
    faucet_count=0,
    cooktop_count=0,
)
DEFAULT_PIECES = [{"label": "A", "sqft": 25}, {"label": "B", "sqft": 15}]
DEFAULT_START = "2026-06-10T08:00:00Z"
DEFAULT_END = "2026-06-10T12:00:00Z"
STD_DEPOSIT_CENTS = 170000


def _data(resp):
    return get_success_data(resp)


# --------------------------------------------------------------------------
# Single-step building blocks
# --------------------------------------------------------------------------
def new_project(material_grade="PREMIUM", customer_name="Test Customer", address="1 Rock Rd"):
    return _data(api_client.create_project(
        create_project_payload(customer_name=customer_name, address=address, material_grade=material_grade),
        SALESREP,
    ))


def get_project_data(project_id):
    return _data(api_client.get_project(project_id, SALESREP))


def current_version(project_id):
    return get_project_data(project_id)["version"]


def add_active_quote(project_id, expected_version=None, **overrides):
    if expected_version is None:
        expected_version = current_version(project_id)
    payload = create_quote_payload(expected_project_version=expected_version, **{**STD_QUOTE, **overrides})
    return _data(api_client.create_quote(project_id, payload, SALESREP))


def add_payment(project_id, amount_cents, kind):
    return _data(api_client.create_payment(
        project_id, create_payment_payload(amount_cents=amount_cents, kind=kind), SALESREP))


def add_template(project_id, measured_sqft=40, edge_profile="OGEE", edge_linear_ft=25):
    return _data(api_client.create_template(
        project_id,
        create_template_payload(measured_sqft=measured_sqft, edge_profile=edge_profile, edge_linear_ft=edge_linear_ft),
        FABRICATOR,
    ))


def add_cutout(template_id, cutout_type="SINK"):
    return _data(api_client.create_cutout(template_id, create_cutout_payload(cutout_type=cutout_type), FABRICATOR))


def approve_template(template_id):
    return _data(api_client.approve_template(template_id, FABRICATOR))


def new_slab(nominal_sqft=50, material_grade="PREMIUM", slab_label="SL1"):
    return _data(api_client.create_slab(
        create_slab_payload(slab_label=slab_label, material_grade=material_grade, nominal_sqft=nominal_sqft),
        FABRICATOR,
    ))


def get_slab_data(slab_id):
    return _data(api_client.get_slab(slab_id, FABRICATOR))


def new_bay(name="BAY1"):
    return _data(api_client.create_bay(create_bay_payload(name=name), SHOPMANAGER))


def new_crew(name="CREW1"):
    return _data(api_client.create_crew(create_crew_payload(name=name), SHOPMANAGER))


def new_fab_order(project_id, template_id, slab_id, bay_id, pieces=None, start=DEFAULT_START, end=DEFAULT_END):
    if pieces is None:
        pieces = [dict(p) for p in DEFAULT_PIECES]
    return _data(api_client.create_fabrication_order(
        create_fabrication_order_payload(
            project_id=project_id, template_id=template_id, slab_id=slab_id, bay_id=bay_id,
            scheduled_start=start, scheduled_end=end, pieces=pieces,
        ),
        FABRICATOR,
    ))


def add_change_order(project_id, delta_cents=0, reopens_template=None, description="scope change"):
    version = current_version(project_id)
    payload = create_change_order_payload(
        expected_project_version=version, description=description, delta_cents=delta_cents)
    if reopens_template is not None:
        payload["reopens_template"] = reopens_template
    return _data(api_client.create_change_order(project_id, payload, SALESREP))


def approve_change_order(change_order_id):
    return _data(api_client.approve_change_order(change_order_id, SHOPMANAGER))


# --------------------------------------------------------------------------
# Composite fixtures
# --------------------------------------------------------------------------
def setup_project_with_quote(material_grade="PREMIUM", **quote_overrides):
    """Project + one ACTIVE quote (quote_total 340000 with std overrides). Returns ctx."""
    p = new_project(material_grade=material_grade)
    q = add_active_quote(p["id"], p["version"], material_grade=material_grade, **quote_overrides)
    p = get_project_data(p["id"])
    return {"p_id": p["id"], "project": p, "q_id": q["id"], "quote": q}


def setup_measured_template_project(with_deposit=True, sink_cutouts=0, material_grade="PREMIUM"):
    """Project + quote + (optional DEPOSIT 170000) + MEASURED template (+ optional SINK cutouts).

    Template is NOT approved. Returns ctx with p_id, t_id.
    """
    ctx = setup_project_with_quote(material_grade=material_grade)
    if with_deposit:
        add_payment(ctx["p_id"], STD_DEPOSIT_CENTS, "DEPOSIT")
    t = add_template(ctx["p_id"])
    for _ in range(sink_cutouts):
        add_cutout(t["id"], "SINK")
    ctx.update({"t_id": t["id"], "template": t})
    ctx["project"] = get_project_data(ctx["p_id"])
    return ctx


def setup_priced_project(with_deposit=True, sink_cutouts=0, material_grade="PREMIUM"):
    """Project + quote + (optional DEPOSIT) + APPROVED template (+ optional SINK cutouts).

    With sink_cutouts=2 the approved template prices final_invoice_cents = 369751.
    Returns ctx with p_id, t_id, and the re-read project.
    """
    ctx = setup_measured_template_project(
        with_deposit=with_deposit, sink_cutouts=sink_cutouts, material_grade=material_grade)
    approve_template(ctx["t_id"])
    ctx["project"] = get_project_data(ctx["p_id"])
    return ctx


def setup_scheduled_fab(material_grade="PREMIUM", sink_cutouts=0, nominal_sqft=50, pieces=None):
    """Deposit-paid, approved-template project + slab + bay + SCHEDULED fabrication order.

    Slab is RESERVED at actual_consumed_sqft (40.20 for the default pieces).
    """
    ctx = setup_priced_project(with_deposit=True, sink_cutouts=sink_cutouts, material_grade=material_grade)
    sl = new_slab(nominal_sqft=nominal_sqft)
    b = new_bay()
    fo = new_fab_order(ctx["p_id"], ctx["t_id"], sl["id"], b["id"], pieces=pieces)
    ctx.update({"sl_id": sl["id"], "slab": sl, "b_id": b["id"], "bay": b, "f_id": fo["id"], "fab": fo})
    return ctx


def setup_complete_fab(**kwargs):
    """Fabrication order driven to COMPLETE (slab CONSUMED, remnant created)."""
    ctx = setup_scheduled_fab(**kwargs)
    api_client.start_cut(ctx["f_id"], FABRICATOR)
    api_client.qc_fabrication_order(ctx["f_id"], {"result": "PASS"}, FABRICATOR)
    _data(api_client.complete_fabrication_order(ctx["f_id"], FABRICATOR))
    return ctx


def setup_install_done(**kwargs):
    """Full pipeline to install DONE (Project INSTALLED, deposit-only so not PAID_IN_FULL)."""
    ctx = setup_complete_fab(**kwargs)
    c = new_crew()
    ij = _data(api_client.create_install_job(
        create_install_job_payload(
            project_id=ctx["p_id"], fabrication_order_id=ctx["f_id"], crew_id=c["id"], install_date="2026-06-15"),
        INSTALLER,
    ))
    api_client.start_install(ij["id"], INSTALLER)
    _data(api_client.complete_install(ij["id"], INSTALLER))
    ctx.update({"c_id": c["id"], "crew": c, "ij_id": ij["id"], "install": ij})
    return ctx


def setup_warranty_submitted(claim_type="CRACK", **kwargs):
    """Full pipeline to install DONE with a SUBMITTED warranty claim (default clock, in window)."""
    ctx = setup_install_done(**kwargs)
    wc = _data(api_client.create_warranty_claim(
        ctx["ij_id"], create_warranty_claim_payload(claim_type=claim_type, description="defect"), INSTALLER))
    ctx.update({"wc_id": wc["id"], "claim": wc})
    return ctx


def setup_closed_project():
    """Project driven all the way to CLOSED via a full BALANCE payment before install completion.

    PREMIUM project + quote + approved template (2 SINK cutouts -> final_invoice 369751) +
    a single BALANCE payment of 369751 (-> PAID_IN_FULL) + fab COMPLETE + install DONE
    (-> Project CLOSED because payment_status is PAID_IN_FULL at install DONE).
    """
    ctx = setup_priced_project(with_deposit=False, sink_cutouts=2)
    add_payment(ctx["p_id"], 369751, "BALANCE")
    sl = new_slab()
    b = new_bay()
    fo = new_fab_order(ctx["p_id"], ctx["t_id"], sl["id"], b["id"])
    api_client.start_cut(fo["id"], FABRICATOR)
    api_client.qc_fabrication_order(fo["id"], {"result": "PASS"}, FABRICATOR)
    api_client.complete_fabrication_order(fo["id"], FABRICATOR)
    c = new_crew()
    ij = _data(api_client.create_install_job(
        create_install_job_payload(
            project_id=ctx["p_id"], fabrication_order_id=fo["id"], crew_id=c["id"], install_date="2026-06-15"),
        INSTALLER,
    ))
    api_client.start_install(ij["id"], INSTALLER)
    api_client.complete_install(ij["id"], INSTALLER)
    ctx.update({"sl_id": sl["id"], "b_id": b["id"], "f_id": fo["id"], "c_id": c["id"], "ij_id": ij["id"]})
    ctx["project"] = get_project_data(ctx["p_id"])
    return ctx
