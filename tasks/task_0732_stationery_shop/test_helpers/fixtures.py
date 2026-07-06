"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() from framework (lenient validator) so setup failures
produce clear "setup failed" errors, not confusing assertion failures.

Every fixture that creates an entity_backed:Customer or entity_backed:Designer
entity threads the entity's id into ownership-gated calls via make_customer_headers
or make_designer_headers.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload,
    create_designer_payload,
    create_paper_stock_payload,
    create_finish_option_payload,
    create_event_package_payload,
    create_design_payload,
    create_order_payload,
    create_line_item_payload,
    create_addressing_job_payload,
    create_initial_proof_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_designer_headers,
)


# ─── Tier 0: Primitive constructors ─────────────────────

def create_customer(email: str = None, **overrides):
    """Create a fresh Customer. Returns the customer dict."""
    admin = TEST_USERS["shop_admin_headers"]
    payload = create_customer_payload(**overrides)
    if email is not None:
        payload["email"] = email
    return get_success_data(api_client.create_customer(payload, admin))


def create_designer(full_name: str = "Test Designer", active: bool = True):
    """Create a Designer."""
    admin = TEST_USERS["shop_admin_headers"]
    payload = create_designer_payload(full_name=full_name, active=active)
    return get_success_data(api_client.create_designer(payload, admin))


def create_paper_stock(base_price_cents: int = 500, lead_days: int = 7,
                      name: str = "Ivory Cotton", **overrides):
    admin = TEST_USERS["shop_admin_headers"]
    payload = create_paper_stock_payload(
        base_price_cents=base_price_cents, lead_days=lead_days, name=name, **overrides
    )
    return get_success_data(api_client.create_paper_stock(payload, admin))


def create_finish_option(surcharge_cents: int = 100, additional_lead_days: int = 5,
                        name: str = "Gold Foil", **overrides):
    admin = TEST_USERS["shop_admin_headers"]
    payload = create_finish_option_payload(
        surcharge_cents=surcharge_cents,
        additional_lead_days=additional_lead_days,
        name=name,
        **overrides,
    )
    return get_success_data(api_client.create_finish_option(payload, admin))


def create_event_package(deposit_pct: float = 0.5, min_qty: int = 50,
                         proof_expiry_days: int = 14,
                         package_type: str = "WEDDING",
                         name: str = "Wedding Suite Std",
                         **overrides):
    admin = TEST_USERS["shop_admin_headers"]
    payload = create_event_package_payload(
        deposit_pct=deposit_pct, min_qty=min_qty, proof_expiry_days=proof_expiry_days,
        package_type=package_type, name=name, **overrides,
    )
    return get_success_data(api_client.create_event_package(payload, admin))


def set_clock(iso_ts: str):
    admin = TEST_USERS["shop_admin_headers"]
    return get_success_data(api_client.set_clock(iso_ts, admin))


# ─── Tier 1: Catalog bundle ─────────────────────────────

def setup_standard_catalog(paper_base_price_cents: int = 500, paper_lead_days: int = 7,
                           finish_surcharge_cents: int = 100,
                           finish_additional_lead_days: int = 5,
                           deposit_pct: float = 0.5, min_qty: int = 50,
                           proof_expiry_days: int = 14):
    """Create the standard bundle: paper stock + finish option + wedding event package.
    Returns (paper_stock, finish_option, event_package).
    """
    paper = create_paper_stock(paper_base_price_cents, paper_lead_days)
    finish = create_finish_option(finish_surcharge_cents, finish_additional_lead_days)
    package = create_event_package(deposit_pct, min_qty, proof_expiry_days)
    return paper, finish, package


# ─── Tier 2: Design + Order + LineItem ──────────────────

def create_design_for(customer: dict, paper: dict, finish: dict, package: dict):
    """Create a Design as the given Customer. Threads the real customer id
    into the acting Customer role headers."""
    cust_headers = make_customer_headers(customer["id"])
    payload = create_design_payload(
        customer_id=customer["id"],
        event_package_id=package["id"],
        paper_stock_id=paper["id"],
        finish_option_id=finish["id"],
    )
    return get_success_data(api_client.create_design(payload, cust_headers))


def create_cart_order_for(customer: dict, design: dict, **overrides):
    """Create a new Order in CART state (POST /orders) as the customer."""
    cust_headers = make_customer_headers(customer["id"])
    payload = create_order_payload(customer["id"], design["id"], **overrides)
    return get_success_data(api_client.create_order(payload, cust_headers))


def add_line_item_to_cart(customer: dict, order: dict, paper: dict, finish: dict,
                          quantity: int = 150):
    """Add a line item to a CART order. Returns (line_item, refreshed_order_version)."""
    cust_headers = make_customer_headers(customer["id"])
    payload = create_line_item_payload(
        paper_stock_id=paper["id"],
        finish_option_id=finish["id"],
        quantity=quantity,
        expected_order_version=order["version"],
    )
    line_item = get_success_data(api_client.add_line_item(order["id"], payload, cust_headers))
    # Re-read order to get updated version
    refreshed = get_success_data(api_client.get_order(order["id"], cust_headers))
    return line_item, refreshed


# ─── Tier 3: Confirmed / Deposit-paid ───────────────────

def setup_cart_order_with_line(customer: dict = None, quantity: int = 150,
                               paper_base_price_cents: int = 500,
                               paper_lead_days: int = 7,
                               finish_surcharge_cents: int = 100,
                               finish_additional_lead_days: int = 5,
                               deposit_pct: float = 0.5, min_qty: int = 50,
                               proof_expiry_days: int = 14):
    """End-state: Order in CART with one LineItem. Returns dict of pieces.

    keys: customer, paper, finish, package, design, order (fresh), line_item
    """
    if customer is None:
        customer = create_customer()
    paper, finish, package = setup_standard_catalog(
        paper_base_price_cents=paper_base_price_cents,
        paper_lead_days=paper_lead_days,
        finish_surcharge_cents=finish_surcharge_cents,
        finish_additional_lead_days=finish_additional_lead_days,
        deposit_pct=deposit_pct,
        min_qty=min_qty,
        proof_expiry_days=proof_expiry_days,
    )
    design = create_design_for(customer, paper, finish, package)
    order = create_cart_order_for(customer, design)
    line_item, order = add_line_item_to_cart(customer, order, paper, finish, quantity=quantity)
    return {
        "customer": customer, "paper": paper, "finish": finish,
        "package": package, "design": design, "order": order, "line_item": line_item,
    }


def confirm_order(customer: dict, order: dict):
    """Confirm order (CART -> DEPOSIT_PENDING). Returns the confirmed order."""
    cust_headers = make_customer_headers(customer["id"])
    return get_success_data(api_client.confirm_order(order["id"], cust_headers))


def simulate_deposit_full(order: dict):
    """ShopAdmin simulates the exact deposit payment. Returns the updated order."""
    admin = TEST_USERS["shop_admin_headers"]
    return get_success_data(api_client.simulate_payment({
        "order_id": order["id"],
        "amount_cents": order["deposit_due_cents"],
        "outcome": "SUCCEEDED",
    }, admin))


def setup_deposit_pending(quantity: int = 150, addressing_qty: int = None):
    """Order in DEPOSIT_PENDING, deposit NOT yet paid. Optional addressing job.

    Returns dict: customer, paper, finish, package, design, order (DEPOSIT_PENDING)
    """
    bundle = setup_cart_order_with_line(quantity=quantity)
    if addressing_qty is not None:
        cust_headers = make_customer_headers(bundle["customer"]["id"])
        get_success_data(api_client.create_addressing_job(
            bundle["order"]["id"],
            create_addressing_job_payload(quantity=addressing_qty),
            cust_headers,
        ))
    bundle["order"] = confirm_order(bundle["customer"], bundle["order"])
    return bundle


def setup_deposit_paid_no_proof(quantity: int = 150, addressing_qty: int = None):
    """Order in DEPOSIT_PENDING with deposit fully paid. No proof yet."""
    bundle = setup_deposit_pending(quantity=quantity, addressing_qty=addressing_qty)
    bundle["order"] = simulate_deposit_full(bundle["order"])
    return bundle


# ─── Tier 4: Proof lifecycle ────────────────────────────

def create_and_submit_proof(designer: dict, design: dict):
    """Create initial proof (DRAFT), then submit to SUBMITTED. Returns proof."""
    des_headers = make_designer_headers(designer["id"])
    proof = get_success_data(api_client.create_proof(
        design["id"], create_initial_proof_payload(designer["id"]), des_headers,
    ))
    proof = get_success_data(api_client.submit_proof(proof["id"], des_headers))
    return proof


def create_draft_proof(designer: dict, design: dict):
    """Create initial proof only (DRAFT, revision 0)."""
    des_headers = make_designer_headers(designer["id"])
    return get_success_data(api_client.create_proof(
        design["id"], create_initial_proof_payload(designer["id"]), des_headers,
    ))


def approve_proof(customer: dict, proof: dict):
    """Customer approves the proof."""
    cust_headers = make_customer_headers(customer["id"])
    return get_success_data(api_client.approve_proof(proof["id"], cust_headers))


def setup_deposit_pending_with_submitted_proof(quantity: int = 150,
                                               addressing_qty: int = None,
                                               deposit_paid: bool = False):
    """DEPOSIT_PENDING order + Proof in SUBMITTED. Optional deposit paid."""
    bundle = setup_deposit_pending(quantity=quantity, addressing_qty=addressing_qty)
    if deposit_paid:
        bundle["order"] = simulate_deposit_full(bundle["order"])
    bundle["designer"] = create_designer(full_name="Test Designer Alpha")
    bundle["proof"] = create_and_submit_proof(bundle["designer"], bundle["design"])
    return bundle


def setup_in_production_order(quantity: int = 150, addressing_qty: int = None):
    """Order in IN_PRODUCTION: deposit paid, proof approved.
    Returns bundle with keys: customer, paper, finish, package, design, order,
    designer, proof (APPROVED), work_order.
    """
    bundle = setup_deposit_pending_with_submitted_proof(
        quantity=quantity, addressing_qty=addressing_qty, deposit_paid=True,
    )
    bundle["proof"] = approve_proof(bundle["customer"], bundle["proof"])
    admin = TEST_USERS["shop_admin_headers"]
    # Refresh order (should have auto-transitioned to IN_PRODUCTION)
    bundle["order"] = get_success_data(api_client.get_order(bundle["order"]["id"], admin))
    # Fetch work order
    wo_list_resp = api_client.list_order_work_orders(bundle["order"]["id"], admin)
    wo_list = get_success_data(wo_list_resp)
    if isinstance(wo_list, list) and wo_list:
        bundle["work_order"] = wo_list[0]
    else:
        bundle["work_order"] = None
    return bundle


# ─── Tier 5: Production advance / Shipment ──────────────

def advance_production(work_order: dict, new_status: str, press_id: str = None,
                       press_slot_start: str = None, press_slot_end: str = None):
    admin = TEST_USERS["shop_admin_headers"]
    payload = {"new_status": new_status}
    if press_id is not None:
        payload["press_id"] = press_id
    if press_slot_start is not None:
        payload["press_slot_start"] = press_slot_start
    if press_slot_end is not None:
        payload["press_slot_end"] = press_slot_end
    return get_success_data(api_client.advance_production(work_order["id"], payload, admin))


def advance_addressing(work_order: dict, new_status: str):
    admin = TEST_USERS["shop_admin_headers"]
    return get_success_data(
        api_client.advance_addressing(work_order["id"], {"new_status": new_status}, admin)
    )


def run_production_to_completed(work_order: dict, press_id: str = "PRESS_A",
                                press_slot_start: str = "2026-04-05T09:00:00Z",
                                press_slot_end: str = "2026-04-05T13:00:00Z"):
    """Walk production dimension NOT_STARTED -> PRINTING -> FINISHING -> COMPLETED."""
    advance_production(work_order, "PRINTING",
                       press_id=press_id,
                       press_slot_start=press_slot_start,
                       press_slot_end=press_slot_end)
    advance_production(work_order, "FINISHING")
    return advance_production(work_order, "COMPLETED")


def setup_ready_to_ship(quantity: int = 150, press_id: str = "PRESS_A",
                        press_slot_start: str = "2026-04-05T09:00:00Z",
                        press_slot_end: str = "2026-04-05T13:00:00Z"):
    """Order in READY_TO_SHIP with a spawned Shipment (no addressing job path).
    Returns bundle with keys: (all IN_PRODUCTION keys) + shipment.
    """
    bundle = setup_in_production_order(quantity=quantity)
    run_production_to_completed(
        bundle["work_order"], press_id=press_id,
        press_slot_start=press_slot_start, press_slot_end=press_slot_end,
    )
    admin = TEST_USERS["shop_admin_headers"]
    bundle["order"] = get_success_data(api_client.get_order(bundle["order"]["id"], admin))
    ship_list = get_success_data(api_client.list_order_shipments(bundle["order"]["id"], admin))
    bundle["shipment"] = ship_list[0] if ship_list else None
    return bundle


def setup_delivered_order(quantity: int = 150):
    """Full pipeline through DELIVERED. Returns bundle with keys as above + shipment DELIVERED."""
    bundle = setup_ready_to_ship(quantity=quantity)
    admin = TEST_USERS["shop_admin_headers"]
    get_success_data(api_client.dispatch_shipment(bundle["shipment"]["id"], admin))
    bundle["shipment"] = get_success_data(
        api_client.mark_shipment_delivered(bundle["shipment"]["id"], admin)
    )
    bundle["order"] = get_success_data(api_client.get_order(bundle["order"]["id"], admin))
    return bundle
