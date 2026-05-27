"""Composite setup helpers for multi-step preconditions.

Uses get_success_data() (lenient validator) so setup failures produce clear
"Setup failed" errors rather than confusing assertion failures.

The PRD-declared `/v1/_clock/set_current_utc`, `/v1/_ops/no-show-sweep`, and
`/v1/_ops/lightning-lane-expiry-sweep` test-driving endpoints are used to reach
time-dependent boundary states deterministically (PRD §3.8).

Identity threading (mandatory per PRD §2.1):
  - Guest role → use make_guest_headers(guest_id) with the actual guest id.
  - Restaurant role → use make_restaurant_headers(restaurant_id) with the actual restaurant id.
  - PlatformAdmin → shared TEST_USERS["platform_admin_headers"] is canonical (opaque identity).
"""
import uuid
from typing import Optional, List, Tuple, Dict, Any

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_guest_payload,
    create_restaurant_payload,
    create_park_session_payload,
    create_dining_plan_payload,
    create_reservation_payload,
    cancel_reservation_payload,
    patch_party_size_payload,
    create_allergy_meal_payload,
    create_lightning_lane_payload,
    allocate_lightning_lane_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS, make_guest_headers, make_restaurant_headers


_ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Tier 0: Clock ────────────────────────────────────────────────────────

def set_clock(iso_instant: str) -> dict:
    """Advance the virtual current UTC for the whole deployment (PRD §3.8)."""
    return get_success_data(api_client.set_clock(set_clock_payload(iso_instant), _ADMIN))


# ─── Tier 1: Single-entity creation helpers ──────────────────────────────

def create_guest(
    email: Optional[str] = None,
    full_name: str = "Test Guest",
    home_timezone: str = "America/New_York",
) -> dict:
    """Create a Guest. Email defaults to a unique value to avoid collisions."""
    if email is None:
        email = f"guest_{uuid.uuid4().hex[:10]}@example.com"
    res = api_client.create_guest(
        create_guest_payload(email=email, full_name=full_name, home_timezone=home_timezone),
        _ADMIN,
    )
    return get_success_data(res)


def create_restaurant(
    name: str = "Test Restaurant",
    park_code: str = "EPCOT",
    capacity_per_slot: int = 20,
    dining_plan_credit_cost: int = 1,
    no_show_base_fee_cents: int = 1000,
    is_character_dining: bool = False,
    opening_local_time: str = "11:00",
    closing_local_time: str = "22:00",
    slot_minutes: int = 30,
) -> dict:
    res = api_client.create_restaurant(
        create_restaurant_payload(
            name=name,
            park_code=park_code,
            capacity_per_slot=capacity_per_slot,
            dining_plan_credit_cost=dining_plan_credit_cost,
            no_show_base_fee_cents=no_show_base_fee_cents,
            is_character_dining=is_character_dining,
            opening_local_time=opening_local_time,
            closing_local_time=closing_local_time,
            slot_minutes=slot_minutes,
        ),
        _ADMIN,
    )
    return get_success_data(res)


def create_dining_plan(
    guest_id: str,
    tier: str = "STANDARD",
    table_service_credits_initial: int = 10,
    valid_from: str = "2026-01-01T00:00:00Z",
    valid_until: str = "2026-12-31T00:00:00Z",
) -> dict:
    res = api_client.create_dining_plan(
        create_dining_plan_payload(
            guest_id=guest_id,
            tier=tier,
            table_service_credits_initial=table_service_credits_initial,
            valid_from=valid_from,
            valid_until=valid_until,
        ),
        _ADMIN,
    )
    return get_success_data(res)


def create_park_session(
    guest_id: str,
    park_code: str = "EPCOT",
    visit_date: str = "2026-02-15",
    actor: str = "guest",
) -> dict:
    """Create a ParkSession. By default acts as the guest (entity-backed identity)."""
    if actor == "admin":
        headers = _ADMIN
    else:
        headers = make_guest_headers(guest_id)
    res = api_client.create_park_session(
        create_park_session_payload(guest_id=guest_id, park_code=park_code, visit_date=visit_date),
        headers,
    )
    return get_success_data(res)


# ─── Tier 2: Standard "ready-to-book" scaffolding ────────────────────────

def setup_guest_restaurant_plan_session(
    park_code: str = "EPCOT",
    visit_date: str = "2026-02-15",
    capacity_per_slot: int = 20,
    dining_plan_credit_cost: int = 1,
    is_character_dining: bool = False,
    no_show_base_fee_cents: int = 1000,
    opening_local_time: str = "11:00",
    closing_local_time: str = "22:00",
    tier: str = "STANDARD",
    table_service_credits_initial: int = 10,
    plan_valid_from: str = "2026-01-01T00:00:00Z",
    plan_valid_until: str = "2026-12-31T00:00:00Z",
    restaurant_name: str = "Test Restaurant",
    guest_email: Optional[str] = None,
) -> Tuple[dict, dict, dict, dict]:
    """One Guest + Restaurant + DiningPlan + ParkSession ready for booking.
    Returns (guest, restaurant, dining_plan, park_session)."""
    guest = create_guest(email=guest_email)
    restaurant = create_restaurant(
        name=restaurant_name,
        park_code=park_code,
        capacity_per_slot=capacity_per_slot,
        dining_plan_credit_cost=dining_plan_credit_cost,
        is_character_dining=is_character_dining,
        no_show_base_fee_cents=no_show_base_fee_cents,
        opening_local_time=opening_local_time,
        closing_local_time=closing_local_time,
    )
    dp = create_dining_plan(
        guest["id"],
        tier=tier,
        table_service_credits_initial=table_service_credits_initial,
        valid_from=plan_valid_from,
        valid_until=plan_valid_until,
    )
    ps = create_park_session(guest["id"], park_code=park_code, visit_date=visit_date)
    return guest, restaurant, dp, ps


def create_pending_reservation(
    guest: dict,
    restaurant: dict,
    park_session: dict,
    dining_plan: dict,
    slot_start_utc: str = "2026-02-15T18:00:00Z",
    party_size: int = 2,
) -> dict:
    """Create a PENDING Reservation as the owning Guest."""
    headers = make_guest_headers(guest["id"])
    res = api_client.create_reservation(
        create_reservation_payload(
            guest_id=guest["id"],
            restaurant_id=restaurant["id"],
            park_session_id=park_session["id"],
            dining_plan_id=dining_plan["id"],
            slot_start_utc=slot_start_utc,
            party_size=party_size,
        ),
        headers,
    )
    return get_success_data(res)


def confirm_reservation(reservation: dict, guest_id: str) -> dict:
    """Advance Reservation PENDING → CONFIRMED."""
    res = api_client.confirm_reservation(reservation["id"], make_guest_headers(guest_id))
    return get_success_data(res)


def cancel_reservation(reservation_id: str, expected_version: int, guest_id: str) -> dict:
    res = api_client.cancel_reservation(
        reservation_id,
        cancel_reservation_payload(expected_version),
        make_guest_headers(guest_id),
    )
    return get_success_data(res)


# ─── Tier 3: Full ready-to-trigger composites ────────────────────────────

def setup_confirmed_reservation(
    party_size: int = 2,
    slot_start_utc: str = "2026-02-15T18:00:00Z",
    visit_date: str = "2026-02-15",
    park_code: str = "EPCOT",
    capacity_per_slot: int = 20,
    dining_plan_credit_cost: int = 1,
    is_character_dining: bool = False,
    no_show_base_fee_cents: int = 1000,
    opening_local_time: str = "11:00",
    closing_local_time: str = "22:00",
    table_service_credits_initial: int = 10,
    tier: str = "STANDARD",
    restaurant_name: str = "Test Restaurant",
    initial_clock: str = "2026-01-15T12:00:00Z",
    plan_valid_from: str = "2026-01-01T00:00:00Z",
    plan_valid_until: str = "2026-12-31T00:00:00Z",
) -> Tuple[dict, dict, dict, dict, dict]:
    """Set clock + create guest/restaurant/plan/session + create + confirm
    reservation. Returns (guest, restaurant, dining_plan, park_session, reservation)
    where reservation reflects the CONFIRMED state with current version."""
    set_clock(initial_clock)
    guest, restaurant, dp, ps = setup_guest_restaurant_plan_session(
        park_code=park_code,
        visit_date=visit_date,
        capacity_per_slot=capacity_per_slot,
        dining_plan_credit_cost=dining_plan_credit_cost,
        is_character_dining=is_character_dining,
        no_show_base_fee_cents=no_show_base_fee_cents,
        opening_local_time=opening_local_time,
        closing_local_time=closing_local_time,
        tier=tier,
        table_service_credits_initial=table_service_credits_initial,
        plan_valid_from=plan_valid_from,
        plan_valid_until=plan_valid_until,
        restaurant_name=restaurant_name,
    )
    pending = create_pending_reservation(
        guest, restaurant, ps, dp,
        slot_start_utc=slot_start_utc,
        party_size=party_size,
    )
    confirmed = confirm_reservation(pending, guest["id"])
    return guest, restaurant, dp, ps, confirmed


def setup_pending_reservation(
    party_size: int = 2,
    slot_start_utc: str = "2026-02-15T18:00:00Z",
    visit_date: str = "2026-02-15",
    park_code: str = "EPCOT",
    capacity_per_slot: int = 20,
    dining_plan_credit_cost: int = 1,
    is_character_dining: bool = False,
    no_show_base_fee_cents: int = 1000,
    opening_local_time: str = "11:00",
    closing_local_time: str = "22:00",
    table_service_credits_initial: int = 10,
    tier: str = "STANDARD",
    restaurant_name: str = "Test Restaurant",
    initial_clock: str = "2026-01-15T12:00:00Z",
) -> Tuple[dict, dict, dict, dict, dict]:
    """Set clock + create dependencies + create PENDING reservation.
    Returns (guest, restaurant, dining_plan, park_session, reservation)."""
    set_clock(initial_clock)
    guest, restaurant, dp, ps = setup_guest_restaurant_plan_session(
        park_code=park_code,
        visit_date=visit_date,
        capacity_per_slot=capacity_per_slot,
        dining_plan_credit_cost=dining_plan_credit_cost,
        is_character_dining=is_character_dining,
        no_show_base_fee_cents=no_show_base_fee_cents,
        opening_local_time=opening_local_time,
        closing_local_time=closing_local_time,
        tier=tier,
        table_service_credits_initial=table_service_credits_initial,
        restaurant_name=restaurant_name,
    )
    pending = create_pending_reservation(
        guest, restaurant, ps, dp,
        slot_start_utc=slot_start_utc, party_size=party_size,
    )
    return guest, restaurant, dp, ps, pending


# ─── Tier 4: Strike accumulation (for guest suspension scenarios) ────────

def drive_guest_no_show_count(
    guest: dict,
    restaurant: dict,
    dining_plan: dict,
    num_strikes: int,
    park_code: str = "EPCOT",
    base_date: str = "2026-02-01",
) -> List[dict]:
    """Create `num_strikes` prior NO_SHOW reservations for this guest, advancing
    the clock for each one. Returns the list of NO_SHOW reservations.

    Each strike uses a fresh visit_date starting at `base_date`. The clock is
    advanced past the slot end so each mark-no-show satisfies the
    `current_utc > slot_end_utc` precondition.
    """
    from datetime import datetime, timedelta

    base = datetime.strptime(base_date, "%Y-%m-%d")
    results: List[dict] = []
    for i in range(num_strikes):
        d = base + timedelta(days=i)
        visit = d.strftime("%Y-%m-%d")
        slot = f"{visit}T18:00:00Z"
        after = f"{visit}T19:00:00Z"
        ps = create_park_session(guest["id"], park_code=park_code, visit_date=visit)
        pending = create_pending_reservation(
            guest, restaurant, ps, dining_plan,
            slot_start_utc=slot, party_size=1,
        )
        confirm_reservation(pending, guest["id"])
        set_clock(after)
        marked = get_success_data(
            api_client.mark_no_show_reservation(pending["id"], _ADMIN)
        )
        results.append(marked)
    return results


# ─── Tier 5: Convenience fetchers ────────────────────────────────────────

def fetch_reservation(res_id: str, actor_guest_id: Optional[str] = None) -> dict:
    if actor_guest_id is not None:
        headers = make_guest_headers(actor_guest_id)
    else:
        headers = _ADMIN
    return get_success_data(api_client.get_reservation(res_id, headers))


def fetch_dining_plan(dp_id: str, actor_guest_id: Optional[str] = None) -> dict:
    if actor_guest_id is not None:
        headers = make_guest_headers(actor_guest_id)
    else:
        headers = _ADMIN
    return get_success_data(api_client.get_dining_plan(dp_id, headers))


def fetch_guest(guest_id: str) -> dict:
    return get_success_data(api_client.get_guest(guest_id, _ADMIN))


def fetch_park_session(ps_id: str, actor_guest_id: Optional[str] = None) -> dict:
    if actor_guest_id is not None:
        headers = make_guest_headers(actor_guest_id)
    else:
        headers = _ADMIN
    return get_success_data(api_client.get_park_session(ps_id, headers))


def fetch_allergy_meal(am_id: str) -> dict:
    return get_success_data(api_client.get_allergy_meal(am_id, _ADMIN))


def fetch_lightning_lane(ll_id: str, actor_guest_id: Optional[str] = None) -> dict:
    if actor_guest_id is not None:
        headers = make_guest_headers(actor_guest_id)
    else:
        headers = _ADMIN
    return get_success_data(api_client.get_lightning_lane(ll_id, headers))


def list_no_show_assessments_for_reservation(res_id: str) -> list:
    """Return list of NoShowFeeAssessment rows for a given reservation."""
    res = api_client.list_no_show_fee_assessments(
        _ADMIN, params={"reservation_id": res_id}
    )
    data = get_success_data(res)
    if isinstance(data, list):
        return data
    return data


def list_credit_ledger_for_reservation(res_id: str) -> list:
    res = api_client.list_credit_ledger_entries(_ADMIN, params={"reservation_id": res_id})
    data = get_success_data(res)
    if isinstance(data, list):
        return data
    return data


def list_credit_ledger_for_plan(dp_id: str) -> list:
    res = api_client.list_credit_ledger_entries(_ADMIN, params={"dining_plan_id": dp_id})
    data = get_success_data(res)
    if isinstance(data, list):
        return data
    return data


def list_assessments_for_guest(guest_id: str) -> list:
    res = api_client.list_no_show_fee_assessments(_ADMIN, params={"guest_id": guest_id})
    data = get_success_data(res)
    if isinstance(data, list):
        return data
    return data
