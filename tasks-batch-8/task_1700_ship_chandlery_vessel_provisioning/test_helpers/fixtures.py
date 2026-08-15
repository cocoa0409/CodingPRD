"""Composite setup helpers.

Most testable claims in this PRD require the system to be in a state that
takes 5-15 API calls to reach (an accepted order, a delivered delivery, an
issued invoice, an applied credit note). These fixtures encapsulate those
preambles so tests can focus on assertions. Every fixture builds its state
from scratch via the public endpoints — the server is restarted before every
test, so each test starts against an empty database.

Identity threading: VesselCateringOfficer and ShipAgentClerk are entity-backed
roles (PRD §2.1). After creating a VesselCall, ownership-gated calls use
make_officer_headers(vessel_call["id"]); payments use
make_clerk_headers(agent["id"]).

Shared schedule (mirrors the design index): ETA 2026-08-10T08:00:00Z, ETD
2026-08-14T12:00:00Z (exactly 100 planned hours), validity deadline
2026-08-12T00:00:00Z. The logical clock is advanced to ETA before arrive so
actual_eta == scheduled_eta and delivery-window containment math is exact.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    DEFAULT_ETA,
    DEFAULT_ETD,
    DEFAULT_VALID_UNTIL,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
)
from .factories import (
    create_catalog_item_payload,
    create_complaint_payload,
    create_delivery_payload,
    create_invoice_payload,
    create_payment_payload,
    create_quotation_payload,
    create_requisition_payload,
    create_ship_agent_payload,
    create_stock_lot_payload,
    create_vessel_call_payload,
    confirm_delivery_payload,
)
from .test_users import TEST_USERS, make_clerk_headers, make_officer_headers

OPS = TEST_USERS["ops_headers"]
SALES = TEST_USERS["sales_headers"]
WAREHOUSE = TEST_USERS["warehouse_headers"]
CUSTOMS = TEST_USERS["customs_headers"]
FINANCE = TEST_USERS["finance_headers"]


# ---------------------------------------------------------------------------
# Tier 1: leaf creators
# ---------------------------------------------------------------------------

def create_agent(**overrides):
    """Register a paying ship agent (FinanceController). Returns ShipAgent."""
    resp = api_client.create_ship_agent(create_ship_agent_payload(**overrides), FINANCE)
    return get_success_data(resp)


def create_catalog_item(**overrides):
    """Create a catalog item (ChandlerOpsManager). Returns CatalogItem."""
    resp = api_client.create_catalog_item(create_catalog_item_payload(**overrides), OPS)
    return get_success_data(resp)


def create_stock_lot(catalog_item_id, **overrides):
    """Create a stock lot (WarehouseSupervisor). Returns StockLot."""
    resp = api_client.create_stock_lot(
        create_stock_lot_payload(catalog_item_id, **overrides), WAREHOUSE,
    )
    return get_success_data(resp)


def create_vessel_call(agent_id, **overrides):
    """Register a vessel port call (ChandlerOpsManager). Returns VesselCall."""
    resp = api_client.create_vessel_call(create_vessel_call_payload(agent_id, **overrides), OPS)
    return get_success_data(resp)


def set_clock(to_iso8601):
    """Advance the logical clock (ChandlerOpsManager). Returns the response data."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, OPS)
    return get_success_data(resp)


def arrive_vessel_call(vessel_call_id):
    """Mark the vessel arrived. Returns updated VesselCall."""
    return get_success_data(api_client.arrive_vessel_call(vessel_call_id, OPS))


def customs_decision(vessel_call_id, decision):
    """Record a customs decision (PortCustomsOfficer). Returns VesselCall."""
    return get_success_data(
        api_client.customs_clearance(vessel_call_id, {"decision": decision}, CUSTOMS)
    )


# ---------------------------------------------------------------------------
# Tier 2: requisition -> submitted -> quotation -> sent
# ---------------------------------------------------------------------------

def create_submitted_requisition(vessel_call_id, catalog_item_id, requested_qty=100,
                                 allows_substitution=False):
    """Create a requisition on the call and submit it. Returns Requisition (SUBMITTED)."""
    officer = make_officer_headers(vessel_call_id)
    req = get_success_data(api_client.create_requisition(
        vessel_call_id,
        create_requisition_payload(
            catalog_item_id, requested_qty=requested_qty,
            allows_substitution=allows_substitution,
        ),
        officer,
    ))
    get_success_data(api_client.submit_requisition(req["id"], officer))
    return get_success_data(api_client.get_requisition(req["id"], officer))


def create_draft_quotation(requisition_id, catalog_item_id, qty=100, unit_price_cents=120,
                           valid_until=DEFAULT_VALID_UNTIL, line_overrides=None):
    """Draft a quotation against a SUBMITTED/QUOTED requisition. Returns Quotation (DRAFT)."""
    lines = line_overrides
    if lines is None:
        lines = [{
            "catalog_item_id": catalog_item_id,
            "qty": qty,
            "unit_price_cents": unit_price_cents,
            "is_substitution": False,
        }]
    payload = {"lines": lines, "valid_until": valid_until}
    resp = api_client.create_quotation(requisition_id, payload, SALES)
    return get_success_data(resp)


def create_sent_quotation(requisition_id, catalog_item_id, qty=100, unit_price_cents=120,
                          valid_until=DEFAULT_VALID_UNTIL, line_overrides=None):
    """Draft + send a quotation. Returns Quotation (SENT)."""
    quo = create_draft_quotation(
        requisition_id, catalog_item_id, qty=qty, unit_price_cents=unit_price_cents,
        valid_until=valid_until, line_overrides=line_overrides,
    )
    get_success_data(api_client.send_quotation(quo["id"], SALES))
    return get_success_data(api_client.get_quotation(quo["id"], SALES))


# ---------------------------------------------------------------------------
# Tier 3: accepted order (the pivotal composite)
# ---------------------------------------------------------------------------

def setup_accepted_order(
    qty=100,
    unit_price_cents=120,
    base_price_cents=None,
    agent_overrides=None,
    item_overrides=None,
    lot_overrides=None,
    call_overrides=None,
    valid_until=DEFAULT_VALID_UNTIL,
    clock_before_arrive=DEFAULT_ETA,
    clear_customs=False,
    requested_qty=None,
    allows_substitution=False,
    line_overrides=None,
    agent=None,
    item=None,
    lot=None,
):
    """Full accept flow. Returns a dict of all created entities:

        {agent, item, lot, call, requisition, quotation, order}

    Steps: agent -> item -> lot -> call -> requisition -> submit -> quotation
    -> send -> clock := ETA -> arrive -> (optional customs CLEARED) -> accept.
    The order opens OPEN x UNINVOICED with stock reserved.

    Pass existing `agent` / `item` / `lot` to share them across multiple
    orders (the lot's stock must cover every order placed against it).
    """
    if agent is None:
        agent = create_agent(**(agent_overrides or {}))
    item_kwargs = dict(item_overrides or {})
    if base_price_cents is not None:
        item_kwargs.setdefault("base_price_cents", base_price_cents)
    if item is None:
        item = create_catalog_item(**item_kwargs)
    if lot is None:
        lot = create_stock_lot(item["id"], **(lot_overrides or {}))
    call = create_vessel_call(agent["id"], **(call_overrides or {}))
    officer = make_officer_headers(call["id"])
    requisition = create_submitted_requisition(
        call["id"], item["id"],
        requested_qty=requested_qty if requested_qty is not None else qty,
        allows_substitution=allows_substitution,
    )
    quotation = create_sent_quotation(
        requisition["id"], item["id"], qty=qty, unit_price_cents=unit_price_cents,
        valid_until=valid_until, line_overrides=line_overrides,
    )
    if clock_before_arrive is not None:
        set_clock(clock_before_arrive)
    arrive_vessel_call(call["id"])
    if clear_customs:
        customs_decision(call["id"], "CLEARED")
    accept_resp = api_client.accept_quotation(quotation["id"], officer)
    order = get_success_data(accept_resp)
    return {
        "agent": agent,
        "item": item,
        "lot": lot,
        "call": call,
        "requisition": requisition,
        "quotation": quotation,
        "order": order,
        "accept_response": accept_resp,
    }


# ---------------------------------------------------------------------------
# Tier 4: delivery lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_scheduled_delivery(order_id, catalog_item_id, qty,
                              window_start=DEFAULT_WINDOW_START,
                              window_end=DEFAULT_WINDOW_END):
    """Schedule a delivery (WarehouseSupervisor). Returns Delivery (SCHEDULED)."""
    resp = api_client.create_delivery(
        order_id,
        create_delivery_payload(
            catalog_item_id, qty=qty,
            window_start=window_start, window_end=window_end,
        ),
        WAREHOUSE,
    )
    return get_success_data(resp)


def dispatch_delivery(delivery_id):
    """Dispatch a delivery. Returns Delivery (OUT_FOR_DELIVERY)."""
    return get_success_data(api_client.dispatch_delivery(delivery_id, WAREHOUSE))


def confirm_delivery(delivery_id, catalog_item_id, qty, officer_headers, clock=None):
    """Confirm receipt (VesselCateringOfficer). Returns Delivery (DELIVERED)."""
    if clock is not None:
        set_clock(clock)
    return get_success_data(api_client.confirm_delivery(
        delivery_id, confirm_delivery_payload(catalog_item_id, qty), officer_headers,
    ))


def setup_delivered_order(qty=100, unit_price_cents=120, **kwargs):
    """Accepted order + one fully confirmed delivery.

    Returns the setup_accepted_order dict extended with {delivery}.
    The order ends in fulfillment DELIVERED, payment UNINVOICED.
    """
    ctx = setup_accepted_order(qty=qty, unit_price_cents=unit_price_cents, **kwargs)
    delivery = create_scheduled_delivery(ctx["order"]["id"], ctx["item"]["id"], qty)
    dispatch_delivery(delivery["id"])
    officer = make_officer_headers(ctx["call"]["id"])
    delivery = confirm_delivery(delivery["id"], ctx["item"]["id"], qty, officer)
    ctx["delivery"] = delivery
    return ctx


def setup_invoiced_order(qty=100, unit_price_cents=120, fx_rate_to_settlement=1.0,
                         invoice_clock=None, **kwargs):
    """Delivered order + issued invoice.

    Returns the setup_delivered_order dict extended with {invoice}.
    The order ends in fulfillment DELIVERED, payment INVOICED.
    """
    ctx = setup_delivered_order(qty=qty, unit_price_cents=unit_price_cents, **kwargs)
    if invoice_clock is not None:
        set_clock(invoice_clock)
    invoice = get_success_data(api_client.create_invoice(
        ctx["order"]["id"], create_invoice_payload(fx_rate_to_settlement), FINANCE,
    ))
    ctx["invoice"] = invoice
    return ctx


# ---------------------------------------------------------------------------
# Tier 5: complaint / credit-note terminal states
# ---------------------------------------------------------------------------

def file_complaint(delivery_id, catalog_item_id, rejected_qty, officer_headers,
                   reason="DAMAGED", evidence_note="evidence"):
    """File a quality complaint. Returns QualityComplaint (SUBMITTED)."""
    return get_success_data(api_client.create_complaint(
        delivery_id,
        create_complaint_payload(
            catalog_item_id, rejected_qty, reason=reason, evidence_note=evidence_note,
        ),
        officer_headers,
    ))


def setup_accepted_credit_note(qty=100, unit_price_cents=5000, rejected_qty=10,
                               qa_user_id="qa-lead-1", **kwargs):
    """Invoiced order + complaint filed + accepted => CreditNote APPLIED.

    Returns the setup_invoiced_order dict extended with {complaint, credit_note}.
    """
    from .test_users import make_qa_headers

    ctx = setup_invoiced_order(qty=qty, unit_price_cents=unit_price_cents, **kwargs)
    officer = make_officer_headers(ctx["call"]["id"])
    complaint = file_complaint(
        ctx["delivery"]["id"], ctx["item"]["id"], rejected_qty, officer,
    )
    accepted = get_success_data(
        api_client.accept_complaint(complaint["id"], make_qa_headers(qa_user_id))
    )
    notes, _meta = list_credit_notes()
    ctx["complaint"] = accepted
    ctx["credit_note"] = notes[0]
    return ctx


def list_credit_notes(params=None):
    """List credit notes (FinanceController). Returns (list, meta)."""
    from prd_bench_local_runner.testing import validate_paginated

    return validate_paginated(api_client.list_credit_notes(FINANCE, params=params))


def pay_invoice(invoice_id, agent_id, amount_cents, currency="USD", **overrides):
    """Record a payment on an invoice as the owning agent's clerk. Returns Payment."""
    return get_success_data(api_client.create_payment(
        invoice_id,
        create_payment_payload(amount_cents, currency=currency, **overrides),
        make_clerk_headers(agent_id),
    ))


# ---------------------------------------------------------------------------
# Domain item presets (PRD-faithful shapes used across many tests)
# ---------------------------------------------------------------------------

WATER_ITEM = dict(
    name="Water 1L", category="PROVISIONS", bonded_eligible=False,
    requires_cold_chain=False, base_price_cents=120, duty_rate_pct=0,
)
WHISKY_ITEM = dict(
    name="Scotch Whisky 1L", category="BONDED", bonded_eligible=True,
    requires_cold_chain=False, base_price_cents=5000, duty_rate_pct=20,
)
FISH_ITEM = dict(
    name="Frozen Salmon 1kg", category="PROVISIONS", bonded_eligible=False,
    requires_cold_chain=True, base_price_cents=2500, duty_rate_pct=5,
)
