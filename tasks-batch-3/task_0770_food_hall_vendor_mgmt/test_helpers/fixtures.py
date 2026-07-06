"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so a broken setup surfaces
as a clear "setup failed" error rather than a confusing assertion failure.

Most interesting claims require the system to be in a specific state that takes
6-15 API calls to reach (an "open" stall = active vendor + issued permit + active
lease). These helpers encapsulate those preambles.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_food_hall_payload, create_vendor_payload, create_stall_payload,
    create_lease_payload, create_permit_payload, create_inspection_payload,
    create_order_payload, create_seating_allocation_payload,
    create_marketing_event_payload, create_settlement_payload,
)
from .test_users import TEST_USERS, make_vendor_headers

HM = TEST_USERS["hall_manager_headers"]
HI = TEST_USERS["health_inspector_headers"]
POS = TEST_USERS["pos_operator_headers"]


# ─── Primitive builders ───────────────────────────────────────────────

def set_clock(iso: str):
    """Advance the logical clock (PRD §2.5)."""
    return get_success_data(api_client.set_clock(iso, HM))


def create_food_hall(**overrides) -> dict:
    return get_success_data(api_client.create_food_hall(
        create_food_hall_payload(**overrides), HM))


def create_active_vendor(**overrides) -> dict:
    vendor = get_success_data(api_client.create_vendor(
        create_vendor_payload(**overrides), HM))
    return get_success_data(api_client.activate_vendor(vendor["id"], HM))


def create_applied_vendor(**overrides) -> dict:
    return get_success_data(api_client.create_vendor(
        create_vendor_payload(**overrides), HM))


def create_stall(food_hall_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_stall(
        create_stall_payload(food_hall_id, **overrides), HM))


def create_pending_permit(stall_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_permit(
        create_permit_payload(stall_id, **overrides), HI))


def create_issued_permit(stall_id: str, **overrides) -> dict:
    permit = create_pending_permit(stall_id, **overrides)
    return get_success_data(api_client.issue_permit(permit["id"], HI))


def create_draft_lease(stall_id: str, vendor_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_lease(
        create_lease_payload(stall_id, vendor_id, **overrides), HM))


def create_active_lease(stall_id: str, vendor_id: str, **overrides) -> dict:
    lease = create_draft_lease(stall_id, vendor_id, **overrides)
    return get_success_data(api_client.activate_lease(lease["id"], HM))


# ─── Tier 1/2: "Open stall" composite (active vendor + issued permit +
#     active lease). Returns every id plus the post-activation lease version. ──

def open_stall(clock: str = None, hall_overrides: dict = None,
               stall_overrides: dict = None, lease_overrides: dict = None) -> dict:
    """Build a fully OPEN stall: hall -> active vendor -> stall -> issued permit
    -> active lease. Returns a dict of ids and the activated lease's version.

    An OPEN posture requires: an ACTIVE lease, an ACTIVE vendor, an ISSUED permit,
    and no FAIL/CONDITIONAL inspection (there is none). See PRD §2.6.
    """
    if clock is not None:
        set_clock(clock)
    hall = create_food_hall(**(hall_overrides or {}))
    vendor = create_active_vendor()
    stall = create_stall(hall["id"], **(stall_overrides or {}))
    permit = create_issued_permit(stall["id"])
    lease = create_active_lease(stall["id"], vendor["id"], **(lease_overrides or {}))
    return {
        "food_hall_id": hall["id"],
        "hall": hall,
        "vendor_id": vendor["id"],
        "vendor": vendor,
        "vendor_headers": make_vendor_headers(vendor["id"]),
        "stall_id": stall["id"],
        "stall": stall,
        "permit_id": permit["id"],
        "permit": permit,
        "lease_id": lease["id"],
        "lease": lease,
        "lease_version": lease["version"],
    }


# ─── Order helpers ────────────────────────────────────────────────────

def place_order(food_hall_id: str, stall_id: str, gross_amount_cents: int = 1500,
                item_count: int = 1) -> dict:
    """Place a shared-POS order; a successful placement lands in ROUTED (PRD §3.5)."""
    return get_success_data(api_client.create_order(
        create_order_payload(food_hall_id, stall_id,
                             gross_amount_cents=gross_amount_cents,
                             item_count=item_count), POS))


def accept_order(order_id: str, vendor_id: str) -> dict:
    return get_success_data(api_client.accept_order(order_id, make_vendor_headers(vendor_id)))


def fulfill_order(order_id: str, vendor_id: str) -> dict:
    return get_success_data(api_client.fulfill_order(order_id, make_vendor_headers(vendor_id)))


def reject_order(order_id: str, vendor_id: str) -> dict:
    return get_success_data(api_client.reject_order(order_id, make_vendor_headers(vendor_id)))


def place_accepted_order(ctx: dict, gross_amount_cents: int, item_count: int = 1) -> dict:
    o = place_order(ctx["food_hall_id"], ctx["stall_id"], gross_amount_cents, item_count)
    return accept_order(o["id"], ctx["vendor_id"])


def place_fulfilled_order(ctx: dict, gross_amount_cents: int, item_count: int = 1) -> dict:
    o = place_order(ctx["food_hall_id"], ctx["stall_id"], gross_amount_cents, item_count)
    accept_order(o["id"], ctx["vendor_id"])
    return fulfill_order(o["id"], ctx["vendor_id"])


# ─── Seating helpers ──────────────────────────────────────────────────

def reserve_seats(food_hall_id: str, seats: int, start_time: str, end_time: str,
                  order_id: str = None) -> dict:
    payload = create_seating_allocation_payload(
        food_hall_id, seats=seats, start_time=start_time, end_time=end_time)
    if order_id is not None:
        payload["order_id"] = order_id
    return get_success_data(api_client.create_seating_allocation(payload, POS))


def release_seats(seating_id: str) -> dict:
    return get_success_data(api_client.release_seating_allocation(seating_id, POS))


# ─── Marketing-event helpers ──────────────────────────────────────────

def create_planned_event(food_hall_id: str, **overrides) -> dict:
    return get_success_data(api_client.create_marketing_event(
        create_marketing_event_payload(food_hall_id, **overrides), HM))


def create_scheduled_event(food_hall_id: str, **overrides) -> dict:
    event = create_planned_event(food_hall_id, **overrides)
    return get_success_data(api_client.schedule_marketing_event(event["id"], HM))


# ─── Settlement helpers ───────────────────────────────────────────────

def create_provisional_settlement(lease_id: str, expected_lease_version: int,
                                   period_start: str = "2026-06-01",
                                   period_end: str = "2026-06-30") -> dict:
    return get_success_data(api_client.create_settlement(
        create_settlement_payload(lease_id, expected_lease_version,
                                  period_start=period_start, period_end=period_end), HM))


def create_finalized_settlement(lease_id: str, expected_lease_version: int,
                                period_start: str = "2026-06-01",
                                period_end: str = "2026-06-30") -> dict:
    se = create_provisional_settlement(lease_id, expected_lease_version,
                                       period_start, period_end)
    return get_success_data(api_client.finalize_settlement(se["id"], HM))


# ─── Inspection helper ────────────────────────────────────────────────

def schedule_inspection(stall_id: str, scheduled_for: str = "2026-06-15T09:00:00Z") -> dict:
    return get_success_data(api_client.create_inspection(
        create_inspection_payload(stall_id, scheduled_for=scheduled_for), HI))


def conduct_inspection(stall_id: str, score: int,
                       scheduled_for: str = "2026-06-15T09:00:00Z") -> dict:
    insp = schedule_inspection(stall_id, scheduled_for)
    return get_success_data(api_client.conduct_inspection(insp["id"], score, HI))
