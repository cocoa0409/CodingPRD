"""Composite setup helpers for multi-step test prerequisites.

The test runner restarts the API server before every test, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints. The
logical clock starts at 2026-08-01T00:00:00Z on every fresh server (PRD §2.5);
fixtures set it explicitly before any time-sensitive chain.

Setup calls use get_success_data() so a failed precondition surfaces as a
clear "setup failed" error rather than a confusing assertion failure.
"""
from datetime import datetime, timedelta

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START, DEFAULTS
from .factories import (
    create_balloon_payload,
    create_chase_assignment_payload,
    create_customer_payload,
    create_flight_payload,
    create_launch_site_payload,
    create_passenger_payload,
    create_pilot_payload,
    create_reservation_payload,
    create_weather_briefing_payload,
)
from .test_users import TEST_USERS, make_customer_headers, make_pilot_headers

OPS = TEST_USERS["ops_headers"]
CHASE = TEST_USERS["chase_headers"]
ANON = TEST_USERS["anon_headers"]


# ─── Clock ────────────────────────────────────────────

def set_clock(to_iso8601: str = CLOCK_START):
    """Advance the server-side logical clock (PRD §2.5)."""
    return get_success_data(api_client.set_clock(to_iso8601, OPS))


def _plus_minutes(iso_ts: str, minutes: int) -> str:
    dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00")) + timedelta(
        minutes=minutes
    )
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def dawn_instant(flight: dict, minutes_after_start: int = 30) -> str:
    """An instant inside the flight's dawn window (both ends inclusive)."""
    return _plus_minutes(flight["dawn_window_start"], minutes_after_start)


# ─── Tier 1: single-entity creation ───────────────────

def create_launch_site(**overrides):
    return get_success_data(
        api_client.create_launch_site(create_launch_site_payload(**overrides), OPS)
    )


def grant_permission(site_id):
    return get_success_data(
        api_client.launch_site_event(site_id, {"event_type": "GRANT_PERMISSION"}, OPS)
    )


def create_granted_site(**overrides):
    site = create_launch_site(**overrides)
    return grant_permission(site["id"])


def create_balloon(**overrides):
    return get_success_data(
        api_client.create_balloon(create_balloon_payload(**overrides), OPS)
    )


def record_inspection(balloon_id, inspected_on=DEFAULTS["INSPECTION_DATE"]):
    """RECORD_INSPECTION is OCC-guarded (PRD §2.7): read the current version,
    then submit it as expected_balloon_version."""
    current = get_success_data(api_client.get_balloon(balloon_id, OPS))
    return get_success_data(
        api_client.balloon_event(
            balloon_id,
            {
                "event_type": "RECORD_INSPECTION",
                "inspected_on": inspected_on,
                "expected_balloon_version": current["version"],
            },
            OPS,
        )
    )


def create_inspected_balloon(inspected_on=DEFAULTS["INSPECTION_DATE"], **overrides):
    balloon = create_balloon(**overrides)
    return record_inspection(balloon["id"], inspected_on)


def create_pilot(**overrides):
    """Default experience (20.0 PIC hours / 5 takeoffs-landings) satisfies both
    currency yardsticks, so the pilot registers CURRENT (PRD §2.10)."""
    return get_success_data(api_client.create_pilot(create_pilot_payload(**overrides), OPS))


def create_customer(**overrides):
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), ANON))


def get_customer(customer_id):
    return get_success_data(api_client.get_customer(customer_id, OPS))


def get_flight(flight_id):
    return get_success_data(api_client.get_flight(flight_id, OPS))


def get_reservation(reservation_id):
    return get_success_data(api_client.get_reservation(reservation_id, OPS))


def get_pilot(pilot_id):
    return get_success_data(api_client.get_pilot(pilot_id, OPS))


# ─── Tier 2: publish-ready operation context ──────────

def setup_publish_ready(site_kw=None, balloon_kw=None, pilot_kw=None):
    """GRANTED site + inspected ACTIVE balloon + CURRENT pilot. Sets the clock
    to the startup instant first so every chain starts from a known 'now'."""
    set_clock(CLOCK_START)
    site = create_granted_site(**(site_kw or {}))
    balloon = create_inspected_balloon(**(balloon_kw or {}))
    pilot = create_pilot(**(pilot_kw or {}))
    return {"site": site, "balloon": balloon, "pilot": pilot}


def create_draft_flight(ctx, **overrides):
    payload = create_flight_payload(
        overrides.pop("launch_site_id", ctx["site"]["id"]),
        overrides.pop("balloon_id", ctx["balloon"]["id"]),
        overrides.pop("pilot_id", ctx["pilot"]["id"]),
        **overrides,
    )
    return get_success_data(api_client.create_flight(payload, OPS))


def setup_scheduled_flight(site_kw=None, balloon_kw=None, pilot_kw=None, flight_kw=None):
    """Full publish battery satisfied; flight is SCHEDULED (PRD §3.2)."""
    ctx = setup_publish_ready(site_kw=site_kw, balloon_kw=balloon_kw, pilot_kw=pilot_kw)
    flight = create_draft_flight(ctx, **(flight_kw or {}))
    flight = get_success_data(api_client.flight_event(flight["id"], {"event_type": "PUBLISH"}, OPS))
    ctx["flight"] = flight
    return ctx


# ─── Tier 3: bookings ─────────────────────────────────

def pilot_headers_for(ctx) -> dict:
    return make_pilot_headers(ctx["pilot"]["id"])


def customer_headers_for(customer) -> dict:
    return make_customer_headers(customer["id"])


def book_reservation(flight, customer=None, **overrides):
    """Book against a SCHEDULED flight. Returns (customer, PENDING reservation)."""
    if customer is None:
        customer = create_customer()
    payload = create_reservation_payload(customer["id"], **overrides)
    reservation = get_success_data(
        api_client.create_reservation(flight["id"], payload, customer_headers_for(customer))
    )
    return customer, reservation


def confirm_reservation(reservation, customer, paid_cents=None):
    """CONFIRM pays exactly the quoted fare (PRD §3.4 payment exactness)."""
    if paid_cents is None:
        paid_cents = get_reservation(reservation["id"])["quoted_fare_cents"]
    return get_success_data(
        api_client.reservation_event(
            reservation["id"],
            {"event_type": "CONFIRM", "paid_cents": paid_cents},
            customer_headers_for(customer),
        )
    )


def create_confirmed_booking(flight, customer=None, **overrides):
    customer, reservation = book_reservation(flight, customer, **overrides)
    reservation = confirm_reservation(reservation, customer)
    return customer, reservation


def add_passengers(reservation, customer, weights):
    """Add one manifest entry per weight (allowed while PENDING or CONFIRMED)."""
    headers = customer_headers_for(customer)
    return [
        get_success_data(
            api_client.add_passenger(
                reservation["id"], create_passenger_payload(weight_lbs=w), headers
            )
        )
        for w in weights
    ]


def list_refunds(reservation_id):
    return get_success_data(api_client.list_refunds(reservation_id, OPS))


def sole_refund(reservation_id):
    refunds = list_refunds(reservation_id)
    assert len(refunds) == 1, f"Expected exactly 1 refund, got {len(refunds)}"
    return refunds[0]


# ─── Tier 4: dawn operations progression ──────────────

def enter_weather_review(ctx, at=None):
    """Move the flight SCHEDULED → WEATHER_REVIEW with the clock inside the
    dawn window (default: 30 minutes after dawn_window_start)."""
    flight = ctx["flight"]
    set_clock(at or dawn_instant(flight))
    flight = get_success_data(
        api_client.flight_event(
            flight["id"], {"event_type": "ENTER_WEATHER_REVIEW"}, pilot_headers_for(ctx)
        )
    )
    ctx["flight"] = flight
    return flight


def record_briefing(ctx, **overrides):
    briefing = get_success_data(
        api_client.create_weather_briefing(
            ctx["flight"]["id"],
            create_weather_briefing_payload(**overrides),
            pilot_headers_for(ctx),
        )
    )
    ctx["briefing"] = briefing
    return briefing


def record_go(ctx):
    flight = get_success_data(
        api_client.flight_event(
            ctx["flight"]["id"], {"event_type": "RECORD_GO"}, pilot_headers_for(ctx)
        )
    )
    ctx["flight"] = flight
    return flight


def record_no_go(ctx):
    flight = get_success_data(
        api_client.flight_event(
            ctx["flight"]["id"], {"event_type": "RECORD_NO_GO"}, pilot_headers_for(ctx)
        )
    )
    ctx["flight"] = flight
    return flight


def create_chase(ctx, **overrides):
    chase = get_success_data(
        api_client.create_chase_assignment(
            ctx["flight"]["id"], create_chase_assignment_payload(**overrides), OPS
        )
    )
    ctx["chase"] = chase
    return chase


def setup_weather_review_flight(site_kw=None, balloon_kw=None, pilot_kw=None,
                                flight_kw=None, at=None):
    """SCHEDULED flight advanced into WEATHER_REVIEW inside its dawn window."""
    ctx = setup_scheduled_flight(
        site_kw=site_kw, balloon_kw=balloon_kw, pilot_kw=pilot_kw, flight_kw=flight_kw
    )
    enter_weather_review(ctx, at=at)
    return ctx


def setup_cleared_flight(site_kw=None, balloon_kw=None, pilot_kw=None,
                         flight_kw=None, briefing_kw=None, at=None):
    """WEATHER_REVIEW + RECORDED GO briefing + RECORD_GO → CLEARED_FOR_LAUNCH."""
    ctx = setup_weather_review_flight(
        site_kw=site_kw, balloon_kw=balloon_kw, pilot_kw=pilot_kw,
        flight_kw=flight_kw, at=at,
    )
    record_briefing(ctx, **(briefing_kw or {}))
    record_go(ctx)
    return ctx


def check_in(reservation, additional_paid_cents=0):
    return get_success_data(
        api_client.reservation_event(
            reservation["id"],
            {"event_type": "CHECK_IN", "additional_paid_cents": additional_paid_cents},
            OPS,
        )
    )


# ─── Tier 5: full flight lifecycle ────────────────────

def setup_landed_flight(with_booking=True, photo_tier="NONE", party_weights=(180,),
                        duration_hours=1.0, site_kw=None, balloon_kw=None,
                        pilot_kw=None, flight_kw=None):
    """Full chain through LANDED: publish → (optional confirmed booking with a
    complete manifest) → chase crew assigned → weather review → GO → check-in
    → LAUNCH → LAND. Returns the whole context bundle."""
    ctx = setup_scheduled_flight(
        site_kw=site_kw, balloon_kw=balloon_kw, pilot_kw=pilot_kw, flight_kw=flight_kw
    )
    if with_booking:
        declared = sum(party_weights)
        customer, reservation = create_confirmed_booking(
            ctx["flight"],
            party_size=len(party_weights),
            declared_weight_lbs=declared,
            photo_package_tier=photo_tier,
        )
        add_passengers(reservation, customer, list(party_weights))
        ctx["customer"] = customer
        ctx["reservation"] = reservation
    create_chase(ctx)
    enter_weather_review(ctx)
    record_briefing(ctx)
    record_go(ctx)
    if with_booking:
        # Actual weights equal the declared average, so the settle delta is 0.
        ctx["reservation"] = check_in(ctx["reservation"], additional_paid_cents=0)
    ctx["flight"] = get_success_data(
        api_client.flight_event(
            ctx["flight"]["id"], {"event_type": "LAUNCH"}, pilot_headers_for(ctx)
        )
    )
    ctx["flight"] = get_success_data(
        api_client.flight_event(
            ctx["flight"]["id"],
            {"event_type": "LAND", "duration_hours": duration_hours},
            pilot_headers_for(ctx),
        )
    )
    return ctx


def chase_event(chase_id, event_type, **extra):
    payload = {"event_type": event_type}
    payload.update(extra)
    return get_success_data(api_client.chase_assignment_event(chase_id, payload, CHASE))


def mark_flown(reservation):
    return get_success_data(
        api_client.reservation_event(reservation["id"], {"event_type": "MARK_FLOWN"}, OPS)
    )


# ─── Tier 6: cancellation / refund pipelines ──────────

def cancel_flight(ctx):
    flight = get_success_data(
        api_client.flight_event(ctx["flight"]["id"], {"event_type": "CANCEL"}, OPS)
    )
    ctx["flight"] = flight
    return flight


def setup_no_go_flight(**kw):
    """SCHEDULED flight pushed to NO_GO inside its dawn window."""
    ctx = setup_weather_review_flight(**kw)
    record_no_go(ctx)
    return ctx


def customer_cancel(reservation, customer):
    return get_success_data(
        api_client.reservation_event(
            reservation["id"], {"event_type": "CANCEL"}, customer_headers_for(customer)
        )
    )


def setup_early_customer_cancel(party_size=1, declared_weight_lbs=180,
                                photo_package_tier="NONE", flight_kw=None):
    """CONFIRMED reservation cancelled by its owner more than 24h before the
    dawn window (CUSTOMER_CANCEL_EARLY) with its auto-created REQUESTED refund.
    Returns ctx with keys: site, balloon, pilot, flight, customer, reservation,
    refund."""
    ctx = setup_scheduled_flight(flight_kw=flight_kw)
    customer, reservation = create_confirmed_booking(
        ctx["flight"],
        party_size=party_size,
        declared_weight_lbs=declared_weight_lbs,
        photo_package_tier=photo_package_tier,
    )
    # Two days before the flight is strictly earlier than dawn_window_start - 24h.
    set_clock("2026-08-08T00:00:00Z")
    reservation = customer_cancel(reservation, customer)
    ctx.update(
        customer=customer,
        reservation=reservation,
        refund=sole_refund(reservation["id"]),
    )
    return ctx


def approve_refund(refund_id, approved_amount_cents):
    return get_success_data(
        api_client.refund_event(
            refund_id,
            {"event_type": "APPROVE", "approved_amount_cents": approved_amount_cents},
            OPS,
        )
    )


def pay_refund(refund_id, paid_via):
    return get_success_data(
        api_client.refund_event(refund_id, {"event_type": "PAY", "paid_via": paid_via}, OPS)
    )
