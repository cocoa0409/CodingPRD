"""Composite setup helpers for multi-step test prerequisites.

Most testable claims require the system to be in a specific state that takes
5–15 API calls to reach (catalog + client + booking + assignment + submit +
payment). These helpers encapsulate those chains so tests focus on assertions.

All helpers use get_success_data() internally so a setup failure surfaces as a
clear "Setup step failed" error rather than a confusing assertion failure.

Identity threading: Client and Barista are entity-backed roles, so every
ownership-gated call uses make_client_headers(client["id"]) /
make_barista_headers(barista["id"]) — never the shared fallback constants.

ISO-week note: `committed_hours_this_week` only tallies assignments whose
event_start falls inside the current ISO week (PRD §3.1). Fixtures that feed
committed-hours assertions therefore book events inside the same ISO week as
the pinned clock (2026-05-01 is the Friday of ISO week Apr 27 – May 3, so
events on 2026-05-02/2026-05-03 stay in-week).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_client_payload, create_cart_payload, create_barista_payload,
    create_flat_package_payload, create_per_cup_package_payload,
    create_addon_payload, create_travel_zone_payload,
    create_inventory_item_payload, create_cancellation_tier_payload,
    create_booking_payload, create_assignment_offer_payload,
    create_reservation_payload, create_payment_payload,
)
from .constants import DEFAULT_CLOCK_ISO
from .test_users import TEST_USERS, make_client_headers, make_barista_headers

OPS = TEST_USERS["ops_manager_headers"]

# Standard 2-hour FLAT event: flat 60000 + travel 10km x 200 = 62000 total,
# deposit = round_half_up(62000 * 0.30) = 18600 (within the 1000..50000 clamp).
STANDARD_EVENT_START = "2026-05-10T10:00:00Z"
STANDARD_EVENT_END = "2026-05-10T12:00:00Z"
STANDARD_TOTAL_CENTS = 62000
STANDARD_DEPOSIT_CENTS = 18600

# In-week 2-hour event (same ISO week as the default clock 2026-05-01) for
# scenarios that assert on Barista.committed_hours_this_week.
IN_WEEK_EVENT_START = "2026-05-02T10:00:00Z"
IN_WEEK_EVENT_END = "2026-05-02T12:00:00Z"
# Same week but more than 48h ahead of the default clock, for amend/cancel
# scenarios that also assert committed hours.
IN_WEEK_LATE_EVENT_START = "2026-05-03T10:00:00Z"
IN_WEEK_LATE_EVENT_END = "2026-05-03T12:00:00Z"


# ─── Tier 0: clock ────────────────────────────────────────────────────────

def set_clock(to_iso8601: str = DEFAULT_CLOCK_ISO) -> dict:
    """Pin the logical clock (OperationsManager-only test-driving endpoint)."""
    return get_success_data(api_client.set_clock(to_iso8601, OPS))


# ─── Tier 1: catalog entity creators ──────────────────────────────────────

def create_client(**overrides) -> dict:
    return get_success_data(api_client.create_client(create_client_payload(**overrides), OPS))


def create_cart(**overrides) -> dict:
    return get_success_data(api_client.create_cart(create_cart_payload(**overrides), OPS))


def create_barista(**overrides) -> dict:
    return get_success_data(api_client.create_barista(create_barista_payload(**overrides), OPS))


def create_flat_package(**overrides) -> dict:
    return get_success_data(
        api_client.create_package(create_flat_package_payload(**overrides), OPS))


def create_per_cup_package(**overrides) -> dict:
    return get_success_data(
        api_client.create_package(create_per_cup_package_payload(**overrides), OPS))


def create_addon(**overrides) -> dict:
    return get_success_data(api_client.create_addon(create_addon_payload(**overrides), OPS))


def create_travel_zone(**overrides) -> dict:
    return get_success_data(
        api_client.create_travel_zone(create_travel_zone_payload(**overrides), OPS))


def create_inventory_item(**overrides) -> dict:
    return get_success_data(
        api_client.create_inventory_item(create_inventory_item_payload(**overrides), OPS))


def create_cancellation_tier(**overrides) -> dict:
    return get_success_data(
        api_client.create_cancellation_tier(
            create_cancellation_tier_payload(**overrides), OPS))


def seed_default_cancellation_tiers() -> list:
    """The canonical three-tier notice policy used by refund scenarios:
    T1: >=168h -> full refund; T2: 72..168h -> 50%; T3: 0..72h -> 0%."""
    return [
        create_cancellation_tier(tier_code="T1", min_notice_hours=168,
                                 max_notice_hours=-1, deposit_refund_pct=1.0,
                                 balance_waived=True),
        create_cancellation_tier(tier_code="T2", min_notice_hours=72,
                                 max_notice_hours=168, deposit_refund_pct=0.5,
                                 balance_waived=True),
        create_cancellation_tier(tier_code="T3", min_notice_hours=0,
                                 max_notice_hours=72, deposit_refund_pct=0.0,
                                 balance_waived=False),
    ]


# ─── Tier 2: base catalog scenario ────────────────────────────────────────

def setup_base_catalog(package_kind: str = "FLAT",
                       clock: str = DEFAULT_CLOCK_ISO,
                       cart_overrides=None, barista_overrides=None,
                       package_overrides=None, zone_overrides=None) -> dict:
    """Pin the clock and create client + cart + barista + package + zone.

    Returns a ctx dict with the created entities and the ownership-correct
    headers for the client and barista.
    """
    set_clock(clock)
    client = create_client()
    cart = create_cart(**(cart_overrides or {}))
    barista = create_barista(**(barista_overrides or {}))
    if package_kind == "FLAT":
        package = create_flat_package(**(package_overrides or {}))
    else:
        package = create_per_cup_package(**(package_overrides or {}))
    zone = create_travel_zone(**(zone_overrides or {}))
    return {
        "client": client,
        "cart": cart,
        "barista": barista,
        "package": package,
        "zone": zone,
        "client_headers": make_client_headers(client["id"]),
        "barista_headers": make_barista_headers(barista["id"]),
    }


# ─── Tier 2: booking assembly ─────────────────────────────────────────────

def create_quote_booking(ctx: dict, **booking_overrides) -> dict:
    """Create an EventBooking in QUOTE as the owning client.

    Identity fields default to the catalog entities in ``ctx`` but may be
    redirected (e.g. ``cart_id=`` for a second cart) via overrides without
    colliding with the positional arguments of ``create_booking_payload``.
    """
    payload = create_booking_payload(
        booking_overrides.pop("client_id", ctx["client"]["id"]),
        booking_overrides.pop("package_id", ctx["package"]["id"]),
        booking_overrides.pop("cart_id", ctx["cart"]["id"]),
        booking_overrides.pop("travel_zone_id", ctx["zone"]["id"]),
        **booking_overrides)
    return get_success_data(
        api_client.create_booking(payload, ctx["client_headers"]))


def offer_primary_assignment(ctx: dict, booking_id: str, barista_id: str = None) -> dict:
    """OperationsManager offers the booking to a barista (OFFERED, primary)."""
    payload = create_assignment_offer_payload(barista_id or ctx["barista"]["id"])
    return get_success_data(
        api_client.offer_assignment(booking_id, payload, OPS))


def attach_addon(ctx: dict, booking_id: str, addon_id: str) -> dict:
    return get_success_data(api_client.attach_addon(
        booking_id, {"addon_id": addon_id}, ctx["client_headers"]))


def create_reservation(ctx: dict, booking_id: str, item_id: str, qty_units: int) -> dict:
    return get_success_data(api_client.create_reservation(
        booking_id, create_reservation_payload(item_id, qty_units), OPS))


# ─── Tier 3: submission with OCC threading ────────────────────────────────

def current_cart_version(cart_id: str) -> int:
    return get_success_data(api_client.get_cart(cart_id, OPS))["version"]


def current_barista_version(barista_id: str) -> int:
    return get_success_data(api_client.get_barista(barista_id, OPS))["version"]


def submit_quote(ctx: dict, booking_id: str) -> dict:
    """Submit a QUOTE booking with fresh OCC versions (success path)."""
    payload = {
        "expected_cart_version": current_cart_version(ctx["cart"]["id"]),
        "expected_primary_barista_version": current_barista_version(ctx["barista"]["id"]),
    }
    return get_success_data(
        api_client.submit_booking(booking_id, payload, ctx["client_headers"]))


def submit_quote_raw(ctx: dict, booking_id: str, expected_cart_version: int,
                     expected_primary_barista_version: int):
    """Raw submit with caller-pinned OCC versions (for stale/version tests)."""
    payload = {
        "expected_cart_version": expected_cart_version,
        "expected_primary_barista_version": expected_primary_barista_version,
    }
    return api_client.submit_booking(booking_id, payload, ctx["client_headers"])


# ─── Tier 4: payments and confirmation ────────────────────────────────────

def pay_deposit(ctx: dict, booking_id: str, amount_cents: int,
                idempotency_key: str = "dep-1") -> dict:
    """Create a DEPOSIT payment as the client and settle it as OperationsManager.

    Returns the SUCCEEDED payment. When the payment pushes deposit_paid_cents
    to at least deposit_due_cents the booking cascades to CONFIRMED (PRD §3.6).
    """
    payment = get_success_data(api_client.create_payment(
        booking_id,
        create_payment_payload("DEPOSIT", amount_cents, idempotency_key),
        ctx["client_headers"]))
    return get_success_data(api_client.mark_payment_succeeded(payment["id"], OPS))


def setup_quote_with_assignment(package_kind: str = "FLAT",
                                booking_overrides=None,
                                accept: bool = False, **catalog_kw) -> dict:
    """Catalog + QUOTE booking + one OFFERED primary assignment.

    With accept=True the assignment is first accepted (ACCEPTED) by the barista.
    """
    ctx = setup_base_catalog(package_kind=package_kind, **catalog_kw)
    booking = create_quote_booking(ctx, **(booking_overrides or {}))
    assignment = offer_primary_assignment(ctx, booking["id"])
    if accept:
        assignment = get_success_data(
            api_client.accept_assignment(assignment["id"], ctx["barista_headers"]))
    ctx.update({"booking": booking, "assignment": assignment})
    return ctx


def setup_submitted_booking(package_kind: str = "FLAT",
                            booking_overrides=None,
                            accept: bool = False, **catalog_kw) -> dict:
    """Full chain through submit: booking lands in PENDING_DEPOSIT with quoted_*
    recomputed, variants pinned, and deposit_due_cents computed."""
    ctx = setup_quote_with_assignment(
        package_kind=package_kind, booking_overrides=booking_overrides,
        accept=accept, **catalog_kw)
    ctx["booking"] = submit_quote(ctx, ctx["booking"]["id"])
    return ctx


def setup_confirmed_booking(package_kind: str = "FLAT",
                            booking_overrides=None,
                            accept: bool = False,
                            deposit_amount: int = None, **catalog_kw) -> dict:
    """Full chain through deposit settlement: booking lands in CONFIRMED.

    ctx keys added: booking (CONFIRMED), assignment, deposit_payment.
    """
    ctx = setup_submitted_booking(
        package_kind=package_kind, booking_overrides=booking_overrides,
        accept=accept, **catalog_kw)
    amount = deposit_amount
    if amount is None:
        amount = ctx["booking"]["deposit_due_cents"]
    ctx["deposit_payment"] = pay_deposit(ctx, ctx["booking"]["id"], amount)
    ctx["booking"] = get_success_data(
        api_client.get_booking(ctx["booking"]["id"], OPS))
    return ctx


def setup_completed_booking(event_start: str = "2026-05-03T10:00:00Z",
                            event_end: str = "2026-05-03T12:00:00Z",
                            clock_after_event: str = "2026-05-03T13:00:00Z",
                            attended: bool = True, **catalog_kw) -> dict:
    """Full lifecycle through COMPLETED: confirm, advance the clock past
    event_end (auto-transition to IN_PROGRESS), resolve attendance, complete.

    ctx keys added: booking (COMPLETED), assignment (COMPLETED or NO_SHOW),
    deposit_payment.
    """
    ctx = setup_confirmed_booking(
        booking_overrides={"event_start": event_start, "event_end": event_end},
        accept=True, **catalog_kw)
    set_clock(clock_after_event)
    ctx["assignment"] = get_success_data(api_client.resolve_assignment(
        ctx["assignment"]["id"], {"attended": attended}, OPS))
    ctx["booking"] = get_success_data(
        api_client.complete_booking(ctx["booking"]["id"], OPS))
    return ctx
