"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures surface as
clear "Setup step failed" errors instead of confusing assertion failures.
Every helper builds state from scratch through PRD-declared endpoints only.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_activity_account_payload,
    create_allocation_run_payload,
    create_design_payload,
    create_event_sale_payload,
    create_exchange_payload,
    create_order_line,
    create_order_payload,
    create_preorder_campaign_payload,
    create_preorder_payload,
    create_product_variant_payload,
    create_program_payload,
    create_purchase_order_payload,
    create_quote_payload,
    create_seasonal_drop_payload,
    create_vendor_payload,
)
from .test_users import (
    TEST_USERS,
    make_cashier_headers,
    make_customer_headers,
)

DIRECTOR = TEST_USERS["director_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
TREASURER = TEST_USERS["treasurer_headers"]

DEFAULT_EVENT_STARTS = TEST_DEFAULTS["EVENT_STARTS"]
DEFAULT_EVENT_ENDS = TEST_DEFAULTS["EVENT_ENDS"]
DEFAULT_CAMPAIGN_OPENS = TEST_DEFAULTS["CAMPAIGN_OPENS"]
DEFAULT_CAMPAIGN_CLOSES = TEST_DEFAULTS["CAMPAIGN_CLOSES"]


# ─── Tier 1: Program lifecycle ────────────────────────

def create_program(**overrides):
    """Create a MerchProgram (starts SETUP). Returns the program dict."""
    res = api_client.create_program(create_program_payload(**overrides), DIRECTOR)
    return get_success_data(res)


def transition_program(program_id, to_state):
    res = api_client.program_lifecycle(program_id, {"to_state": to_state}, DIRECTOR)
    return get_success_data(res)


def create_active_program(**overrides):
    """Create program + transition to ACTIVE. Returns activated program."""
    program = create_program(**overrides)
    return transition_program(program["id"], "ACTIVE")


def get_program(program_id):
    return get_success_data(api_client.get_program(program_id, DIRECTOR))


def fresh_program_version(program_id):
    """Current MerchProgram.version — needed for OCC-guarded drop creates."""
    return get_program(program_id)["version"]


def add_profit(program_id, amount_cents, reason="donation"):
    """Post a manual profit adjustment to undistributed profit."""
    res = api_client.create_profit_adjustment(
        program_id, {"amount_cents": amount_cents, "reason": reason}, DIRECTOR
    )
    return get_success_data(res)


def set_clock(to_iso8601):
    res = api_client.set_clock({"to_iso8601": to_iso8601}, DIRECTOR)
    return get_success_data(res)


def run_ops(program_id):
    res = api_client.run_ops(program_id, DIRECTOR)
    return get_success_data(res)


# ─── Tier 1: Design licensing (OCC-threaded) ──────────

def create_design(program_id, **overrides):
    """Create a Design (starts DRAFT, revision_count 0)."""
    res = api_client.create_design(create_design_payload(program_id, **overrides), MANAGER)
    return get_success_data(res)


def design_transition(design_id, to_state, expected_design_version, note=None):
    payload = {
        "to_state": to_state,
        "expected_design_version": expected_design_version,
    }
    if note is not None:
        payload["note"] = note
    res = api_client.design_licensing_transition(design_id, payload, COORDINATOR)
    return get_success_data(res)


def submit_design(design):
    return design_transition(design["id"], "SUBMITTED", design["version"])


def approve_design(design):
    return design_transition(design["id"], "APPROVED", design["version"])


def create_approved_design(program_id, **overrides):
    """Create design and walk DRAFT -> SUBMITTED -> APPROVED. Returns it."""
    design = create_design(program_id, **overrides)
    return approve_design(submit_design(design))


# ─── Tier 1: Vendors ──────────────────────────────────

def create_vendor(program_id, quotes=None, **overrides):
    res = api_client.create_vendor(
        create_vendor_payload(program_id, quotes=quotes, **overrides), MANAGER
    )
    return get_success_data(res)


def patch_vendor(vendor_id, **fields):
    return get_success_data(api_client.update_vendor(vendor_id, fields, MANAGER))


def create_approved_vendor_with_quote(
    program_id,
    design_id,
    unit_cost_cents=500,
    min_order_qty=25,
    production_days=10,
    name="PrintCo",
):
    """Vendor with one ACTIVE quote on the design, promoted to APPROVED."""
    vendor = create_vendor(
        program_id,
        quotes=[
            create_quote_payload(
                design_id,
                unit_cost_cents=unit_cost_cents,
                min_order_qty=min_order_qty,
                production_days=production_days,
            )
        ],
        name=name,
        contact_email=f"{name.lower()}@co.com",
    )
    return patch_vendor(vendor["id"], status="APPROVED")


# ─── Tier 1: Variants ─────────────────────────────────

def create_variant(
    program_id, design_id, size="M", unit_price_cents=2500, drop_id=None, **overrides
):
    payload_overrides = {"size": size, "unit_price_cents": unit_price_cents}
    if drop_id is not None:
        payload_overrides["drop_id"] = drop_id
    payload_overrides.update(overrides)
    res = api_client.create_product_variant(
        create_product_variant_payload(program_id, design_id, **payload_overrides),
        MANAGER,
    )
    return get_success_data(res)


def get_variant(variant_id):
    return get_success_data(api_client.get_product_variant(variant_id, MANAGER))


# ─── Tier 1: Seasonal drops ───────────────────────────

def create_drop(program_id, expected_program_version, **overrides):
    res = api_client.create_seasonal_drop(
        create_seasonal_drop_payload(program_id, expected_program_version, **overrides),
        MANAGER,
    )
    return get_success_data(res)


def drop_transition(drop_id, to_state):
    res = api_client.seasonal_drop_transition(drop_id, {"to_state": to_state}, MANAGER)
    return get_success_data(res)


# ─── Tier 1: Purchase orders ──────────────────────────

def create_stock_po(program_id, variant_id, vendor_id, qty_ordered=25):
    """Manager-created stock PO (DRAFT, auto_created false)."""
    res = api_client.create_purchase_order(
        create_purchase_order_payload(program_id, variant_id, vendor_id, qty_ordered),
        MANAGER,
    )
    return get_success_data(res)


def submit_po(po_id):
    return get_success_data(api_client.submit_purchase_order(po_id, MANAGER))


def receive_po(po_id, qty):
    return get_success_data(
        api_client.receive_purchase_order(po_id, {"qty": qty}, MANAGER)
    )


def stock_variant(program_id, variant_id, vendor_id, qty):
    """Create + submit + fully receive a stock PO. Returns the PO."""
    po = create_stock_po(program_id, variant_id, vendor_id, qty)
    submit_po(po["id"])
    return receive_po(po["id"], qty)


# ─── Tier 2: Storefront composites ────────────────────

def setup_storefront(
    stock_qty=None,
    unit_price_cents=2500,
    unit_cost_cents=500,
    min_order_qty=None,
    size="M",
    licensing_fee_cents=0,
    royalty_pct=0,
    design_name="Eagle",
    program_overrides=None,
):
    """ACTIVE program + APPROVED design + variant (+ optional stocked PO).

    Returns dict(program, design, variant, vendor, po). When stock_qty is
    None, no vendor/PO is created and the variant has zero stock.
    """
    program = create_active_program(**(program_overrides or {}))
    design = create_approved_design(
        program["id"],
        name=design_name,
        royalty_pct=royalty_pct,
        licensing_fee_cents=licensing_fee_cents,
    )
    variant = create_variant(
        program["id"], design["id"], size=size, unit_price_cents=unit_price_cents
    )
    vendor = None
    po = None
    if stock_qty is not None:
        vendor = create_approved_vendor_with_quote(
            program["id"],
            design["id"],
            unit_cost_cents=unit_cost_cents,
            min_order_qty=min_order_qty if min_order_qty is not None else stock_qty,
        )
        po = stock_variant(program["id"], variant["id"], vendor["id"], stock_qty)
    return {
        "program": program,
        "design": design,
        "variant": variant,
        "vendor": vendor,
        "po": po,
    }


# ─── Tier 1/2: Events and drawers ─────────────────────

def create_event(program_id, register="GYM-A", name="Game", starts=None, ends=None):
    res = api_client.create_event_sale(
        create_event_sale_payload(
            program_id,
            name=name,
            register_location=register,
            starts_at=starts or DEFAULT_EVENT_STARTS,
            ends_at=ends or DEFAULT_EVENT_ENDS,
        ),
        MANAGER,
    )
    return get_success_data(res)


def open_drawer(event_id, opening_float_cents=10000, cashier_id="cashier-01"):
    res = api_client.open_drawer(
        event_id,
        {"opening_float_cents": opening_float_cents},
        make_cashier_headers(cashier_id),
    )
    return get_success_data(res)


def create_open_event(
    program_id, register="GYM-A", name="Game", opening_float_cents=10000,
    cashier_id="cashier-01", starts=None, ends=None,
):
    """SCHEDULED event + drawer opened. Returns the OPEN event."""
    event = create_event(program_id, register=register, name=name, starts=starts, ends=ends)
    return open_drawer(event["id"], opening_float_cents, cashier_id)


def get_event(event_id):
    return get_success_data(api_client.get_event_sale(event_id, TREASURER))


# ─── Tier 2: Orders ───────────────────────────────────

def create_pos_order(
    program_id,
    event_id,
    variant_id,
    qty,
    customer_user_id="walkup",
    payment_method="CASH",
    cashier_id="cashier-01",
    discount_pct=None,
):
    line_overrides = {}
    if discount_pct is not None:
        line_overrides["discount_pct"] = discount_pct
    res = api_client.create_order(
        create_order_payload(
            program_id,
            "EVENT_POS",
            customer_user_id,
            payment_method,
            [create_order_line(variant_id, qty, **line_overrides)],
            event_id=event_id,
        ),
        make_cashier_headers(cashier_id),
    )
    return get_success_data(res)


def create_online_order(
    program_id,
    variant_id,
    qty,
    customer_user_id="cust-10",
    payment_method="CARD",
    discount_pct=None,
):
    line_overrides = {}
    if discount_pct is not None:
        line_overrides["discount_pct"] = discount_pct
    res = api_client.create_order(
        create_order_payload(
            program_id,
            "ONLINE",
            customer_user_id,
            payment_method,
            [create_order_line(variant_id, qty, **line_overrides)],
        ),
        make_customer_headers(customer_user_id),
    )
    return get_success_data(res)


def get_order(order_id):
    return get_success_data(api_client.get_order(order_id, TREASURER))


def mark_ready_for_pickup(order_id):
    res = api_client.order_fulfillment_transition(
        order_id, {"to_state": "READY_FOR_PICKUP"}, MANAGER
    )
    return get_success_data(res)


# ─── Tier 2/3: Preorder campaigns ─────────────────────

def create_campaign(program_id, design_id, **overrides):
    res = api_client.create_preorder_campaign(
        create_preorder_campaign_payload(program_id, design_id, **overrides), MANAGER
    )
    return get_success_data(res)


def open_campaign(campaign_id):
    return get_success_data(api_client.open_preorder_campaign(campaign_id, MANAGER))


def create_open_campaign(program_id, design_id, **overrides):
    campaign = create_campaign(program_id, design_id, **overrides)
    return open_campaign(campaign["id"])


def get_campaign(campaign_id):
    return get_success_data(api_client.get_preorder_campaign(campaign_id, MANAGER))


def get_preorder(preorder_id):
    return get_success_data(api_client.get_preorder(preorder_id, TREASURER))


def place_preorder(program_id, campaign_id, variant_id, customer_user_id, qty=1):
    res = api_client.create_preorder(
        create_preorder_payload(
            program_id, campaign_id, variant_id, customer_user_id, qty
        ),
        make_customer_headers(customer_user_id),
    )
    return get_success_data(res)


def pay_preorder(preorder_id, phase, amount_cents, customer_user_id):
    res = api_client.pay_preorder(
        preorder_id,
        {"phase": phase, "amount_cents": amount_cents},
        make_customer_headers(customer_user_id),
    )
    return get_success_data(res)


def place_paid_preorder(program_id, campaign_id, variant_id, customer_user_id, qty=1):
    """Place a preorder and pay its exact deposit. Returns the PAID preorder."""
    preorder = place_preorder(program_id, campaign_id, variant_id, customer_user_id, qty)
    return pay_preorder(
        preorder["id"], "DEPOSIT", preorder["deposit_due_cents"], customer_user_id
    )


def lock_campaign(campaign_id, lock_time="2026-09-01T00:00:00Z"):
    """Advance the logical clock to lock_time (>= closes_at) and lock."""
    set_clock(lock_time)
    return get_success_data(api_client.lock_preorder_campaign(campaign_id, MANAGER))


def list_campaign_pos(campaign_id):
    """All purchase orders carrying this campaign_id, oldest first."""
    res = api_client.list_purchase_orders(
        MANAGER, params={"campaign_id": campaign_id, "limit": 100}
    )
    data, _meta = validate_paginated(res)
    return data


def setup_open_campaign_shop(
    goal_units=5,
    unit_price_cents=2500,
    deposit_pct=0.4,
    variant_size="M",
    with_vendor=False,
    vendor_min_order_qty=1,
    vendor_unit_cost_cents=500,
    closes_at=DEFAULT_CAMPAIGN_CLOSES,
):
    """ACTIVE program + APPROVED design + variant + OPEN campaign.

    Returns dict(program, design, variant, campaign, vendor). Vendor is
    None unless with_vendor is True (lock goal-met branch needs one).
    """
    program = create_active_program()
    design = create_approved_design(program["id"])
    variant = create_variant(
        program["id"], design["id"], size=variant_size, unit_price_cents=unit_price_cents
    )
    vendor = None
    if with_vendor:
        vendor = create_approved_vendor_with_quote(
            program["id"],
            design["id"],
            unit_cost_cents=vendor_unit_cost_cents,
            min_order_qty=vendor_min_order_qty,
        )
    campaign = create_open_campaign(
        program["id"],
        design["id"],
        unit_price_cents=unit_price_cents,
        deposit_pct=deposit_pct,
        goal_units=goal_units,
        closes_at=closes_at,
    )
    return {
        "program": program,
        "design": design,
        "variant": variant,
        "campaign": campaign,
        "vendor": vendor,
    }


def setup_campaign_in_production(
    goal_units=1,
    preorder_qty=1,
    unit_price_cents=2500,
    deposit_pct=0.4,
    vendor_min_order_qty=1,
    vendor_unit_cost_cents=500,
    customer_user_id="cust-01",
    lock_time="2026-09-01T00:00:00Z",
):
    """Full chain through lock: OPEN campaign + PAID preorder(s) covering the
    goal + vendor with ACTIVE quote, then clock past closes_at and lock.

    Returns dict(program, design, variant, vendor, campaign, preorders, pos).
    Campaign is IN_PRODUCTION with auto-created SUBMITTED POs.
    """
    shop = setup_open_campaign_shop(
        goal_units=goal_units,
        unit_price_cents=unit_price_cents,
        deposit_pct=deposit_pct,
        with_vendor=True,
        vendor_min_order_qty=vendor_min_order_qty,
        vendor_unit_cost_cents=vendor_unit_cost_cents,
    )
    preorder = place_paid_preorder(
        shop["program"]["id"],
        shop["campaign"]["id"],
        shop["variant"]["id"],
        customer_user_id,
        preorder_qty,
    )
    campaign = lock_campaign(shop["campaign"]["id"], lock_time)
    shop["campaign"] = campaign
    shop["preorders"] = [preorder]
    shop["pos"] = list_campaign_pos(campaign["id"])
    return shop


def setup_campaign_fulfilling(**kwargs):
    """IN_PRODUCTION campaign with every campaign PO fully received.

    Returns the setup dict from setup_campaign_in_production with the
    campaign re-read in FULFILLING.
    """
    shop = setup_campaign_in_production(**kwargs)
    for po in shop["pos"]:
        receive_po(po["id"], po["qty_ordered"] - po["qty_received"])
    shop["campaign"] = get_campaign(shop["campaign"]["id"])
    return shop


# ─── Tier 2: Exchanges ────────────────────────────────

def create_exchange(program_id, order_id, original_variant_id, new_variant_id, user_id):
    res = api_client.create_exchange(
        create_exchange_payload(
            program_id, order_id, original_variant_id, new_variant_id
        ),
        make_customer_headers(user_id),
    )
    return get_success_data(res)


def approve_exchange(exchange_id):
    res = api_client.exchange_decision(exchange_id, {"decision": "APPROVED"}, TREASURER)
    return get_success_data(res)


def setup_exchange_shop(
    original_price=2500, new_price=2500, stock_qty=25, customer_user_id="cust-40"
):
    """ACTIVE program; APPROVED design; variants M and L stocked; OPEN event;
    POS CARD order of 1 x M recorded for customer_user_id.

    Returns dict(program, design, variant_m, variant_l, event, order).
    """
    program = create_active_program()
    design = create_approved_design(program["id"])
    variant_m = create_variant(
        program["id"], design["id"], size="M", unit_price_cents=original_price
    )
    variant_l = create_variant(
        program["id"], design["id"], size="L", unit_price_cents=new_price
    )
    vendor = create_approved_vendor_with_quote(
        program["id"], design["id"], min_order_qty=stock_qty
    )
    stock_variant(program["id"], variant_m["id"], vendor["id"], stock_qty)
    stock_variant(program["id"], variant_l["id"], vendor["id"], stock_qty)
    event = create_open_event(program["id"], register="GYM-E")
    order = create_pos_order(
        program["id"],
        event["id"],
        variant_m["id"],
        1,
        customer_user_id=customer_user_id,
        payment_method="CARD",
    )
    return {
        "program": program,
        "design": design,
        "variant_m": variant_m,
        "variant_l": variant_l,
        "event": event,
        "order": order,
    }


# ─── Tier 2/5: Profit allocation ──────────────────────

def create_activity_account(program_id, name, allocation_weight, cap_cents=None):
    overrides = {"allocation_weight": allocation_weight}
    if cap_cents is not None:
        overrides["cap_cents"] = cap_cents
    res = api_client.create_activity_account(
        create_activity_account_payload(program_id, name, **overrides), DIRECTOR
    )
    return get_success_data(res)


def create_allocation_run(program_id, distributable_cents):
    res = api_client.create_allocation_run(
        create_allocation_run_payload(program_id, distributable_cents), TREASURER
    )
    return get_success_data(res)


def get_allocation_run(run_id):
    return get_success_data(api_client.get_allocation_run(run_id, TREASURER))


def setup_profit_program(amount_cents=100000, accounts_spec=None):
    """ACTIVE program with undistributed profit and activity accounts.

    accounts_spec: list of (name, weight, cap_cents_or_None). Returns
    dict(program, accounts) where accounts maps name -> account dict.
    """
    program = create_active_program()
    add_profit(program["id"], amount_cents)
    accounts = {}
    for name, weight, cap in (accounts_spec or [("Band", 1, None)]):
        accounts[name] = create_activity_account(program["id"], name, weight, cap)
    return {"program": program, "accounts": accounts}


def setup_waterfall_scenario():
    """The 50/30/20 weight split with Band capped at 30000, profit 100000.

    Returns dict(program, accounts, run) with the DRAFT run for 100000.
    """
    setup = setup_profit_program(
        100000,
        accounts_spec=[
            ("Band", 50, 30000),
            ("Drama", 30, None),
            ("Robotics", 20, None),
        ],
    )
    run = create_allocation_run(setup["program"]["id"], 100000)
    setup["run"] = run
    return setup


def allocation_line_for(run, account_id):
    """Extract the frozen waterfall line for one account."""
    for line in run["lines"]:
        if line["account_id"] == account_id:
            return line
    raise AssertionError(f"No allocation line for account {account_id}")


def get_account(account_id):
    return get_success_data(api_client.get_activity_account(account_id, TREASURER))
