"""Composite setup helpers for multi-step test prerequisites.

Each helper drives an empty DB to a precondition using only PRD-declared endpoints.
Uses get_success_data() (lenient validator) so setup failures produce clear
"Setup failed" errors rather than confusing assertion failures. The harness restarts
the server (empty DB) before every test, so every helper builds state from scratch.

Staff roles are opaque (PRD §2.1) so shared-constant headers are used throughout;
the Customer role is entity_backed and uses make_customer_headers() with the real id.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload,
    create_inventory_item_payload,
    create_workbench_payload,
    create_appraisal_payload,
    create_custom_order_payload,
    create_repair_ticket_payload,
    create_layaway_plan_payload,
    create_trade_in_payload,
    create_special_order_payload,
    create_payment_payload,
    create_warranty_claim_payload,
    create_ledger_entry_payload,
)
from .test_users import TEST_USERS

SA = TEST_USERS["sales_associate_headers"]
GS = TEST_USERS["goldsmith_headers"]
SM = TEST_USERS["store_manager_headers"]


# ─── Tier 0: Standing records ────────────────────────────────────────────────
def create_customer(**overrides):
    """Create a Customer (ACTIVE, balance 0). Returns the customer dict."""
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), SA))


def create_inventory_item(**overrides):
    """Create an InventoryItem (IN_STOCK). Returns the item dict."""
    return get_success_data(
        api_client.create_inventory_item(create_inventory_item_payload(**overrides), SM)
    )


def create_workbench(**overrides):
    """Create a Workbench (ACTIVE). Returns the workbench dict."""
    return get_success_data(api_client.create_workbench(create_workbench_payload(**overrides), SM))


def suspend_customer(customer):
    """Suspend an ACTIVE customer. Returns the updated (SUSPENDED) customer dict."""
    return get_success_data(
        api_client.suspend_customer(customer["id"], {"expected_version": customer["version"]}, SM)
    )


# ─── Tier 1/3: Custom-order lifecycle progressions ───────────────────────────
def create_custom_order(customer_id=None, **overrides):
    """Create a DRAFT custom order. Creates a customer if none supplied.
    Returns (order, customer_id)."""
    if customer_id is None:
        customer_id = create_customer()["id"]
    order = get_success_data(
        api_client.create_custom_order(create_custom_order_payload(customer_id, **overrides), SA)
    )
    return order, customer_id


def create_quoted_custom_order(customer_id=None, **overrides):
    """DRAFT -> QUOTED. Returns (order, customer_id)."""
    order, customer_id = create_custom_order(customer_id, **overrides)
    order = get_success_data(
        api_client.quote_custom_order(order["id"], {"expected_version": order["version"]}, SA)
    )
    return order, customer_id


def pay_custom_order_deposit(order, amount_cents):
    """Record a CUSTOM_ORDER payment of amount_cents (may auto-advance to DEPOSIT_PAID).
    Returns the latest order dict."""
    get_success_data(
        api_client.create_payment(
            create_payment_payload(
                "CUSTOM_ORDER", custom_order_id=order["id"], amount_cents=amount_cents
            ),
            SA,
        )
    )
    return get_success_data(api_client.get_custom_order(order["id"], SA))


def create_deposit_paid_custom_order(customer_id=None, deposit_cents=None, **overrides):
    """DRAFT -> QUOTED -> (pay deposit) -> DEPOSIT_PAID. Returns (order, customer_id).
    If deposit_cents is None, pays exactly deposit_required_cents."""
    order, customer_id = create_quoted_custom_order(customer_id, **overrides)
    pay = deposit_cents if deposit_cents is not None else order["deposit_required_cents"]
    order = pay_custom_order_deposit(order, pay)
    return order, customer_id


def create_design_review_custom_order(customer_id=None, deposit_cents=None, **overrides):
    """Drive to DESIGN_REVIEW (deposit paid, design started, submitted for review).
    Returns (order, customer_id)."""
    order, customer_id = create_deposit_paid_custom_order(customer_id, deposit_cents, **overrides)
    order = get_success_data(
        api_client.start_design_custom_order(order["id"], {"expected_version": order["version"]}, GS)
    )
    order = get_success_data(
        api_client.submit_review_custom_order(order["id"], {"expected_version": order["version"]}, GS)
    )
    return order, customer_id


def create_design_review_with_revisions(revision_count, customer_id=None,
                                        deposit_cents=None, **overrides):
    """Drive to DESIGN_REVIEW after performing `revision_count` revision loops
    (DESIGN_REVIEW -> IN_DESIGN -> DESIGN_REVIEW). Returns (order, customer_id)."""
    order, customer_id = create_design_review_custom_order(customer_id, deposit_cents, **overrides)
    for _ in range(revision_count):
        order = get_success_data(
            api_client.request_revision_custom_order(
                order["id"], {"expected_version": order["version"]}, SA
            )
        )
        order = get_success_data(
            api_client.submit_review_custom_order(
                order["id"], {"expected_version": order["version"]}, GS
            )
        )
    return order, customer_id


def create_approved_custom_order(line_items, customer_id=None, deposit_cents=None, **overrides):
    """Drive to APPROVED with the supplied line_items. Returns (order, customer_id)."""
    order, customer_id = create_design_review_custom_order(customer_id, deposit_cents, **overrides)
    order = get_success_data(
        api_client.approve_design_custom_order(
            order["id"], {"line_items": line_items, "expected_version": order["version"]}, SA
        )
    )
    return order, customer_id


def create_in_production_custom_order(line_items, customer_id=None,
                                      deposit_cents=None, **overrides):
    """Drive to IN_PRODUCTION. Returns (order, customer_id)."""
    order, customer_id = create_approved_custom_order(
        line_items, customer_id, deposit_cents, **overrides
    )
    order = get_success_data(
        api_client.start_production_custom_order(
            order["id"], {"expected_version": order["version"]}, GS
        )
    )
    return order, customer_id


def create_ready_custom_order(line_items, customer_id=None, deposit_cents=None, **overrides):
    """Drive through complete-production to READY (final_total_cents computed).
    Returns (order, customer_id)."""
    order, customer_id = create_in_production_custom_order(
        line_items, customer_id, deposit_cents, **overrides
    )
    order = get_success_data(
        api_client.complete_production_custom_order(
            order["id"], {"expected_version": order["version"]}, GS
        )
    )
    return order, customer_id


# ─── Tier 3: Repair-ticket lifecycle progressions ────────────────────────────
def create_repair_ticket(customer_id=None, **overrides):
    """Create an INTAKE repair ticket. Returns (ticket, customer_id)."""
    if customer_id is None:
        customer_id = create_customer()["id"]
    ticket = get_success_data(
        api_client.create_repair_ticket(create_repair_ticket_payload(customer_id, **overrides), SA)
    )
    return ticket, customer_id


def create_assessed_repair_ticket(parts_cents, labor_cents, customer_id=None, **overrides):
    """INTAKE -> ASSESSED with the supplied parts/labor. Returns (ticket, customer_id)."""
    ticket, customer_id = create_repair_ticket(customer_id, **overrides)
    ticket = get_success_data(
        api_client.assess_repair_ticket(
            ticket["id"],
            {"parts_cents": parts_cents, "labor_cents": labor_cents,
             "expected_version": ticket["version"]},
            GS,
        )
    )
    return ticket, customer_id


def create_in_repair_ticket_via_parts(parts_cents, labor_cents, customer_id=None, **overrides):
    """ASSESSED -> AWAITING_PARTS -> IN_REPAIR (parts branch). Returns (ticket, customer_id)."""
    ticket, customer_id = create_assessed_repair_ticket(
        parts_cents, labor_cents, customer_id, **overrides
    )
    ticket = get_success_data(
        api_client.order_parts_repair_ticket(ticket["id"], {"expected_version": ticket["version"]}, GS)
    )
    ticket = get_success_data(
        api_client.parts_received_repair_ticket(
            ticket["id"], {"expected_version": ticket["version"]}, GS
        )
    )
    return ticket, customer_id


def drive_repair_ticket_to_qc_via_parts(parts_cents, labor_cents, customer_id=None, **overrides):
    """Through the parts fork to QC. Returns (ticket, customer_id)."""
    ticket, customer_id = create_in_repair_ticket_via_parts(
        parts_cents, labor_cents, customer_id, **overrides
    )
    ticket = get_success_data(
        api_client.submit_qc_repair_ticket(ticket["id"], {"expected_version": ticket["version"]}, GS)
    )
    return ticket, customer_id


def drive_repair_ticket_to_qc_no_parts(parts_cents, labor_cents, customer_id=None, **overrides):
    """ASSESSED -> IN_REPAIR (no-parts branch) -> QC. Returns (ticket, customer_id)."""
    ticket, customer_id = create_assessed_repair_ticket(
        parts_cents, labor_cents, customer_id, **overrides
    )
    ticket = get_success_data(
        api_client.start_repair_repair_ticket(
            ticket["id"], {"expected_version": ticket["version"]}, GS
        )
    )
    ticket = get_success_data(
        api_client.submit_qc_repair_ticket(ticket["id"], {"expected_version": ticket["version"]}, GS)
    )
    return ticket, customer_id


def drive_repair_ticket_to_picked_up_no_parts(parts_cents, labor_cents,
                                              customer_id=None, **overrides):
    """Full no-parts lifecycle to PICKED_UP. Returns (ticket, customer_id)."""
    ticket, customer_id = drive_repair_ticket_to_qc_no_parts(
        parts_cents, labor_cents, customer_id, **overrides
    )
    ticket = get_success_data(
        api_client.pass_qc_repair_ticket(ticket["id"], {"expected_version": ticket["version"]}, SM)
    )
    ticket = get_success_data(
        api_client.pickup_repair_ticket(ticket["id"], {"expected_version": ticket["version"]}, SA)
    )
    return ticket, customer_id


def schedule_repair_ticket(ticket, bench_id, start, end):
    """Reserve a bench window on a ticket. Returns the updated ticket dict."""
    return get_success_data(
        api_client.schedule_repair_ticket(
            ticket["id"],
            {"bench_id": bench_id, "scheduled_start": start, "scheduled_end": end,
             "expected_version": ticket["version"]},
            GS,
        )
    )


# ─── Tier 1/4: Layaway plan progressions ─────────────────────────────────────
def create_layaway_plan(customer_id=None, inventory_item_id=None,
                        item_price_cents=600_000, installment_count=4):
    """Create a PENDING layaway plan. Creates customer + IN_STOCK item if needed.
    Returns (plan, customer_id, item)."""
    if customer_id is None:
        customer_id = create_customer()["id"]
    item = (
        {"id": inventory_item_id}
        if inventory_item_id is not None
        else create_inventory_item(list_price_cents=item_price_cents)
    )
    plan = get_success_data(
        api_client.create_layaway_plan(
            create_layaway_plan_payload(customer_id, item["id"], installment_count=installment_count),
            SA,
        )
    )
    return plan, customer_id, item


def create_active_layaway_plan(customer_id=None, item_price_cents=600_000, installment_count=4):
    """PENDING -> ACTIVE (item reserved, down payment collected). Returns (plan, customer_id, item)."""
    plan, customer_id, item = create_layaway_plan(
        customer_id, None, item_price_cents, installment_count
    )
    plan = get_success_data(
        api_client.activate_layaway_plan(
            plan["id"], {"expected_inventory_item_version": item["version"]}, SA
        )
    )
    return plan, customer_id, item


def pay_layaway_installment(plan, amount_cents):
    """Record a LAYAWAY payment. Returns the latest plan dict."""
    get_success_data(
        api_client.create_payment(
            create_payment_payload("LAYAWAY", layaway_plan_id=plan["id"], amount_cents=amount_cents),
            SA,
        )
    )
    return get_success_data(api_client.get_layaway_plan(plan["id"], SA))


# ─── Tier 1: Trade-in offers ─────────────────────────────────────────────────
def create_trade_in_offer(customer_id=None, **overrides):
    """Create an OFFERED trade-in. Creates a customer if needed. Returns (offer, customer_id)."""
    if customer_id is None:
        customer_id = create_customer()["id"]
    offer = get_success_data(
        api_client.create_trade_in(create_trade_in_payload(customer_id, **overrides), SA)
    )
    return offer, customer_id


def create_accepted_trade_in(customer_id=None, **overrides):
    """Create then ACCEPT a trade-in (posts CREDIT to store credit). Returns (offer, customer_id)."""
    offer, customer_id = create_trade_in_offer(customer_id, **overrides)
    offer = get_success_data(
        api_client.accept_trade_in(offer["id"], {"expected_version": offer["version"]}, SM)
    )
    return offer, customer_id


# ─── Tier 1: Special orders ──────────────────────────────────────────────────
def create_special_order(customer_id=None, **overrides):
    """Create a REQUESTED special order. Creates a customer if needed.
    Returns (order, customer_id)."""
    if customer_id is None:
        customer_id = create_customer()["id"]
    order = get_success_data(
        api_client.create_special_order(create_special_order_payload(customer_id, **overrides), SA)
    )
    return order, customer_id


def create_delivered_special_order_item(customer_id=None, quoted_price_cents=300_000,
                                        sku="SO-ITEM", metal_karat="K18"):
    """Place -> receive -> deliver a special order; the created item ends SOLD.
    Returns (order, received_item_id)."""
    order, customer_id = create_special_order(customer_id, quoted_price_cents=quoted_price_cents)
    # Fund the deposit so place() succeeds.
    get_success_data(
        api_client.create_payment(
            create_payment_payload(
                "SPECIAL_ORDER", special_order_id=order["id"],
                amount_cents=order["deposit_required_cents"],
            ),
            SA,
        )
    )
    order = get_success_data(api_client.get_special_order(order["id"], SA))
    order = get_success_data(
        api_client.place_special_order(order["id"], {"expected_version": order["version"]}, SA)
    )
    order = get_success_data(
        api_client.receive_special_order(
            order["id"], {"sku": sku, "metal_karat": metal_karat,
                          "expected_version": order["version"]},
            SA,
        )
    )
    received_item_id = order["received_inventory_item_id"]
    order = get_success_data(
        api_client.deliver_special_order(order["id"], {"expected_version": order["version"]}, SA)
    )
    return order, received_item_id


# ─── Tier 1/3: Appraisals ────────────────────────────────────────────────────
def create_draft_appraisal(inventory_item_id=None, item=None, **overrides):
    """Create a DRAFT appraisal. Creates an item if none supplied. Returns (appraisal, item)."""
    if item is None:
        item = create_inventory_item() if inventory_item_id is None else {"id": inventory_item_id}
    appraisal = get_success_data(
        api_client.create_appraisal(create_appraisal_payload(item["id"], **overrides), SM)
    )
    return appraisal, item


def create_finalized_appraisal(item=None, **overrides):
    """Create + finalize an appraisal on an item (sets latest_appraised_value_cents,
    assigns document_number, bumps item version). Returns (appraisal, item) with the item
    dict refreshed to its post-finalize version."""
    appraisal, item = create_draft_appraisal(item=item, **overrides)
    # Fetch the item's current version for the OCC-guarded finalize.
    item_now = get_success_data(api_client.get_inventory_item(item["id"], SM))
    appraisal = get_success_data(
        api_client.finalize_appraisal(
            appraisal["id"], {"expected_inventory_item_version": item_now["version"]}, SM
        )
    )
    item_after = get_success_data(api_client.get_inventory_item(item["id"], SM))
    return appraisal, item_after


# ─── Tier 3: Warranty claims + spawned repair ────────────────────────────────
def create_submitted_warranty_claim(inventory_item_id=None, customer_id=None,
                                    item=None, **overrides):
    """Create a SUBMITTED warranty claim. Returns (claim, customer_id, item_id)."""
    if customer_id is None:
        customer_id = create_customer()["id"]
    if item is not None:
        item_id = item["id"]
    elif inventory_item_id is not None:
        item_id = inventory_item_id
    else:
        item_id = create_inventory_item()["id"]
    claim = get_success_data(
        api_client.create_warranty_claim(
            create_warranty_claim_payload(item_id, customer_id, **overrides), SA
        )
    )
    return claim, customer_id, item_id


def create_approved_warranty_claim(customer_id=None):
    """Item with a FINALIZED appraisal + an APPROVED warranty claim (spawns a WARRANTY
    repair ticket). Returns (claim, spawned_repair_ticket_id, customer_id, item_id)."""
    if customer_id is None:
        customer_id = create_customer()["id"]
    appraisal, item = create_finalized_appraisal()
    claim, customer_id, item_id = create_submitted_warranty_claim(
        customer_id=customer_id, item=item
    )
    claim = get_success_data(
        api_client.approve_warranty_claim(claim["id"], {"expected_version": claim["version"]}, SM)
    )
    return claim, claim["spawned_repair_ticket_id"], customer_id, item_id


def drive_spawned_warranty_ticket_to_ready(spawned_rt_id):
    """Drive a freshly spawned WARRANTY repair ticket INTAKE -> ... -> READY (no parts).
    Returns the ticket dict in READY state."""
    ticket = get_success_data(api_client.get_repair_ticket(spawned_rt_id, GS))
    ticket = get_success_data(
        api_client.assess_repair_ticket(
            ticket["id"],
            {"parts_cents": 0, "labor_cents": 0, "expected_version": ticket["version"]},
            GS,
        )
    )
    ticket = get_success_data(
        api_client.start_repair_repair_ticket(ticket["id"], {"expected_version": ticket["version"]}, GS)
    )
    ticket = get_success_data(
        api_client.submit_qc_repair_ticket(ticket["id"], {"expected_version": ticket["version"]}, GS)
    )
    ticket = get_success_data(
        api_client.pass_qc_repair_ticket(ticket["id"], {"expected_version": ticket["version"]}, SM)
    )
    return ticket


# ─── Tier 0: Ledger ──────────────────────────────────────────────────────────
def post_ledger_entry(customer_id, direction, amount_cents, reason="MANUAL_ADJUSTMENT"):
    """Post a manual ledger entry. Returns the entry dict."""
    return get_success_data(
        api_client.create_ledger_entry(
            create_ledger_entry_payload(
                customer_id, direction=direction, amount_cents=amount_cents, reason=reason
            ),
            SM,
        )
    )
