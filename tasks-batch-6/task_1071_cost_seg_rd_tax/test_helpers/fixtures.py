"""Composite setup helpers.

Every helper builds its preconditions from scratch (the server DB is reset before
each test) using only PRD-declared endpoints, and uses get_success_data() so a
setup failure surfaces as a clear "Setup failed" error rather than a confusing
assertion. Ownership-gated Engineer/Reviewer calls are always issued with headers
built from the acting Engineer's real id (see test_users.make_engineer_headers).
"""
from prd_bench_local_runner.testing import get_success_data
from .test_users import (
    TEST_USERS, make_engineer_headers, make_reviewer_headers,
)
from . import factories as f


SM = TEST_USERS["study_manager_headers"]
CPA = TEST_USERS["cpa_headers"]


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------
def create_client(api, active=True, **overrides):
    """Create a Client (default: activated to ACTIVE)."""
    cli = get_success_data(api.create_client(f.create_client_payload(**overrides), SM))
    if active:
        cli = get_success_data(api.activate_client(cli["id"], SM))
    return cli


def create_engineer(api, **overrides):
    return get_success_data(api.create_engineer(f.create_engineer_payload(**overrides), SM))


def create_property(api, client_id, **overrides):
    return get_success_data(api.create_property(f.create_property_payload(client_id, **overrides), SM))


def create_study(api, client_id, study_type="COST_SEGREGATION", **overrides):
    return get_success_data(api.create_study(
        f.create_study_payload(client_id, study_type, **overrides), SM))


def set_clock(api, iso):
    return get_success_data(api.set_clock(iso, SM))


# ---------------------------------------------------------------------------
# Cost-seg pipeline
# ---------------------------------------------------------------------------
def setup_cost_seg_engineering(api, *, marginal_tax_rate=0.21, tax_year=2024,
                               placed_in_service_date="2024-03-01T00:00:00.000Z",
                               purchase_price_cents=120000000, land_value_cents=20000000,
                               is_look_back=False, scope_overrides=None,
                               with_reviewer=False):
    """Active client + property + engineer + a COST_SEGREGATION study scoped and
    engineer-assigned, i.e. in ENGINEERING. Returns a context dict.

    scope_overrides lets a test control fee_type / fee_fixed_amount_cents /
    fee_percent_bps on the scope call.
    """
    cli = create_client(api, marginal_tax_rate=marginal_tax_rate)
    eng = create_engineer(api)
    prop = create_property(api, cli["id"], purchase_price_cents=purchase_price_cents,
                           land_value_cents=land_value_cents,
                           placed_in_service_date=placed_in_service_date)
    st = create_study(api, cli["id"], "COST_SEGREGATION", tax_year=tax_year,
                      is_look_back=is_look_back)
    scope = f.scope_cost_seg_payload(prop["id"], **(scope_overrides or {}))
    get_success_data(api.scope_study(st["id"], scope, SM))
    get_success_data(api.assign_engineer(st["id"], {"assigned_engineer_id": eng["id"]}, SM))
    ctx = {
        "client": cli, "engineer": eng, "property": prop, "study": st,
        "client_id": cli["id"], "engineer_id": eng["id"], "property_id": prop["id"],
        "study_id": st["id"],
        "eng_headers": make_engineer_headers(eng["id"]),
    }
    if with_reviewer:
        rev = create_engineer(api, email="reviewer@example.com")
        ctx["reviewer"] = rev
        ctx["reviewer_id"] = rev["id"]
        ctx["rev_headers"] = make_reviewer_headers(rev["id"])
    return ctx


def add_component(api, ctx, name, asset_class, cost, allocate=False):
    """Add an AssetComponent (as the assigned engineer); optionally allocate it."""
    comp = get_success_data(api.add_asset_component(
        ctx["study_id"],
        f.asset_component_payload(name, asset_class, cost),
        ctx["eng_headers"]))
    if allocate:
        comp = get_success_data(api.allocate_component(comp["id"], ctx["eng_headers"]))
    return comp


def add_allocated_components(api, ctx, comps):
    """comps = list of (name, asset_class, cost). Returns list of allocated components."""
    return [add_component(api, ctx, n, ac, c, allocate=True) for (n, ac, c) in comps]


# ---------------------------------------------------------------------------
# R&D pipeline
# ---------------------------------------------------------------------------
def setup_rd_engineering(api, *, credit_method="ASC", tax_year=2024,
                         scope_overrides=None, with_reviewer=False):
    """Active client + engineer + an RD_CREDIT study scoped (credit_method) and
    engineer-assigned, i.e. in ENGINEERING."""
    cli = create_client(api)
    eng = create_engineer(api)
    st = create_study(api, cli["id"], "RD_CREDIT", tax_year=tax_year)
    scope = f.scope_rd_payload(credit_method, **(scope_overrides or {}))
    get_success_data(api.scope_study(st["id"], scope, SM))
    get_success_data(api.assign_engineer(st["id"], {"assigned_engineer_id": eng["id"]}, SM))
    ctx = {
        "client": cli, "engineer": eng, "study": st,
        "client_id": cli["id"], "engineer_id": eng["id"], "study_id": st["id"],
        "eng_headers": make_engineer_headers(eng["id"]),
    }
    if with_reviewer:
        rev = create_engineer(api, email="reviewer@example.com")
        ctx["reviewer"] = rev
        ctx["reviewer_id"] = rev["id"]
        ctx["rev_headers"] = make_reviewer_headers(rev["id"])
    return ctx


def add_qualified_qre(api, ctx, lines):
    """lines = list of (category, gross, qualified_percent). Qualifies each. Returns list."""
    out = []
    for (cat, gross, qp) in lines:
        q = get_success_data(api.add_qre_line_item(
            ctx["study_id"], f.qre_line_payload(cat, gross, qp), ctx["eng_headers"]))
        q = get_success_data(api.qualify_qre(q["id"], ctx["eng_headers"]))
        out.append(q)
    return out


# ---------------------------------------------------------------------------
# Lifecycle transitions
# ---------------------------------------------------------------------------
def submit(api, ctx):
    return get_success_data(api.submit_review(ctx["study_id"], ctx["eng_headers"]))


def reject(api, ctx, note=None):
    payload = {"review_note": note} if note is not None else None
    return get_success_data(api.reject_study(ctx["study_id"], ctx["rev_headers"], payload))


def finalize(api, ctx):
    return get_success_data(api.finalize_study(ctx["study_id"], ctx["rev_headers"]))


def deliver(api, ctx):
    return get_success_data(api.deliver_study(ctx["study_id"], CPA))


def first_fee_invoice(api, ctx):
    invs, _ = _list(api.list_fee_invoices(ctx["study_id"], SM))
    return invs[0] if invs else None


def only_report(api, ctx):
    reps, _ = _list(api.list_reports(ctx["study_id"], SM))
    return reps[0] if reps else None


def _list(response):
    body = response.json()
    return body["data"], body["meta"]


# ---------------------------------------------------------------------------
# High-level composite scenarios (reused across difficulty + corner instances)
# ---------------------------------------------------------------------------
def setup_cost_seg_finalized(api, *, scope_overrides=None, comps=None,
                             marginal_tax_rate=0.21, is_look_back=False,
                             placed_in_service_date="2024-03-01T00:00:00.000Z",
                             tax_year=2024):
    """Full cost-seg pipeline through FINALIZED (report ISSUED, fee invoice created).
    Returns the context dict augmented with the reviewer."""
    ctx = setup_cost_seg_engineering(
        api, marginal_tax_rate=marginal_tax_rate, tax_year=tax_year,
        placed_in_service_date=placed_in_service_date, is_look_back=is_look_back,
        scope_overrides=scope_overrides, with_reviewer=True)
    add_allocated_components(api, ctx, comps or [("5yr", "FIVE_YEAR", 10000000)])
    submit(api, ctx)
    finalize(api, ctx)
    return ctx


def setup_cost_seg_delivered_lookback(api, *, comps=None, tax_year=2024,
                                      placed_in_service_date="2024-03-01T00:00:00.000Z"):
    """Full cost-seg look-back pipeline through DELIVERED. Captures study.version
    at deliver under ctx['delivered_version']."""
    ctx = setup_cost_seg_finalized(
        api, scope_overrides={"fee_type": "FIXED", "fee_fixed_amount_cents": 100000},
        comps=comps, is_look_back=True, tax_year=tax_year,
        placed_in_service_date=placed_in_service_date)
    st = deliver(api, ctx)
    ctx["delivered_version"] = st["version"]
    ctx["study"] = st
    return ctx
