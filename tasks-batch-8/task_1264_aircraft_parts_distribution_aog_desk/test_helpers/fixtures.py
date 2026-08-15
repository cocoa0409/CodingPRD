"""
Composite setup helpers for multi-step test prerequisites (PRD §3 workflows).

Uses get_success_data() (lenient) internally so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading: CustomerContact calls inside fixtures always use
make_customer_headers(customer["id"]) because ownership checks compare
X-User-ID against the resource's customer_id (PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_customer_payload, create_part_payload, create_inventory_unit_payload,
    create_aog_request_payload, make_quote_line, create_quote_payload,
    create_shipment_payload, create_charter_slot_payload, create_loan_payload,
    create_warranty_claim_payload, create_return_authorization_payload,
)
from .constants import TEST_DEFAULTS
from .test_users import TEST_USERS, make_customer_headers

AGENT = TEST_USERS["aog_desk_agent_headers"]
WAREHOUSE = TEST_USERS["warehouse_operator_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]
ADJUSTER = TEST_USERS["warranty_adjuster_headers"]
APPROVER = TEST_USERS["warranty_approver_headers"]
OPS = TEST_USERS["platform_ops_headers"]


# ─── Tier 0: single-entity creation ────────────────────

def create_customer(**overrides):
    res = api_client.create_customer(create_customer_payload(**overrides), FINANCE)
    return get_success_data(res)


def create_part(**overrides):
    res = api_client.create_part(create_part_payload(**overrides), WAREHOUSE)
    return get_success_data(res)


def create_unit(part_id, **overrides):
    res = api_client.create_inventory_unit(
        create_inventory_unit_payload(part_id, **overrides), WAREHOUSE
    )
    return get_success_data(res)


def create_aog_request(customer_id, part_id, **overrides):
    res = api_client.create_aog_request(
        create_aog_request_payload(customer_id, part_id, **overrides), AGENT
    )
    return get_success_data(res)


def create_quote(aog_request_id, customer_id, lines, **overrides):
    res = api_client.create_quote(
        create_quote_payload(aog_request_id, customer_id, lines, **overrides), AGENT
    )
    return get_success_data(res)


def create_loan(customer_id, unit_id, **overrides):
    res = api_client.create_loan(
        create_loan_payload(customer_id, unit_id, **overrides), AGENT
    )
    return get_success_data(res)


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, OPS))


def run_sweeps():
    return get_success_data(api_client.run_sweeps(OPS))


# ─── Tier 1: quote lifecycle ───────────────────────────

def issue_quote(quote_id):
    """DRAFT -> ISSUED. Returns the issued quote (version is the OCC handle)."""
    return get_success_data(api_client.issue_quote(quote_id, AGENT))


def accept_quote(quote_id, customer_id, expected_quote_version):
    """ISSUED -> ACCEPTED as the owning customer contact."""
    res = api_client.accept_quote(
        quote_id,
        {"expected_quote_version": expected_quote_version},
        make_customer_headers(customer_id),
    )
    return get_success_data(res)


def get_order_for_quote(quote_id):
    data, meta = validate_paginated(
        api_client.list_orders(AGENT, params={"quote_id": quote_id})
    )
    assert len(data) == 1, f"Setup failed: expected 1 order for quote {quote_id}"
    return data[0]


def get_order_lines(order_id):
    data, meta = validate_paginated(
        api_client.list_order_lines(AGENT, params={"order_id": order_id})
    )
    return data


def get_core_return_for_line(line_id):
    data, meta = validate_paginated(
        api_client.list_core_returns(AGENT, params={"order_line_id": line_id})
    )
    assert len(data) == 1, f"Setup failed: expected 1 core return for line {line_id}"
    return data[0]


# ─── Tier 2/3: full order chains ───────────────────────

def setup_issued_quote(customer_name="QuoteAir", credit_limit_cents=None,
                       part_overrides=None, unit_overrides=None,
                       aog_overrides=None, line_overrides=None,
                       quote_overrides=None, with_unit=False, source_search=False):
    """
    Customer + part (+ optional unit) + OPEN request + DRAFT quote + issue.
    Returns dict of context: customer, part, unit, aog, quote (ISSUED).
    """
    credit = credit_limit_cents if credit_limit_cents is not None else TEST_DEFAULTS["CREDIT_LIMIT"]
    customer = create_customer(name=customer_name, credit_limit_cents=credit)
    part = create_part(**(part_overrides or {}))
    unit = create_unit(part["id"], **(unit_overrides or {})) if with_unit else None
    aog = create_aog_request(customer["id"], part["id"], **(aog_overrides or {}))
    if source_search:
        get_success_data(api_client.source_search(aog["id"], AGENT))
        aog = get_success_data(api_client.get_aog_request(aog["id"], AGENT))
    line = make_quote_line(part["id"], **(line_overrides or {}))
    quote = create_quote(aog["id"], customer["id"], [line], **(quote_overrides or {}))
    quote = issue_quote(quote["id"])
    return {
        "customer": customer, "part": part, "unit": unit,
        "aog": aog, "quote": quote,
    }


def accept_quote_and_get_order(ctx):
    """Accept the issued quote in ctx; adds 'order' and 'lines' to ctx."""
    accepted = accept_quote(
        ctx["quote"]["id"], ctx["customer"]["id"], ctx["quote"]["version"]
    )
    ctx["quote"] = accepted
    ctx["order"] = get_order_for_quote(ctx["quote"]["id"])
    ctx["lines"] = get_order_lines(ctx["order"]["id"])
    return ctx


def allocate_all_lines(ctx, unit_ids=None):
    """Allocate every PENDING line. unit_ids: optional list aligned with lines."""
    allocated = []
    for i, line in enumerate(ctx["lines"]):
        payload = {}
        if unit_ids is not None:
            payload["unit_id"] = unit_ids[i]
        res = api_client.allocate_order_line(line["id"], payload, WAREHOUSE)
        allocated.append(get_success_data(res))
    ctx["lines"] = allocated
    return ctx


def clear_order_compliance(ctx, decision="CLEARED", decision_memo=None):
    payload = {"decision": decision}
    if decision_memo is not None:
        payload["decision_memo"] = decision_memo
    ctx["order"] = get_success_data(
        api_client.post_compliance_decision(ctx["order"]["id"], payload, COMPLIANCE)
    )
    return ctx


def ship_tender_deliver(ctx, shipment_overrides=None, tender_payload=None):
    """Create the order's shipment, tender it, deliver it. Adds 'shipment'."""
    shipment = get_success_data(api_client.create_shipment(
        create_shipment_payload(ctx["order"]["id"], **(shipment_overrides or {})),
        WAREHOUSE,
    ))
    get_success_data(api_client.tender_shipment(shipment["id"], tender_payload or {}, WAREHOUSE))
    ctx["shipment"] = get_success_data(
        api_client.deliver_shipment(shipment["id"], WAREHOUSE)
    )
    return ctx


def setup_delivered_order(sale_type="OUTRIGHT", customer_name="DelivAir",
                          credit_limit_cents=None, part_overrides=None,
                          unit_overrides=None, aog_overrides=None,
                          line_overrides=None, quote_overrides=None,
                          shipment_overrides=None, tender_payload=None,
                          source_search=True):
    """
    Full chain: customer -> part -> unit -> AOG request -> (source search) ->
    quote -> issue -> accept -> allocate -> compliance CLEARED -> shipment ->
    tender -> deliver.

    Returns context dict with customer, part, unit, aog, quote, order, lines,
    shipment. For EXCHANGE lines also adds 'core_return'.
    """
    line_cfg = {"sale_type": sale_type}
    if sale_type == "EXCHANGE":
        line_cfg.setdefault("condition_required", "OVERHAULED")
    line_cfg.update(line_overrides or {})

    unit_cfg = {}
    if sale_type == "EXCHANGE":
        unit_cfg.setdefault("condition", "OVERHAULED")
        unit_cfg.setdefault("trace_doc_level", "DUAL_RELEASE")
    unit_cfg.update(unit_overrides or {})

    aog_cfg = {}
    if sale_type == "EXCHANGE":
        aog_cfg.setdefault("condition_acceptable", ["OVERHAULED"])
    aog_cfg.update(aog_overrides or {})

    part_cfg = {}
    if sale_type in ("EXCHANGE", "LOAN", "LEASE"):
        part_cfg.setdefault("rotable", True)
        part_cfg.setdefault("core_value_cents", 500_000)
    part_cfg.update(part_overrides or {})

    ctx = setup_issued_quote(
        customer_name=customer_name,
        credit_limit_cents=credit_limit_cents,
        part_overrides=part_cfg,
        unit_overrides=unit_cfg,
        aog_overrides=aog_cfg,
        line_overrides=line_cfg,
        quote_overrides=quote_overrides,
        with_unit=True,
        source_search=source_search,
    )
    accept_quote_and_get_order(ctx)
    allocate_all_lines(ctx, unit_ids=[ctx["unit"]["id"]] * len(ctx["lines"]))
    clear_order_compliance(ctx)
    ship_tender_deliver(ctx, shipment_overrides, tender_payload)

    if sale_type == "EXCHANGE":
        ctx["core_return"] = get_core_return_for_line(ctx["lines"][0]["id"])
    return ctx


def setup_delivered_multi_line_order(num_lines=2, line_total_each=20_000,
                                     customer_name="MultiAir", warranty_months=12):
    """
    Delivered order whose single quote line of quantity N explodes into N
    per-unit order lines, each allocated to its own unit.
    Returns ctx with 'lines' (N rows) and 'units' (N rows).
    """
    customer = create_customer(name=customer_name)
    part = create_part(list_price_cents=line_total_each, warranty_months=warranty_months)
    units = [create_unit(part["id"]) for _ in range(num_lines)]
    aog = create_aog_request(customer["id"], part["id"], quantity=num_lines)
    line = make_quote_line(
        part["id"], quantity=num_lines, unit_price_cents=line_total_each,
    )
    quote = create_quote(aog["id"], customer["id"], [line])
    quote = issue_quote(quote["id"])
    ctx = {"customer": customer, "part": part, "aog": aog, "quote": quote,
           "units": units, "unit": units[0]}
    accept_quote_and_get_order(ctx)
    allocate_all_lines(ctx, unit_ids=[u["id"] for u in units])
    clear_order_compliance(ctx)
    ship_tender_deliver(ctx)
    return ctx
