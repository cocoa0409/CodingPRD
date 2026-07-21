"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "Setup failed" errors rather than confusing assertion failures. Every
helper builds its preconditions from scratch — each test runs against an empty
database with the logical clock at its 2026-07-01T00:00:00Z startup default.

Identity threading: Traveler/Approver are entity-backed roles, so ownership-gated
calls always use make_traveler_headers/make_approver_headers with the real
Traveler.id — never a shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_DEFAULT
from .factories import (
    create_travel_policy_payload, create_traveler_payload, create_vendor_payload,
    create_negotiated_rate_payload, create_trip_request_payload,
    create_booking_payload, create_group_booking_payload, exchange_booking_payload,
    create_invoice_payload,
)
from .test_users import TEST_USERS, make_traveler_headers, make_approver_headers

MGR = TEST_USERS["travel_manager_headers"]
FIN = TEST_USERS["finance_officer_headers"]


# ─── Clock / maintenance ──────────────────────────────
def set_clock(iso: str):
    return get_success_data(api_client.set_clock({"to_iso8601": iso}, MGR))


def run_sweep():
    return get_success_data(api_client.run_sweep(MGR))


# ─── Tier 1: single-entity builders ───────────────────
def make_policy(**overrides) -> dict:
    return get_success_data(api_client.create_travel_policy(
        create_travel_policy_payload(**overrides), MGR))


def make_traveler(policy_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_traveler(
        create_traveler_payload(policy_id, **overrides), MGR))


def make_vendor(**overrides) -> dict:
    return get_success_data(api_client.create_vendor(
        create_vendor_payload(**overrides), MGR))


def make_rate(vendor_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_negotiated_rate(
        create_negotiated_rate_payload(vendor_id, **overrides), MGR))


def make_trip(traveler_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_trip_request(
        create_trip_request_payload(traveler_id, **overrides),
        make_traveler_headers(traveler_id)))


def submit_trip(trip_id: str, traveler_id: str) -> dict:
    return get_success_data(api_client.submit_trip_request(
        trip_id, make_traveler_headers(traveler_id)))


def approve_trip(trip_id: str, approver_id: str) -> dict:
    return get_success_data(api_client.approve_trip_request(
        trip_id, make_approver_headers(approver_id)))


def reject_trip(trip_id: str, approver_id: str, reason: str = None) -> dict:
    payload = {"reason": reason} if reason is not None else {}
    return get_success_data(api_client.reject_trip_request(
        trip_id, make_approver_headers(approver_id), payload))


def cancel_trip(trip_id: str, traveler_id: str) -> dict:
    return get_success_data(api_client.cancel_trip_request(
        trip_id, make_traveler_headers(traveler_id)))


def trip_version(trip_id: str, traveler_id: str) -> int:
    trip = get_success_data(api_client.get_trip_request(
        trip_id, make_traveler_headers(traveler_id)))
    return trip["version"]


def book(trip_id: str, traveler_id: str, expected_version: int, **overrides) -> dict:
    return get_success_data(api_client.create_booking(
        create_booking_payload(trip_id, overrides.pop("vendor_id"), expected_version, **overrides),
        make_traveler_headers(traveler_id)))


def cancel_booking(booking_id: str, traveler_id: str) -> dict:
    return get_success_data(api_client.cancel_booking(
        booking_id, make_traveler_headers(traveler_id)))


def exchange(booking_id: str, traveler_id: str, new_fare_cents: int, **overrides) -> dict:
    return get_success_data(api_client.exchange_booking(
        booking_id, exchange_booking_payload(new_fare_cents, **overrides),
        make_traveler_headers(traveler_id)))


def make_group_booking(vendor_id: str, organizer_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_group_booking(
        create_group_booking_payload(vendor_id, organizer_id, **overrides), MGR))


def confirm_group_booking(gb_id: str, confirmed_count: int) -> dict:
    return get_success_data(api_client.confirm_group_booking(
        gb_id, {"confirmed_count": confirmed_count}, MGR))


def make_invoice(vendor_id: str, invoiced_total_cents: int, lines: list, **overrides) -> dict:
    return get_success_data(api_client.create_invoice(
        create_invoice_payload(vendor_id, invoiced_total_cents, lines, **overrides), FIN))


# ─── Credit lookup helpers ────────────────────────────
def credits_for_origin(origin_booking_id: str, traveler_id: str) -> list:
    return get_success_data(api_client.list_unused_ticket_credits(
        make_traveler_headers(traveler_id),
        params={"origin_booking_id": origin_booking_id}))


def credits_for_traveler(traveler_id: str) -> list:
    return get_success_data(api_client.list_unused_ticket_credits(
        make_traveler_headers(traveler_id),
        params={"traveler_id": traveler_id}))


def first_credit_for_origin(origin_booking_id: str, traveler_id: str) -> dict:
    rows = credits_for_origin(origin_booking_id, traveler_id)
    assert rows, f"Setup failed: no credit found for origin booking {origin_booking_id}"
    return rows[0]


def get_credit(credit_id: str) -> dict:
    return get_success_data(api_client.get_unused_ticket_credit(credit_id, MGR))


# ─── Tier 2/3: composite scenarios ────────────────────
def make_approved_trip(*, clock: str = CLOCK_DEFAULT, policy_overrides: dict = None,
                       traveler_grade: str = "STANDARD", market_estimate: int = 50000,
                       vendor_type: str = "AIR", with_rate: bool = False,
                       rate_overrides: dict = None, trip_overrides: dict = None) -> dict:
    """Program bootstrap through an APPROVED, ready-to-book TripRequest.

    Sets the clock, creates a policy, an owning traveler, and a vendor. Optionally
    creates a matching negotiated rate (drives the provisional estimate). Creates a
    trip and submits it; if submission routes to PENDING_MANAGER, a separate MANAGER
    approver clears it to APPROVED. Returns a dict of all created handles; the
    returned ``trip`` carries its current ``version`` (use for the first booking).
    """
    set_clock(clock)
    policy = make_policy(**(policy_overrides or {}))
    traveler = make_traveler(policy["id"], grade=traveler_grade)
    vendor = make_vendor(vendor_type=vendor_type)
    rate = make_rate(vendor["id"], **(rate_overrides or {})) if with_rate else None
    trip = make_trip(traveler["id"], market_estimate_cents=market_estimate, **(trip_overrides or {}))
    trip = submit_trip(trip["id"], traveler["id"])
    approver = None
    if trip["status"] == "PENDING_MANAGER":
        approver = make_traveler(policy["id"], grade="MANAGER")
        trip = approve_trip(trip["id"], approver["id"])
    return {"policy": policy, "traveler": traveler, "vendor": vendor,
            "rate": rate, "approver": approver, "trip": trip}


def make_credit_from_cancelled_nonref(*, fare_cents: int = 250000, clock: str = CLOCK_DEFAULT,
                                      policy_overrides: dict = None) -> dict:
    """Approved trip + one AIR NONREFUNDABLE booking, then cancel it to mint a credit.

    Returns dict: policy, traveler, vendor, trip, booking (CANCELLED), credit (AVAILABLE).
    """
    ctx = make_approved_trip(clock=clock, policy_overrides=policy_overrides,
                             market_estimate=50000,
                             trip_overrides={"return_date": "2026-08-20T09:00:00Z"})
    trav_id = ctx["traveler"]["id"]
    booking = book(ctx["trip"]["id"], trav_id, ctx["trip"]["version"],
                   vendor_id=ctx["vendor"]["id"], segment_type="AIR",
                   fare_basis="NONREFUNDABLE", fare_cents=fare_cents)
    cancel_booking(booking["id"], trav_id)
    credit = first_credit_for_origin(booking["id"], trav_id)
    ctx["booking"] = booking
    ctx["credit"] = credit
    return ctx
