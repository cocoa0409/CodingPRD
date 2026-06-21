"""Composite setup helpers for multi-step test prerequisites (PRD §3).

Most interesting claims require the system to be walked into a specific state
(deliver a purchase, build an APPROVED_REPAIR warranty ticket, advance a build
to ASSEMBLING, accumulate store credit, etc.). These helpers encapsulate those
chains so test bodies focus on assertions.

The test harness restarts the server and clears the database before EVERY test
(see SKILL Testing principles), so every helper builds its preconditions from
scratch using only PRD-declared endpoints.

Setup calls use get_success_data() (lenient validator) so a setup misstep
produces a clear "Setup failed" error rather than a confusing assertion.

Identity threading (PRD §2.1): the Customer role is entity-backed. The one
ownership-gated mutation is approving a ticket — these helpers call
make_customer_headers(customer["id"]) for that, never the shared fallback.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_customer_payload, create_sku_payload, create_tune_up_tier_payload,
    create_service_ticket_payload, create_labor_line_payload,
    create_service_bay_payload, create_bay_booking_payload,
    create_sales_order_payload, create_order_line_payload, reserve_payload,
    create_layaway_plan_payload, create_special_order_payload,
    create_build_job_payload, reserve_part_payload,
    create_warranty_claim_payload, approve_warranty_payload,
    create_trade_in_payload, create_payment_payload,
    create_recall_notice_payload, set_clock_payload,
)
from .test_users import TEST_USERS, make_customer_headers


MGR = TEST_USERS["shop_manager_headers"]
SA = TEST_USERS["sales_associate_headers"]
ADV = TEST_USERS["service_advisor_headers"]


# ─── Primitive creators ─────────────────────────────────────────────────────
def create_customer(**overrides):
    """Create a Customer (PRD §3.1). ShopManager has create authority."""
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), MGR))


def create_sku(**overrides):
    """Create a Sku (PRD §3.1)."""
    return get_success_data(api_client.create_sku(create_sku_payload(**overrides), MGR))


def create_tier(**overrides):
    """Create a TuneUpTier (PRD §3.2)."""
    return get_success_data(api_client.create_tune_up_tier(create_tune_up_tier_payload(**overrides), MGR))


def create_bay(**overrides):
    """Create a ServiceBay (PRD §3.4)."""
    return get_success_data(api_client.create_service_bay(create_service_bay_payload(**overrides), MGR))


def create_order(customer_id, **overrides):
    """Open an empty SalesOrder (PRD §3.5)."""
    return get_success_data(api_client.create_sales_order(create_sales_order_payload(customer_id, **overrides), SA))


def add_order_line(order_id, sku_id, qty=1, **overrides):
    """Add an OrderLine to a PENDING order (PRD §3.5)."""
    return get_success_data(
        api_client.create_order_line(create_order_line_payload(order_id, sku_id, qty, **overrides), SA)
    )


def set_clock(to_iso8601):
    """Set the server's current UTC clock (PRD §3.3)."""
    return api_client.set_clock(set_clock_payload(to_iso8601), MGR)


def get_sku(sku_id):
    return get_success_data(api_client.get_sku(sku_id, MGR))


# ─── Tier 2/3: Sales-order lifecycle shortcuts (PRD §3.5, §3.6) ─────────────
def create_reserved_order(sku_id, qty=1, customer_id=None):
    """Create customer (if needed) + order + one line + reserve.
    Returns (customer, order, line). The order is PENDING|UNPAID -> RESERVED.
    (PRD §3.5 reserve transition.)"""
    customer = {"id": customer_id} if customer_id else create_customer()
    order = create_order(customer["id"])
    line = add_order_line(order["id"], sku_id, qty)
    sku = get_sku(sku_id)
    get_success_data(api_client.reserve_sales_order(order["id"], reserve_payload(sku["version"]), SA))
    order = get_success_data(api_client.get_sales_order(order["id"], SA))
    return customer, order, line


def pay_order(order_id, amount_cents):
    """Capture a payment against a SALES_ORDER (PRD §3.6)."""
    return get_success_data(
        api_client.create_payment(create_payment_payload("SALES_ORDER", order_id, amount_cents), SA)
    )


def create_delivered_purchase(sku_id, qty=1, customer_id=None, price_cents=None):
    """Walk an order to DELIVERED: create -> line -> reserve -> pay full -> deliver.
    Establishes a DELIVERED OrderLine for warranty/recall ownership (PRD §3.5, §3.10).
    Returns (customer, order, line). price_cents is the per-unit price used to
    pay in full; if None it is read back from the order subtotal."""
    customer, order, line = create_reserved_order(sku_id, qty, customer_id)
    pay_order(order["id"], order["subtotal_cents"])
    order = get_success_data(api_client.deliver_sales_order(order["id"], SA))
    return customer, order, line


# ─── Tier 3: Service-ticket lifecycle (PRD §3.2, §3.3) ──────────────────────
def create_ticket(customer_id, tier_id, **overrides):
    """Open a service ticket in INTAKE (PRD §3.2)."""
    return get_success_data(
        api_client.create_service_ticket(create_service_ticket_payload(customer_id, tier_id, **overrides), ADV)
    )


def add_labor_line(ticket_id, labor_cents=3000, menu_code="BRAKE_BLEED"):
    """Add a labor line to a ticket (PRD §3.3)."""
    return get_success_data(
        api_client.create_labor_line(
            create_labor_line_payload(ticket_id, menu_code=menu_code, labor_cents=labor_cents), ADV)
    )


def create_quoted_ticket(customer_id, tier_id, labor_cents=None, **ticket_overrides):
    """Create a ticket, optionally add one labor line, then quote it
    (INTAKE -> AWAITING_APPROVAL). Returns the quoted ticket. (PRD §3.2, §3.3.)"""
    ticket = create_ticket(customer_id, tier_id, **ticket_overrides)
    if labor_cents is not None:
        add_labor_line(ticket["id"], labor_cents=labor_cents)
    return get_success_data(api_client.quote_service_ticket(ticket["id"], ADV))


def create_in_progress_ticket(customer_id, tier_id, labor_cents=None, **ticket_overrides):
    """Quote then customer-approve a ticket (AWAITING_APPROVAL -> IN_PROGRESS).
    Uses make_customer_headers for the ownership-gated approve (PRD §2.1, §3.2)."""
    ticket = create_quoted_ticket(customer_id, tier_id, labor_cents=labor_cents, **ticket_overrides)
    cust_headers = make_customer_headers(customer_id)
    return get_success_data(api_client.approve_service_ticket(ticket["id"], cust_headers))


# ─── Tier 3: Warranty lifecycle (PRD §3.10) ─────────────────────────────────
def create_under_review_claim(sku_id, defect_part, customer_id=None,
                              qty=1, sku_overrides=None):
    """Deliver a purchase of `sku_id`, submit a warranty claim on its DELIVERED
    line, and move it to UNDER_REVIEW. Returns (customer, claim, line).
    (PRD §3.10 submit + review.)"""
    customer, order, line = create_delivered_purchase(sku_id, qty=qty, customer_id=customer_id)
    claim = get_success_data(api_client.create_warranty_claim(
        create_warranty_claim_payload(customer["id"], sku_id, line["id"], defect_part), ADV))
    claim = get_success_data(api_client.review_warranty_claim(claim["id"], ADV))
    return customer, claim, line


def create_approved_repair_claim(sku_id, defect_part="COMPONENT", customer_id=None):
    """Full chain to an APPROVED_REPAIR warranty claim on a covered, delivered
    purchase (PRD §3.10). Returns (customer, claim, line)."""
    customer, claim, line = create_under_review_claim(sku_id, defect_part, customer_id=customer_id)
    claim = get_success_data(api_client.approve_warranty_claim(
        claim["id"], approve_warranty_payload("REPAIR"), ADV))
    return customer, claim, line


# ─── Tier 3: Layaway lifecycle (PRD §3.7) ───────────────────────────────────
def open_layaway(customer_id, sku_id, qty=1):
    """Open a layaway plan, supplying the current Sku.version for the OCC check
    (PRD §2.7, §3.7). Returns the plan."""
    sku = get_sku(sku_id)
    return get_success_data(api_client.create_layaway_plan(
        create_layaway_plan_payload(customer_id, sku_id, sku["version"], qty), SA))


def pay_layaway(plan_id, amount_cents):
    """Capture a payment against a LAYAWAY_PLAN (PRD §3.6)."""
    return get_success_data(
        api_client.create_payment(create_payment_payload("LAYAWAY_PLAN", plan_id, amount_cents), SA)
    )


def open_layaway_with_deposit(customer_id, sku_id, deposit_cents, qty=1):
    """Open a layaway and capture `deposit_cents` of payment against it.
    Returns the plan re-read after payment. (PRD §3.7.)"""
    plan = open_layaway(customer_id, sku_id, qty)
    pay_layaway(plan["id"], deposit_cents)
    return get_success_data(api_client.get_layaway_plan(plan["id"], SA))


# ─── Tier 3: Special-order lifecycle (PRD §3.8) ─────────────────────────────
def create_special_order(customer_id, sku_id, qty=1):
    """Create a special order (QUOTED); deposit_required computed (PRD §3.8)."""
    return get_success_data(
        api_client.create_special_order(create_special_order_payload(customer_id, sku_id, qty), SA)
    )


def pay_special_order(so_id, amount_cents):
    """Capture a payment against a SPECIAL_ORDER (PRD §3.6)."""
    return get_success_data(
        api_client.create_payment(create_payment_payload("SPECIAL_ORDER", so_id, amount_cents), SA)
    )


def create_confirmed_special_order(customer_id, sku_id, qty=1):
    """Create a special order, pay its required deposit, and confirm it
    (QUOTED -> CONFIRMED). Returns the confirmed order. (PRD §3.8.)"""
    so = create_special_order(customer_id, sku_id, qty)
    pay_special_order(so["id"], so["deposit_required_cents"])
    return get_success_data(api_client.confirm_special_order(so["id"], SA))


# ─── Tier 3/4: Build-job lifecycle (PRD §3.9) ───────────────────────────────
def create_build(customer_id, frame_sku_id, required_part_count=1):
    """Create a DRAFT build job on a BIKE frame (PRD §3.9)."""
    return get_success_data(api_client.create_build_job(
        create_build_job_payload(customer_id, frame_sku_id, required_part_count), ADV))


def reserve_frame(build_id):
    return get_success_data(api_client.reserve_frame_build_job(build_id, ADV))


def reserve_part(build_id, part_sku_id, qty=1):
    return get_success_data(
        api_client.reserve_part_build_job(build_id, reserve_part_payload(part_sku_id, qty), ADV))


def create_assembling_build(customer_id, frame_sku_id, part_sku_id, required_part_count):
    """Create a build, reserve the frame + `required_part_count` parts, mark
    parts reserved (DRAFT -> PARTS_RESERVED), then start (PARTS_RESERVED ->
    ASSEMBLING). Returns the started build with build_fee_cents set. (PRD §3.9.)"""
    build = create_build(customer_id, frame_sku_id, required_part_count)
    reserve_frame(build["id"])
    for _ in range(required_part_count):
        reserve_part(build["id"], part_sku_id, 1)
    get_success_data(api_client.mark_parts_reserved_build_job(build["id"], ADV))
    return get_success_data(api_client.start_build_job(build["id"], ADV))


# ─── Tier 3: Trade-in -> store-credit accumulation (PRD §3.11, §3.6) ────────
def create_appraised_trade_in(customer_id, condition_grade, appraised_value_cents,
                              apply_to="STORE_CREDIT"):
    """Record a trade-in appraisal (APPRAISED) (PRD §3.11)."""
    return get_success_data(api_client.create_trade_in(
        create_trade_in_payload(customer_id, condition_grade, appraised_value_cents,
                                apply_to=apply_to), SA))


def accept_trade_in(trade_in_id):
    """Accept a trade-in (APPRAISED -> ACCEPTED), computing the offer and (for
    STORE_CREDIT) crediting the customer (PRD §3.11)."""
    return get_success_data(api_client.accept_trade_in(trade_in_id, MGR))


def seed_store_credit_via_grade_c(customer_id, appraised_value_cents):
    """Seed store credit by accepting a grade-C STORE_CREDIT trade-in.
    offer = round_half_up(appraised * 0.50) - 1500, floored at 0 (PRD §3.11).
    Returns the accepted trade-in. Used to reach known credit balances."""
    ti = create_appraised_trade_in(customer_id, "C", appraised_value_cents, "STORE_CREDIT")
    return accept_trade_in(ti["id"])


# ─── Recalls (PRD §3.11, §2.9) ──────────────────────────────────────────────
def publish_recall(sku_id, severity="ADVISORY"):
    """Publish a recall notice on a Sku (PRD §3.11)."""
    return get_success_data(
        api_client.create_recall_notice(create_recall_notice_payload(sku_id, severity), MGR))
