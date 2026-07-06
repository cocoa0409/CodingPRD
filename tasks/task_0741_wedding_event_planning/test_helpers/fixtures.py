"""Composite setup helpers for the Wedding & Event Planning API.

Every helper builds its preconditions from scratch through PRD-declared endpoints
(the test harness restarts the server and empties the database before every test),
using get_success_data() so that a broken setup surfaces as a clear "Setup step
failed" error rather than an opaque assertion failure.

Identity threading: the Client role is entity_backed:EventProject, so every
ownership-gated Client call (signing / requesting a revision on the event's
contract) uses make_client_headers(event["id"]) — never the shared fallback.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_client_headers, make_vendor_headers

# The Planner is an opaque operator; the shared constant is its canonical form.
PLANNER = TEST_USERS["planner_headers"]


# ---------------------------------------------------------------------------
# Low-level single-call builders
# ---------------------------------------------------------------------------
def create_event(**overrides) -> dict:
    payload = {
        "couple_names": "Alex & Blair",
        "event_date": "2026-09-15T00:00:00Z",
        "venue_name": "Grand Hall",
        "package_type": "FULL",
        "total_budget_cents": 10_000_000,
        "guest_count_estimate": 100,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_event(payload, PLANNER))


def get_event(event_id) -> dict:
    return get_success_data(api_client.get_event(event_id, PLANNER))


def create_contract(event_id, expected_event_version, **overrides) -> dict:
    payload = {"event_id": event_id, "expected_event_version": expected_event_version}
    payload.update(overrides)
    return get_success_data(api_client.create_contract(payload, PLANNER))


def create_vendor(**overrides) -> dict:
    payload = {"name": "Test Vendor", "category": "FLORAL", "contact_email": "vendor@example.com"}
    payload.update(overrides)
    return get_success_data(api_client.create_vendor(payload, PLANNER))


def create_coi(vendor_id, **overrides) -> dict:
    payload = {
        "vendor_id": vendor_id,
        "policy_number": "POL-1",
        "coverage_amount_cents": 100_000_000,
        "coverage_expiry_date": "2027-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return get_success_data(api_client.create_coi(payload, PLANNER))


def verify_coi(coi_id) -> dict:
    return get_success_data(api_client.verify_coi(coi_id, PLANNER))


def create_booking(event_id, vendor_id, estimated_cost_cents=1_000_000, **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "vendor_id": vendor_id,
        "service_description": "Vendor service",
        "estimated_cost_cents": estimated_cost_cents,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_vendor_booking(payload, PLANNER))


def book_booking(booking_id, contracted_cost_cents) -> dict:
    return get_success_data(
        api_client.book_vendor_booking(
            booking_id, {"contracted_cost_cents": contracted_cost_cents}, PLANNER
        )
    )


def create_guest(event_id, party_size=2, **overrides) -> dict:
    payload = {"event_id": event_id, "guest_name": "Party Guest", "party_size": party_size}
    payload.update(overrides)
    return get_success_data(api_client.create_guest(payload, PLANNER))


def rsvp(guest_id, rsvp_status, headers=None) -> dict:
    return get_success_data(
        api_client.rsvp_guest(guest_id, {"rsvp_status": rsvp_status}, headers or PLANNER)
    )


def create_accepted_guest(event_id, party_size=2, **overrides) -> dict:
    guest = create_guest(event_id, party_size=party_size, **overrides)
    return rsvp(guest["id"], "ACCEPTED")


def create_table(event_id, capacity=8, **overrides) -> dict:
    payload = {"event_id": event_id, "table_label": "T1", "capacity": capacity}
    payload.update(overrides)
    return get_success_data(api_client.create_table(payload, PLANNER))


def seat_guest(event_id, guest_id, table_id) -> dict:
    payload = {"event_id": event_id, "guest_id": guest_id, "table_id": table_id}
    return get_success_data(api_client.create_seat_assignment(payload, PLANNER))


def create_staff_member(event_id, hourly_rate_cents=5_000, role_title="SERVER", **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "staff_name": "Sam Staff",
        "role_title": role_title,
        "hourly_rate_cents": hourly_rate_cents,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_staff_member(payload, PLANNER))


def create_staff_assignment(event_id, staff_member_id, start, end) -> dict:
    payload = {
        "event_id": event_id,
        "staff_member_id": staff_member_id,
        "shift_start_offset_min": start,
        "shift_end_offset_min": end,
    }
    return get_success_data(api_client.create_staff_assignment(payload, PLANNER))


def create_timeline_block(event_id, start, end, zone="RECEPTION_HALL",
                          block_type="RECEPTION", **overrides) -> dict:
    payload = {
        "event_id": event_id,
        "label": "Run-of-show block",
        "zone": zone,
        "block_type": block_type,
        "start_offset_min": start,
        "end_offset_min": end,
    }
    payload.update(overrides)
    return get_success_data(api_client.create_timeline_block(payload, PLANNER))


def set_clock(to_iso8601) -> None:
    """Advance the server logical clock (PRD §2.6). Returns nothing; the endpoint
    reports side effects only."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, PLANNER)
    assert 200 <= resp.status_code < 300, (
        f"Setup step failed: set clock -> HTTP {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# Contract-progression composites (Tier 1 / Tier 3)
# ---------------------------------------------------------------------------
def setup_draft_contract_event(**event_overrides):
    """Event (DRAFT) with a freshly-created DRAFT contract. Returns (event, contract).
    The event's version has already advanced to 2 (contract create bumps it)."""
    event = create_event(**event_overrides)
    contract = create_contract(event["id"], event["version"])
    return event, contract


def setup_sent_contract_event(**event_overrides):
    """Event with its contract advanced to SENT. Returns (event, contract)."""
    event, contract = setup_draft_contract_event(**event_overrides)
    get_success_data(api_client.send_contract(contract["id"], PLANNER))
    return event, contract


def setup_signed_contract_event(**event_overrides):
    """Event with its contract advanced to SIGNED (signed by the owning Client).
    Returns (event, contract)."""
    event, contract = setup_sent_contract_event(**event_overrides)
    get_success_data(api_client.sign_contract(contract["id"], make_client_headers(event["id"])))
    return event, contract


def setup_countersigned_contract_event(**event_overrides):
    """Event (still DRAFT) with its active contract COUNTERSIGNED. Returns
    (event, contract)."""
    event, contract = setup_signed_contract_event(**event_overrides)
    contract = get_success_data(api_client.countersign_contract(contract["id"], PLANNER))
    return event, contract


def setup_event_in_booking(**event_overrides):
    """Full path to an event in BOOKING: create -> contract -> send -> sign ->
    countersign -> confirm. Returns (event, contract) where event reflects the
    BOOKING state."""
    event, contract = setup_countersigned_contract_event(**event_overrides)
    booking_event = get_success_data(api_client.confirm_event(event["id"], PLANNER))
    return booking_event, contract


# ---------------------------------------------------------------------------
# Vendor / COI composites (Tier 2)
# ---------------------------------------------------------------------------
def create_verified_vendor(coverage_expiry_date="2027-01-01T00:00:00Z", **vendor_overrides):
    """Vendor with a VERIFIED COI. Returns (vendor, coi)."""
    vendor = create_vendor(**vendor_overrides)
    coi = create_coi(vendor["id"], coverage_expiry_date=coverage_expiry_date)
    coi = verify_coi(coi["id"])
    return vendor, coi


def create_pending_vendor(coverage_expiry_date="2027-01-01T00:00:00Z", **vendor_overrides):
    """Vendor with a PENDING (unverified) COI. Returns (vendor, coi)."""
    vendor = create_vendor(**vendor_overrides)
    coi = create_coi(vendor["id"], coverage_expiry_date=coverage_expiry_date)
    return vendor, coi


# ---------------------------------------------------------------------------
# Booking-ready composites (Tier 2 / Tier 4 threshold targeting)
# ---------------------------------------------------------------------------
def setup_booking_ready(coverage_expiry_date="2027-01-01T00:00:00Z",
                        vendor_category="FLORAL", **event_overrides):
    """Event in BOOKING plus a vendor holding a VERIFIED COI valid for the event.
    Returns (event, vendor). Accepts total_budget_cents / package_type / event_date
    overrides for threshold targeting."""
    event, _contract = setup_event_in_booking(**event_overrides)
    vendor, _coi = create_verified_vendor(
        coverage_expiry_date=coverage_expiry_date, category=vendor_category
    )
    return event, vendor


def setup_booked_booking(contracted_cost_cents=2_000_000, total_budget_cents=10_000_000,
                         estimated_cost_cents=1_000_000, **event_overrides):
    """Event in BOOKING with one BOOKED booking (two SCHEDULED payments minted).
    Returns (event, vendor, booking) where booking reflects the BOOKED state."""
    event, vendor = setup_booking_ready(total_budget_cents=total_budget_cents, **event_overrides)
    booking = create_booking(event["id"], vendor["id"], estimated_cost_cents=estimated_cost_cents)
    booking = book_booking(booking["id"], contracted_cost_cents)
    return event, vendor, booking


def list_booking_payments(booking_id) -> list:
    """Discovery channel for cascade-minted payments (PRD §3.3): the SCHEDULED
    DEPOSIT + BALANCE payments of a booking."""
    data, _meta = _list(api_client.list_vendor_payments, params={"vendor_booking_id": booking_id})
    return data


def _list(list_fn, params=None):
    resp = list_fn(PLANNER, params=params)
    assert 200 <= resp.status_code < 300, (
        f"Setup step failed: list -> HTTP {resp.status_code}: {resp.text}"
    )
    body = resp.json()
    return body["data"], body["meta"]


# ---------------------------------------------------------------------------
# Seating composites (Tier 2)
# ---------------------------------------------------------------------------
def setup_seated_guest(event_id, party_size=3, capacity=5):
    """Event table + one ACCEPTED guest seated at it. Returns (table, guest, seat)."""
    table = create_table(event_id, capacity=capacity)
    guest = create_accepted_guest(event_id, party_size=party_size)
    seat = seat_guest(event_id, guest["id"], table["id"])
    return table, guest, seat
