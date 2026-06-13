"""Composite setup helpers for multi-step test prerequisites (PRD §3).

Most interesting claims require the system to be driven through several state
transitions (draft -> quote -> authorize -> book -> accept -> dispatch ->
confirm-delivery -> claim) before the behavior under test is reachable. These
helpers encapsulate those chains so individual tests focus on assertions.

All helpers use get_success_data() (lenient validator) so a setup failure
surfaces as a clear "Setup failed" error instead of a confusing assertion
failure deep inside a test.

Identity threading: every ownership-gated call on an Order/Claim/Schedule uses
make_customer_headers(customer["id"]); every ownership-gated call on a
WireFulfillment uses make_florist_headers(florist["id"]). Operator roles
(Dispatcher/CatalogAdmin) use the shared constants.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_customer_payload,
    create_zone_payload,
    create_arrangement_payload,
    create_holiday_window_payload,
    create_florist_payload,
    create_order_payload,
    create_substitution_payload,
    create_claim_payload,
    create_recurring_schedule_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_florist_headers,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
CATALOG_ADMIN = TEST_USERS["catalog_admin_headers"]


# ─── Clock ────────────────────────────────────────────────────────────────

def set_clock(iso8601: str):
    """Set the simulated wall clock to a supplied instant (PRD §2.10)."""
    return get_success_data(api_client.set_clock({"to_iso8601": iso8601}, DISPATCHER))


# ─── Primitive entity creators ────────────────────────────────────────────

def create_zone(**overrides):
    """Create a DeliveryZone (CatalogAdmin)."""
    return get_success_data(
        api_client.create_zone(create_zone_payload(**overrides), CATALOG_ADMIN))


def create_arrangement(**overrides):
    """Create a catalog Arrangement (CatalogAdmin)."""
    return get_success_data(
        api_client.create_arrangement(create_arrangement_payload(**overrides), CATALOG_ADMIN))


def create_holiday_window(**overrides):
    """Create a HolidayWindow (CatalogAdmin)."""
    return get_success_data(
        api_client.create_holiday_window(create_holiday_window_payload(**overrides), CATALOG_ADMIN))


def create_customer(**overrides):
    """Register a Customer (CatalogAdmin)."""
    return get_success_data(
        api_client.create_customer(create_customer_payload(**overrides), CATALOG_ADMIN))


def create_florist(covered_zone_id, **overrides):
    """Register a Florist (Dispatcher)."""
    return get_success_data(
        api_client.create_florist(create_florist_payload(covered_zone_id, **overrides), DISPATCHER))


def credit_wallet(customer_id, amount_cents):
    """Seed a customer's wallet_credit_cents deterministically (PRD §3.1)."""
    return get_success_data(
        api_client.credit_wallet({"customer_id": customer_id, "amount_cents": amount_cents}, DISPATCHER))


def set_loyalty_tier(customer_id, loyalty_tier):
    """Set a customer's loyalty_tier directly (PRD §3.1)."""
    return get_success_data(
        api_client.set_loyalty_tier({"customer_id": customer_id, "loyalty_tier": loyalty_tier}, DISPATCHER))


def mark_authorized(order_id):
    """Force an order's payment_status to AUTHORIZED at its estimate (PRD §3.4)."""
    return get_success_data(api_client.mark_authorized({"order_id": order_id}, DISPATCHER))


# ─── Catalog setup ────────────────────────────────────────────────────────

def setup_catalog(clock_iso, zone_overrides=None, arrangement_overrides=None,
                  florist_overrides=None, with_florist=True):
    """Set the clock and create a zone, arrangement, customer (and optionally a
    florist) covering that zone. Returns a dict of the created rows."""
    set_clock(clock_iso)
    zone = create_zone(**(zone_overrides or {}))
    arrangement = create_arrangement(**(arrangement_overrides or {}))
    customer = create_customer()
    out = {"zone": zone, "arrangement": arrangement, "customer": customer, "florist": None}
    if with_florist:
        out["florist"] = create_florist(zone["id"], **(florist_overrides or {}))
    return out


# ─── Order lifecycle stages ───────────────────────────────────────────────

def create_draft_order(customer, arrangement, zone, **order_overrides):
    """Create a DRAFT order owned by `customer` (PRD §3.2)."""
    payload = create_order_payload(
        customer["id"], arrangement["id"], zone["id"], **order_overrides)
    return get_success_data(
        api_client.create_order(payload, make_customer_headers(customer["id"])))


def quote_order(order, customer):
    """Quote an order DRAFT->QUOTED (PRD §3.2)."""
    return get_success_data(
        api_client.quote_order(order["id"], make_customer_headers(customer["id"])))


def book_order(order, customer, expected_version):
    """Book a QUOTED order QUOTED->BOOKED with the given OCC version (PRD §3.4)."""
    return get_success_data(api_client.book_order(
        order["id"], {"expected_order_version": expected_version},
        make_customer_headers(customer["id"])))


def get_order_wire_fulfillment(order):
    """Return the WireFulfillment row created for a booked order (PRD §3.4)."""
    data = get_success_data(api_client.list_order_wire_fulfillments(order["id"], DISPATCHER))
    rows = data if isinstance(data, list) else data.get("data", data)
    return rows[0]


def accept_wire_fulfillment(wf, florist):
    """Florist accepts its assignment ASSIGNED->ACCEPTED (PRD §3.5)."""
    return get_success_data(
        api_client.accept_wire_fulfillment(wf["id"], make_florist_headers(florist["id"])))


def dispatch_order(order, florist):
    """Dispatch a BOOKED+ACCEPTED order BOOKED->IN_TRANSIT (PRD §3.5)."""
    return get_success_data(
        api_client.dispatch_order(order["id"], make_florist_headers(florist["id"])))


def confirm_delivery(order, florist):
    """Confirm delivery IN_TRANSIT->DELIVERED (PRD §3.5)."""
    return get_success_data(
        api_client.confirm_delivery(order["id"], make_florist_headers(florist["id"])))


# ─── Composite order-state shortcuts ──────────────────────────────────────

def setup_quoted_order(clock_iso, zone_overrides=None, arrangement_overrides=None,
                       florist_overrides=None, order_overrides=None, with_florist=True):
    """Catalog + a QUOTED order. Returns (ctx, order) where ctx is the catalog dict."""
    ctx = setup_catalog(clock_iso, zone_overrides, arrangement_overrides,
                        florist_overrides, with_florist=with_florist)
    order = create_draft_order(ctx["customer"], ctx["arrangement"], ctx["zone"],
                               **(order_overrides or {}))
    order = quote_order(order, ctx["customer"])
    return ctx, order


def setup_authorized_order(clock_iso, zone_overrides=None, arrangement_overrides=None,
                           florist_overrides=None, order_overrides=None):
    """Catalog + a QUOTED + AUTHORIZED order. Returns (ctx, order_after_auth)."""
    ctx, order = setup_quoted_order(clock_iso, zone_overrides, arrangement_overrides,
                                    florist_overrides, order_overrides)
    order = mark_authorized(order["id"])
    return ctx, order


def setup_booked_order(clock_iso, zone_overrides=None, arrangement_overrides=None,
                       florist_overrides=None, order_overrides=None):
    """Catalog + a BOOKED order (slot reserved, WireFulfillment ASSIGNED).
    Returns (ctx, order_after_book, wire_fulfillment)."""
    ctx, order = setup_authorized_order(clock_iso, zone_overrides, arrangement_overrides,
                                        florist_overrides, order_overrides)
    order = book_order(order, ctx["customer"], order["version"])
    wf = get_order_wire_fulfillment(order)
    return ctx, order, wf


def setup_accepted_order(clock_iso, zone_overrides=None, arrangement_overrides=None,
                         florist_overrides=None, order_overrides=None):
    """Catalog + a BOOKED order whose WireFulfillment is ACCEPTED.
    Returns (ctx, order, wire_fulfillment_after_accept)."""
    ctx, order, wf = setup_booked_order(clock_iso, zone_overrides, arrangement_overrides,
                                        florist_overrides, order_overrides)
    wf = accept_wire_fulfillment(wf, ctx["florist"])
    return ctx, order, wf


def setup_in_transit_order(clock_iso, zone_overrides=None, arrangement_overrides=None,
                           florist_overrides=None, order_overrides=None):
    """Catalog + an IN_TRANSIT order (dispatched; payment CAPTURED).
    Returns (ctx, order_after_dispatch, wire_fulfillment)."""
    ctx, order, wf = setup_accepted_order(clock_iso, zone_overrides, arrangement_overrides,
                                          florist_overrides, order_overrides)
    order = dispatch_order(order, ctx["florist"])
    return ctx, order, wf


def setup_delivered_order(clock_iso, zone_overrides=None, arrangement_overrides=None,
                          florist_overrides=None, order_overrides=None):
    """Catalog + a DELIVERED order (full happy path).
    Returns (ctx, order_after_delivery, wire_fulfillment)."""
    ctx, order, wf = setup_in_transit_order(clock_iso, zone_overrides, arrangement_overrides,
                                            florist_overrides, order_overrides)
    order = confirm_delivery(order, ctx["florist"])
    return ctx, order, wf


# ─── Claim lifecycle ──────────────────────────────────────────────────────

def file_claim(order, customer, reason, requested_remedy):
    """File a QualityClaim on a DELIVERED order (PRD §3.7)."""
    payload = create_claim_payload(order["id"], customer["id"], reason, requested_remedy)
    return get_success_data(
        api_client.create_claim(payload, make_customer_headers(customer["id"])))


def approve_claim(claim):
    """Approve an OPEN claim OPEN->APPROVED (Dispatcher, PRD §3.7)."""
    return get_success_data(api_client.approve_claim(claim["id"], DISPATCHER))


def resolve_claim(claim, expected_order_version):
    """Resolve an APPROVED claim APPROVED->RESOLVED with OCC version (PRD §3.7)."""
    return get_success_data(api_client.resolve_claim(
        claim["id"], {"expected_order_version": expected_order_version}, DISPATCHER))


def setup_approved_claim(clock_iso, reason, requested_remedy,
                         zone_overrides=None, arrangement_overrides=None,
                         florist_overrides=None, order_overrides=None):
    """Catalog + DELIVERED order + an APPROVED claim with the given reason/remedy.
    Returns (ctx, order_after_delivery, claim_after_approve)."""
    ctx, order, _wf = setup_delivered_order(clock_iso, zone_overrides, arrangement_overrides,
                                            florist_overrides, order_overrides)
    claim = file_claim(order, ctx["customer"], reason, requested_remedy)
    claim = approve_claim(claim)
    return ctx, order, claim


# ─── Recurring schedules ──────────────────────────────────────────────────

def create_schedule(customer, arrangement, zone, **overrides):
    """Create an ACTIVE RecurringSchedule owned by `customer` (PRD §3.8)."""
    payload = create_recurring_schedule_payload(
        customer["id"], arrangement["id"], zone["id"], **overrides)
    return get_success_data(
        api_client.create_recurring_schedule(payload, make_customer_headers(customer["id"])))


def emit_schedule(schedule):
    """Emit the next order from an ACTIVE schedule (Dispatcher, PRD §3.8)."""
    return get_success_data(api_client.emit_schedule(schedule["id"], DISPATCHER))


def get_emitted_order(schedule):
    """Return the most recent order emitted by a schedule via parent_recurrence_id."""
    data = get_success_data(api_client.list_orders(
        DISPATCHER, params={"parent_recurrence_id": schedule["id"]}))
    rows = data if isinstance(data, list) else data.get("data", data)
    return rows[0]
