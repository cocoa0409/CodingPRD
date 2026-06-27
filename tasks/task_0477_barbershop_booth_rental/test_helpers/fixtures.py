"""Composite setup helpers for multi-step test prerequisites.

Each test runs against a freshly-restarted, empty server, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints.

Uses get_success_data() (lenient validator) for setup calls so setup failures
surface as clear "Setup failed" errors rather than confusing assertion noise.

Identity threading: Barber and Customer are entity_backed roles. Operator
endpoints used here (booking, queue, checkout, settlement) are all callable by
ShopOwner/Receptionist (opaque), so the shared operator headers are correct for
the setup chains; entity-backed headers are only threaded in tests that
exercise ownership directly.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_shop_payload,
    create_barber_payload,
    create_chair_payload,
    create_shift_payload,
    create_service_payload,
    create_addon_payload,
    create_product_payload,
    create_membership_payload,
    create_customer_payload,
    create_appointment_payload,
    create_queue_payload,
    set_lines_payload,
)
from .test_users import TEST_USERS

OWNER = TEST_USERS["shop_owner_headers"]
RECEPTION = TEST_USERS["receptionist_headers"]

DEFAULT_CLOCK = "2026-06-10T08:00:00Z"
SHIFT_START = "2026-06-10T09:00:00Z"
SHIFT_END = "2026-06-10T18:00:00Z"


# ─── Primitive helpers ────────────────────────────────────────────────────
def set_clock(iso8601: str):
    """Set the logical clock to an absolute instant."""
    return get_success_data(api_client.set_clock(iso8601, OWNER))


def create_shop(**overrides):
    """Create an OPEN shop. Returns the shop dict."""
    return get_success_data(
        api_client.create_shop(create_shop_payload(**overrides), OWNER)
    )


def shop_version(shop_id: str) -> int:
    """Read the shop's current version (for OCC threading on shift create)."""
    return get_success_data(api_client.get_shop(shop_id, OWNER))["version"]


def barber_version(barber_id: str) -> int:
    return get_success_data(api_client.get_barber(barber_id, OWNER))["version"]


def create_active_barber(shop_id: str, comp_model="COMMISSION", **overrides):
    """Create a barber and activate the license. Returns the activated barber."""
    barber = get_success_data(
        api_client.create_barber(
            create_barber_payload(shop_id, comp_model=comp_model, **overrides), OWNER
        )
    )
    return get_success_data(api_client.activate_license(barber["id"], OWNER))


def create_chair(shop_id: str, label="Chair 1"):
    return get_success_data(
        api_client.create_chair(create_chair_payload(shop_id, label=label), OWNER)
    )


def create_shift(shop_id, barber_id, chair_id,
                 start_utc=SHIFT_START, end_utc=SHIFT_END, expected_version=None):
    """Create a SCHEDULED shift, auto-threading the live shop version for OCC."""
    if expected_version is None:
        expected_version = shop_version(shop_id)
    return get_success_data(
        api_client.create_shift(
            create_shift_payload(
                shop_id, barber_id, chair_id, start_utc, end_utc, expected_version
            ),
            OWNER,
        )
    )


def create_service(shop_id, **overrides):
    return get_success_data(
        api_client.create_service(create_service_payload(shop_id, **overrides), OWNER)
    )


def create_addon(shop_id, **overrides):
    return get_success_data(
        api_client.create_addon(create_addon_payload(shop_id, **overrides), OWNER)
    )


def create_product(shop_id, **overrides):
    return get_success_data(
        api_client.create_product(create_product_payload(shop_id, **overrides), OWNER)
    )


def create_membership(shop_id, **overrides):
    return get_success_data(
        api_client.create_membership(create_membership_payload(shop_id, **overrides), OWNER)
    )


def create_customer(shop_id, **overrides):
    return get_success_data(
        api_client.create_customer(create_customer_payload(shop_id, **overrides), OWNER)
    )


# ─── Tier 2: Entity Hierarchy ─────────────────────────────────────────────
def setup_shop_with_barber_chair_shift(clock=DEFAULT_CLOCK, shop_overrides=None,
                                       barber_overrides=None, comp_model="COMMISSION",
                                       service_overrides=None):
    """Clock set, OPEN shop, ACTIVE barber, chair, a 09:00-18:00 SCHEDULED shift,
    one LISTED Haircut service, and one ACTIVE customer.

    Returns a dict with keys: shop, barber, chair, shift, service, customer.
    This is the most common booking-ready scenario.
    """
    set_clock(clock)
    shop = create_shop(**(shop_overrides or {}))
    chair = create_chair(shop["id"])
    service = create_service(shop["id"], **(service_overrides or {}))
    b_over = dict(barber_overrides or {})
    # Let an explicit comp_model inside barber_overrides win over the dedicated
    # parameter, so passing both does not raise a duplicate-keyword TypeError.
    b_comp = b_over.pop("comp_model", comp_model)
    barber = create_active_barber(shop["id"], comp_model=b_comp, **b_over)
    shift = create_shift(shop["id"], barber["id"], chair["id"])
    customer = create_customer(shop["id"])
    return {
        "shop": shop,
        "barber": barber,
        "chair": chair,
        "shift": shift,
        "service": service,
        "customer": customer,
    }


# ─── Tier 3: Lifecycle shortcuts (appointment-sourced ticket) ──────────────
def book_appointment(ctx, start_utc="2026-06-10T10:00:00Z", addon_ids=None,
                     customer_id=None, service_item_id=None):
    """Book an appointment within the ctx shop/barber/chair/shift. Returns appt."""
    payload = create_appointment_payload(
        ctx["shop"]["id"],
        customer_id or ctx["customer"]["id"],
        ctx["barber"]["id"],
        ctx["chair"]["id"],
        service_item_id or ctx["service"]["id"],
        start_utc,
    )
    if addon_ids is not None:
        payload["addon_ids"] = addon_ids
    return get_success_data(api_client.create_appointment(payload, RECEPTION))


def check_in(appointment_id):
    """Check in a BOOKED appointment. Returns the updated appointment."""
    return get_success_data(api_client.check_in_appointment(appointment_id, RECEPTION))


def checked_in_ticket(ctx, start_utc="2026-06-10T10:00:00Z", addon_ids=None):
    """Book + check in an appointment. Returns (appointment, open_ticket).
    The open ticket is seeded with the appointment's service + addons."""
    appt = book_appointment(ctx, start_utc=start_utc, addon_ids=addon_ids)
    checked = check_in(appt["id"])
    ticket = get_success_data(api_client.get_ticket(checked["ticket_id"], OWNER))
    return checked, ticket


def set_lines(ticket_id, **lines):
    """Replace the lines on an OPEN ticket. Returns the updated ticket."""
    return get_success_data(
        api_client.set_ticket_lines(ticket_id, set_lines_payload(**lines), RECEPTION)
    )


def checkout(ticket_id):
    """Check out (OPEN -> PAID). Returns the paid ticket."""
    return get_success_data(api_client.checkout_ticket(ticket_id, RECEPTION))


# ─── Walk-in / queue lifecycle ─────────────────────────────────────────────
def setup_shop_with_active_barber(clock=DEFAULT_CLOCK, shop_overrides=None,
                                  comp_model="COMMISSION", barber_overrides=None):
    """Clock set, OPEN shop, one ACTIVE barber, one ACTIVE customer — no chair/shift.
    Suited to walk-in queue flows (queue serve resolves a barber, no shift needed).

    Returns dict with keys: shop, barber, customer.
    """
    set_clock(clock)
    shop = create_shop(**(shop_overrides or {}))
    barber = create_active_barber(shop["id"], comp_model=comp_model,
                                  **(barber_overrides or {}))
    customer = create_customer(shop["id"])
    return {"shop": shop, "barber": barber, "customer": customer}


def enqueue(shop_id, customer_id, requested_barber_id=None):
    payload = create_queue_payload(shop_id, customer_id)
    if requested_barber_id is not None:
        payload["requested_barber_id"] = requested_barber_id
    return get_success_data(api_client.create_queue_ticket(payload, RECEPTION))


def serve(queue_ticket_id):
    """Serve a WAITING front ticket. Returns the SERVING queue ticket."""
    return get_success_data(api_client.serve_queue_ticket(queue_ticket_id, RECEPTION))


def served_walkin_ticket(ctx, requested_barber_id="__use_ctx__"):
    """Enqueue + serve a walk-in for the ctx customer/barber. Returns (queue, ticket).
    The open ticket has no lines yet."""
    rb = ctx["barber"]["id"] if requested_barber_id == "__use_ctx__" else requested_barber_id
    q = enqueue(ctx["shop"]["id"], ctx["customer"]["id"], requested_barber_id=rb)
    served = serve(q["id"])
    ticket = get_success_data(api_client.get_ticket(served["ticket_id"], OWNER))
    return served, ticket


# ─── Tier 4: PAID-ticket / settlement targeting ────────────────────────────
def paid_walkin(ctx, lines=None, requested_barber_id="__use_ctx__"):
    """Enqueue -> serve -> (set lines) -> checkout a walk-in. Returns the PAID ticket."""
    _, ticket = served_walkin_ticket(ctx, requested_barber_id=requested_barber_id)
    if lines:
        set_lines(ticket["id"], **lines)
    return checkout(ticket["id"])


def paid_appointment(ctx, start_utc="2026-06-10T10:00:00Z", addon_ids=None, lines=None):
    """Book -> check-in -> (set lines) -> checkout. Returns the PAID ticket."""
    _, ticket = checked_in_ticket(ctx, start_utc=start_utc, addon_ids=addon_ids)
    if lines:
        set_lines(ticket["id"], **lines)
    return checkout(ticket["id"])


def settle(barber_id, business_date="2026-06-10", expected_version=None):
    """Create (finalize) a DailySettlement, auto-threading the live barber version."""
    if expected_version is None:
        expected_version = barber_version(barber_id)
    return get_success_data(
        api_client.create_settlement(
            barber_id,
            {"business_date": business_date, "expected_barber_version": expected_version},
            OWNER,
        )
    )
