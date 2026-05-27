"""Composite setup helpers for multi-step test prerequisites.

Each fixture builds its preconditions from scratch using only PRD-declared
endpoints; the test harness restarts the server before every test, so every
fixture starts against an empty database.

Identity threading rule (PRD §2.1):
  * Member writes that are ownership-gated MUST use
    `make_member_headers(member_id)` — Member identity is
    entity_backed:Member and X-User-ID must equal the acting row's id.
  * MemberServices, LoyaltyManager, ComplianceOfficer are opaque
    operator identifiers — shared header constants are fine.

Setup helpers use `get_success_data` from the framework so a failed setup
surfaces as a clear "setup failed" error rather than a misleading assertion
failure deep inside a test.
"""
from typing import Optional, Tuple, Dict, Any, List

from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_property_payload,
    create_member_payload,
    create_host_payload,
    create_gaming_session_payload,
    create_comp_room_booking_payload,
    create_host_assignment_payload,
    create_self_exclusion_payload,
    create_annual_reset_run_payload,
)
from .test_users import (
    TEST_USERS,
    make_member_services_headers,
    make_loyalty_manager_headers,
    make_compliance_officer_headers,
    make_member_headers,
)


# ─── Clock control ────────────────────────────────────────────────────────

def set_clock(to_iso8601: str, officer_id: str = "co_1") -> None:
    """Pin the server's current_utc to a deterministic instant (PRD §2.11)."""
    get_success_data(
        api_client.set_clock(
            to_iso8601, make_compliance_officer_headers(officer_id),
        )
    )


# ─── Tier 1: Single-entity creates ────────────────────────────────────────

def create_property(
    name: str = "Caesars Palace LV",
    market_segment: str = "VEGAS_STRIP",
    base_room_rate_cents: int = 30000,
    officer_id: str = "co_1",
) -> dict:
    return get_success_data(
        api_client.create_property(
            create_property_payload(
                name=name,
                market_segment=market_segment,
                base_room_rate_cents=base_room_rate_cents,
            ),
            make_compliance_officer_headers(officer_id),
        )
    )


def create_member(
    property_id: str,
    full_name: str = "Test Member",
    email: str = "test@example.com",
    services_id: str = "ms_1",
) -> dict:
    return get_success_data(
        api_client.create_member(
            create_member_payload(
                home_property_id=property_id,
                full_name=full_name,
                email=email,
            ),
            make_member_services_headers(services_id),
        )
    )


def create_host(
    property_id: str,
    employee_email: str = "host@caesars.example",
    officer_id: str = "co_1",
) -> dict:
    return get_success_data(
        api_client.create_host(
            create_host_payload(
                home_property_id=property_id,
                employee_email=employee_email,
            ),
            make_compliance_officer_headers(officer_id),
        )
    )


def record_gaming_session(
    member_id: str,
    property_id: str,
    started_at: str,
    ended_at: str,
    game_type: str = "SLOTS",
    theoretical_loss_cents: int = 100000,
    services_id: str = "ms_1",
) -> dict:
    return get_success_data(
        api_client.create_gaming_session(
            create_gaming_session_payload(
                member_id=member_id,
                property_id=property_id,
                started_at=started_at,
                ended_at=ended_at,
                game_type=game_type,
                theoretical_loss_cents=theoretical_loss_cents,
            ),
            make_member_services_headers(services_id),
        )
    )


def get_member_version(member_id: str, manager_id: str = "lm_1") -> int:
    """Re-read Member to obtain the current `version` for OCC payloads."""
    data = get_success_data(
        api_client.get_member(
            member_id, make_loyalty_manager_headers(manager_id),
        )
    )
    return data["version"]


# ─── Tier 2: Member tier promotion helpers ────────────────────────────────

def promote_member_to_platinum(
    member_id: str,
    property_id: str,
    started_at: str = "2026-01-01T01:00:00Z",
    ended_at: str = "2026-01-01T02:00:00Z",
    services_id: str = "ms_1",
) -> dict:
    """Promote a GOLD member to PLATINUM via two SLOTS sessions spaced >1h
    apart so the rolling 60-minute velocity window never reaches the
    SUSPENDED threshold of 1_500_000 cents (PRD §3.4).

    PRD §3.3: SLOTS at GOLD: tier_credits_earned = loss/100 * 1.0 * 1.0.
    Two sessions of 750_000 cents each → 7500 TC + 7500 TC = 15000 TC,
    meeting PLATINUM threshold (>=15000). Each session's rolling window
    sum is 750_000 cents → at most FLAGGED (>= 500_000), never SUSPENDED.

    The first session uses the supplied started_at/ended_at. The second
    session is shifted forward by 2 hours to keep the rolling-window sums
    disjoint."""
    s1 = record_gaming_session(
        member_id=member_id,
        property_id=property_id,
        started_at=started_at,
        ended_at=ended_at,
        game_type="SLOTS",
        theoretical_loss_cents=750_000,
        services_id=services_id,
    )
    # Shift session 2 forward by 2 hours from session 1's end to keep the
    # rolling 60-min window from accumulating both sessions.
    s2_started_at = _shift_iso_by_hours(ended_at, 2)
    s2_ended_at = _shift_iso_by_hours(s2_started_at, 1)
    return record_gaming_session(
        member_id=member_id,
        property_id=property_id,
        started_at=s2_started_at,
        ended_at=s2_ended_at,
        game_type="SLOTS",
        theoretical_loss_cents=750_000,
        services_id=services_id,
    )


def _shift_iso_by_hours(iso: str, hours: int) -> str:
    """Add `hours` to an ISO-8601 Z-suffixed timestamp; return Z-suffixed."""
    from datetime import datetime, timedelta, timezone
    s = iso.replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt2 = dt + timedelta(hours=hours)
    out = dt2.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return out


def promote_member_to_diamond_from_platinum(
    member_id: str,
    property_id: str,
    started_at: str = "2026-01-02T01:00:00Z",
    ended_at: str = "2026-01-02T02:00:00Z",
    services_id: str = "ms_1",
) -> dict:
    """Promote a PLATINUM member to DIAMOND via three TABLE_GAMES sessions
    each ≤ velocity SUSPEND threshold and spaced > 1 hour apart so the
    rolling 60-minute velocity window never reaches 1_500_000 cents
    (PRD §3.4).

    PRD §3.3: TABLE_GAMES at PLATINUM: loss/100 * 2.0 * 1.25 = loss * 0.025.
    Three sessions of 1_200_000 cents each → 30000 TC each → 90000 TC
    added to existing 15000 ytd = 105000 ≥ 75000 DIAMOND threshold. Each
    session's rolling-window sum is 1_200_000 < 1_500_000 → at most
    FLAGGED, never SUSPENDED."""
    out = None
    cur_started = started_at
    cur_ended = ended_at
    for _ in range(3):
        out = record_gaming_session(
            member_id=member_id,
            property_id=property_id,
            started_at=cur_started,
            ended_at=cur_ended,
            game_type="TABLE_GAMES",
            theoretical_loss_cents=1_200_000,
            services_id=services_id,
        )
        cur_started = _shift_iso_by_hours(cur_ended, 2)
        cur_ended = _shift_iso_by_hours(cur_started, 1)
    return out


# ─── Tier 2: Booking and assignment lifecycle helpers ─────────────────────

def create_booking(
    member_id: str,
    property_id: str,
    expected_member_version: int,
    check_in: str = "2026-02-01T15:00:00Z",
    check_out: str = "2026-02-02T11:00:00Z",
    manager_id: str = "lm_1",
) -> dict:
    return get_success_data(
        api_client.create_comp_room_booking(
            create_comp_room_booking_payload(
                member_id=member_id,
                property_id=property_id,
                expected_member_version=expected_member_version,
                check_in=check_in,
                check_out=check_out,
            ),
            make_loyalty_manager_headers(manager_id),
        )
    )


def confirm_booking(booking_id: str, manager_id: str = "lm_1") -> dict:
    return get_success_data(
        api_client.confirm_comp_room_booking(
            booking_id, make_loyalty_manager_headers(manager_id),
        )
    )


def check_in_booking(booking_id: str, manager_id: str = "lm_1") -> dict:
    return get_success_data(
        api_client.check_in_comp_room_booking(
            booking_id, make_loyalty_manager_headers(manager_id),
        )
    )


def check_out_booking(booking_id: str, manager_id: str = "lm_1") -> dict:
    return get_success_data(
        api_client.check_out_comp_room_booking(
            booking_id, make_loyalty_manager_headers(manager_id),
        )
    )


def cancel_booking_as_manager(booking_id: str, manager_id: str = "lm_1") -> dict:
    return get_success_data(
        api_client.cancel_comp_room_booking(
            booking_id, make_loyalty_manager_headers(manager_id),
        )
    )


def create_host_assignment(
    member_id: str,
    host_id: str,
    expected_member_version: int,
    manager_id: str = "lm_alice",
) -> dict:
    return get_success_data(
        api_client.create_host_assignment(
            create_host_assignment_payload(
                member_id=member_id,
                host_id=host_id,
                expected_member_version=expected_member_version,
            ),
            make_loyalty_manager_headers(manager_id),
        )
    )


def approve_host_assignment(
    ha_id: str, manager_id: str = "lm_bob",
) -> dict:
    return get_success_data(
        api_client.approve_host_assignment(
            ha_id, make_loyalty_manager_headers(manager_id),
        )
    )


def self_exclude_member(
    member_id: str,
    exclusion_until: str = "2027-12-31T00:00:00Z",
    reason: str = "Self-exclusion test",
) -> dict:
    return get_success_data(
        api_client.create_self_exclusion(
            create_self_exclusion_payload(
                member_id=member_id,
                exclusion_until=exclusion_until,
                reason=reason,
            ),
            make_member_headers(member_id),
        )
    )


def schedule_annual_reset(
    reset_year: int = 2027,
    scheduled_for: str = "2028-01-01T00:00:00Z",
    officer_id: str = "co_1",
) -> dict:
    return get_success_data(
        api_client.create_annual_reset_run(
            create_annual_reset_run_payload(
                reset_year=reset_year, scheduled_for=scheduled_for,
            ),
            make_compliance_officer_headers(officer_id),
        )
    )


# ─── Tier 3: Composite bootstraps ─────────────────────────────────────────

def bootstrap_property_and_gold_member(
    clock: str = "2026-01-01T00:00:00Z",
    market_segment: str = "VEGAS_STRIP",
    base_room_rate_cents: int = 30000,
    property_name: str = "CP-LV",
    full_name: str = "Test Member",
    email: str = "test@example.com",
) -> Dict[str, Any]:
    """Pin the clock, create one Property, and create one GOLD member.

    Returns {"property": ..., "member": ...}. The member is in the default
    tier state (PRD §3.1: GOLD on registration)."""
    set_clock(clock)
    prop = create_property(
        name=property_name,
        market_segment=market_segment,
        base_room_rate_cents=base_room_rate_cents,
    )
    mem = create_member(
        property_id=prop["id"], full_name=full_name, email=email,
    )
    return {"property": prop, "member": mem}


def bootstrap_property_and_platinum_member(
    clock: str = "2026-01-01T00:00:00Z",
    market_segment: str = "VEGAS_STRIP",
    base_room_rate_cents: int = 30000,
    property_name: str = "CP-LV",
    full_name: str = "Test Member",
    email: str = "test@example.com",
    promo_started_at: str = "2026-01-01T01:00:00Z",
    promo_ended_at: str = "2026-01-01T02:00:00Z",
) -> Dict[str, Any]:
    """Bootstrap a Property and a Member already promoted to PLATINUM.

    Promotion is achieved via a $15,000 SLOTS gaming session (15000 TC).

    Returns {"property": ..., "member": <after promotion, refreshed>}.
    """
    ctx = bootstrap_property_and_gold_member(
        clock=clock,
        market_segment=market_segment,
        base_room_rate_cents=base_room_rate_cents,
        property_name=property_name,
        full_name=full_name,
        email=email,
    )
    promote_member_to_platinum(
        member_id=ctx["member"]["id"],
        property_id=ctx["property"]["id"],
        started_at=promo_started_at,
        ended_at=promo_ended_at,
    )
    # Refresh the member to read the bumped version and tier_status.
    refreshed = get_success_data(
        api_client.get_member(
            ctx["member"]["id"], make_loyalty_manager_headers("lm_1"),
        )
    )
    return {"property": ctx["property"], "member": refreshed}


def bootstrap_property_and_diamond_member(
    clock: str = "2026-01-01T00:00:00Z",
    base_room_rate_cents: int = 30000,
    full_name: str = "Diamond Member",
    email: str = "diamond@example.com",
) -> Dict[str, Any]:
    """Bootstrap a DIAMOND member via a multi-session ladder that respects
    the velocity SUSPEND threshold of 1_500_000 cents per rolling 60-min
    window (PRD §3.4).

    Ladder:
      1) GOLD → PLATINUM: two SLOTS sessions of 750_000 cents → 15000 TC,
         each window ≤ 750_000 cents (FLAGGED only).
      2) PLATINUM → DIAMOND: three TABLE_GAMES sessions of 1_200_000 cents
         each → 30000 TC * 3 = 90000 TC; 15000 + 90000 = 105000 ≥ 75000
         DIAMOND threshold. Each window ≤ 1_200_000 cents (FLAGGED only).

    Sessions are spaced > 1 hour apart so the rolling-window sums stay
    disjoint."""
    set_clock(clock)
    prop = create_property(base_room_rate_cents=base_room_rate_cents)
    mem = create_member(
        property_id=prop["id"], full_name=full_name, email=email,
    )
    # Step 1: GOLD → PLATINUM
    promote_member_to_platinum(
        member_id=mem["id"], property_id=prop["id"],
        started_at="2026-01-01T01:00:00Z",
        ended_at="2026-01-01T02:00:00Z",
    )
    # Step 2: PLATINUM → DIAMOND (start well after the platinum sessions).
    promote_member_to_diamond_from_platinum(
        member_id=mem["id"], property_id=prop["id"],
        started_at="2026-01-01T08:00:00Z",
        ended_at="2026-01-01T09:00:00Z",
    )
    refreshed = get_success_data(
        api_client.get_member(
            mem["id"], make_loyalty_manager_headers("lm_1"),
        )
    )
    return {"property": prop, "member": refreshed}


def bootstrap_platinum_with_pending_booking(
    clock: str = "2026-01-01T00:00:00Z",
    check_in: str = "2026-03-01T15:00:00Z",
    check_out: str = "2026-03-02T11:00:00Z",
) -> Dict[str, Any]:
    """Property + PLATINUM member + PENDING CompRoomBooking.

    Returns {"property", "member", "booking"} with member refreshed AFTER
    the booking is created (so member.version reflects the booking-create
    bump per PRD §3.6)."""
    ctx = bootstrap_property_and_platinum_member(clock=clock)
    booking = create_booking(
        member_id=ctx["member"]["id"],
        property_id=ctx["property"]["id"],
        expected_member_version=ctx["member"]["version"],
        check_in=check_in,
        check_out=check_out,
    )
    refreshed = get_success_data(
        api_client.get_member(
            ctx["member"]["id"], make_loyalty_manager_headers("lm_1"),
        )
    )
    return {"property": ctx["property"], "member": refreshed, "booking": booking}


def bootstrap_platinum_with_confirmed_booking(
    clock: str = "2026-01-01T00:00:00Z",
    check_in: str = "2026-03-01T15:00:00Z",
    check_out: str = "2026-03-02T11:00:00Z",
) -> Dict[str, Any]:
    """Property + PLATINUM member + CONFIRMED CompRoomBooking."""
    ctx = bootstrap_platinum_with_pending_booking(
        clock=clock, check_in=check_in, check_out=check_out,
    )
    confirmed = confirm_booking(ctx["booking"]["id"])
    return {
        "property": ctx["property"],
        "member": ctx["member"],
        "booking": confirmed,
    }


def bootstrap_platinum_with_completed_booking(
    clock: str = "2026-01-01T00:00:00Z",
    check_in: str = "2026-03-01T15:00:00Z",
    check_out: str = "2026-03-02T11:00:00Z",
    post_check_in_clock: str = "2026-03-01T16:00:00Z",
    post_check_out_clock: str = "2026-03-02T12:00:00Z",
) -> Dict[str, Any]:
    """Property + PLATINUM member + COMPLETED CompRoomBooking (full lifecycle).

    Walks PENDING → CONFIRMED → CHECKED_IN → COMPLETED with clock
    advances between transitions (PRD §3.6 requires clock >= check_in
    for check-in, clock >= check_out for check-out)."""
    ctx = bootstrap_platinum_with_confirmed_booking(
        clock=clock, check_in=check_in, check_out=check_out,
    )
    set_clock(post_check_in_clock)
    check_in_booking(ctx["booking"]["id"])
    set_clock(post_check_out_clock)
    completed = check_out_booking(ctx["booking"]["id"])
    return {
        "property": ctx["property"],
        "member": ctx["member"],
        "booking": completed,
    }


def bootstrap_two_managers_with_pending_host_assignment(
    clock: str = "2026-01-01T00:00:00Z",
    alice_id: str = "lm_alice",
    bob_id: str = "lm_bob",
) -> Dict[str, Any]:
    """Property + Host + PLATINUM member + PENDING_APPROVAL HostAssignment
    created by alice (creator), pending bob's approval (PRD §3.5)."""
    ctx = bootstrap_property_and_platinum_member(clock=clock)
    host = create_host(
        property_id=ctx["property"]["id"],
        employee_email=f"host-{ctx['property']['id'][:8]}@caesars.example",
    )
    ha = create_host_assignment(
        member_id=ctx["member"]["id"],
        host_id=host["id"],
        expected_member_version=ctx["member"]["version"],
        manager_id=alice_id,
    )
    refreshed = get_success_data(
        api_client.get_member(
            ctx["member"]["id"], make_loyalty_manager_headers(alice_id),
        )
    )
    return {
        "property": ctx["property"],
        "member": refreshed,
        "host": host,
        "host_assignment": ha,
        "alice_id": alice_id,
        "bob_id": bob_id,
    }


def bootstrap_member_with_active_host_assignment(
    clock: str = "2026-01-01T00:00:00Z",
    alice_id: str = "lm_alice",
    bob_id: str = "lm_bob",
) -> Dict[str, Any]:
    """Property + Host + PLATINUM member + ACTIVE HostAssignment (after
    bob's approval, PRD §3.5). Returns refreshed member with
    assigned_host_id = host.id."""
    ctx = bootstrap_two_managers_with_pending_host_assignment(
        clock=clock, alice_id=alice_id, bob_id=bob_id,
    )
    approved_ha = approve_host_assignment(
        ctx["host_assignment"]["id"], manager_id=bob_id,
    )
    refreshed = get_success_data(
        api_client.get_member(
            ctx["member"]["id"], make_loyalty_manager_headers(alice_id),
        )
    )
    return {
        "property": ctx["property"],
        "member": refreshed,
        "host": ctx["host"],
        "host_assignment": approved_ha,
        "alice_id": alice_id,
        "bob_id": bob_id,
    }


def bootstrap_cascade_setup(
    clock: str = "2026-11-01T00:00:00Z",
    check_in: str = "2026-12-01T15:00:00Z",
    check_out: str = "2026-12-02T11:00:00Z",
) -> Dict[str, Any]:
    """PRD §3.7 deep-cascade setup: Property + Host + PLATINUM member with
    BOTH an ACTIVE HostAssignment AND a CONFIRMED CompRoomBooking.

    Tests issue a self-exclusion on this member and observe the three-hop
    cascade: member.exclusion_status → EXCLUDED; ha → REVOKED; booking →
    CANCELLED; member.assigned_host_id → null."""
    ctx = bootstrap_member_with_active_host_assignment(clock=clock)
    booking = create_booking(
        member_id=ctx["member"]["id"],
        property_id=ctx["property"]["id"],
        expected_member_version=ctx["member"]["version"],
        check_in=check_in,
        check_out=check_out,
    )
    confirmed = confirm_booking(booking["id"])
    refreshed = get_success_data(
        api_client.get_member(
            ctx["member"]["id"],
            make_loyalty_manager_headers(ctx["alice_id"]),
        )
    )
    return {
        "property": ctx["property"],
        "member": refreshed,
        "host": ctx["host"],
        "host_assignment": ctx["host_assignment"],
        "booking": confirmed,
        "alice_id": ctx["alice_id"],
        "bob_id": ctx["bob_id"],
    }


# ─── Tier 4: Velocity / threshold targeting helpers ───────────────────────

def bootstrap_member_at_velocity_just_below_flag(
    clock: str = "2026-05-01T00:00:00Z",
) -> Dict[str, Any]:
    """Bootstrap a GOLD member with no prior sessions, ready to record a
    single session whose total over a 60-min window can be tuned to
    exactly trip or stay below the FLAG threshold."""
    return bootstrap_property_and_gold_member(clock=clock)


def bootstrap_platinum_member_with_pending_booking_pre_velocity(
    clock: str = "2026-11-15T00:00:00Z",
    check_in: str = "2026-12-15T15:00:00Z",
    check_out: str = "2026-12-16T11:00:00Z",
) -> Dict[str, Any]:
    """Property + PLATINUM member + PENDING CompRoomBooking. Tests then
    record three 60-min-window SLOTS sessions summing to 1_500_000 cents
    to drive the member into SUSPENDED — observing the booking cascade
    (PRD §3.4)."""
    return bootstrap_platinum_with_pending_booking(
        clock=clock, check_in=check_in, check_out=check_out,
    )


# ─── Tier 5: Annual reset / occupancy fixtures ────────────────────────────

def bootstrap_scheduled_annual_reset(
    clock_before: str = "2027-06-01T00:00:00Z",
    reset_year: int = 2027,
    scheduled_for: str = "2028-01-01T00:00:00Z",
) -> Dict[str, Any]:
    """Schedule an AnnualResetRun with the clock pinned BEFORE
    scheduled_for. Tests can then either /cancel (clock < scheduled_for,
    PRD §3.8) or advance the clock and /execute."""
    set_clock(clock_before)
    ar = schedule_annual_reset(
        reset_year=reset_year, scheduled_for=scheduled_for,
    )
    return {"annual_reset_run": ar}


def bootstrap_due_annual_reset_with_two_platinum_members(
    clock_before_scheduled: str = "2027-11-01T00:00:00Z",
    reset_year: int = 2027,
    scheduled_for: str = "2028-01-01T00:00:00Z",
    clock_after_scheduled: str = "2028-01-01T01:00:00Z",
) -> Dict[str, Any]:
    """Two non-excluded members each at known tier_credits_lifetime, plus
    a SCHEDULED AnnualResetRun whose `scheduled_for` lies in the past
    (clock advanced). Tests trigger /execute and assert the lifetime
    invariant + reset count.

    PRD §3.3: SLOTS at GOLD: 1 TC per $1 loss. We use 2_000_000 cents on
    member A (20000 TC) and 3_000_000 cents on member B (30000 TC) —
    both above PLATINUM threshold."""
    set_clock(clock_before_scheduled)
    prop = create_property()
    ma = create_member(
        property_id=prop["id"], full_name="Member A", email="ma@example.com",
    )
    mb = create_member(
        property_id=prop["id"], full_name="Member B", email="mb@example.com",
    )
    # Member A: 2 SLOTS sessions of 1_000_000 cents each, spaced > 1 hour
    # apart → 10000 TC + 10000 TC = 20000 TC lifetime. Each rolling window
    # sum is 1_000_000 < 1_500_000 → FLAGGED only (PRD §3.4).
    record_gaming_session(
        member_id=ma["id"], property_id=prop["id"],
        started_at="2027-11-01T01:00:00Z", ended_at="2027-11-01T02:00:00Z",
        game_type="SLOTS", theoretical_loss_cents=1_000_000,
    )
    record_gaming_session(
        member_id=ma["id"], property_id=prop["id"],
        started_at="2027-11-01T04:00:00Z", ended_at="2027-11-01T05:00:00Z",
        game_type="SLOTS", theoretical_loss_cents=1_000_000,
    )
    # Member B: 3 SLOTS sessions of 1_000_000 cents each, spaced > 1 hour
    # apart → 30000 TC lifetime.
    record_gaming_session(
        member_id=mb["id"], property_id=prop["id"],
        started_at="2027-11-01T07:00:00Z", ended_at="2027-11-01T08:00:00Z",
        game_type="SLOTS", theoretical_loss_cents=1_000_000,
    )
    record_gaming_session(
        member_id=mb["id"], property_id=prop["id"],
        started_at="2027-11-01T10:00:00Z", ended_at="2027-11-01T11:00:00Z",
        game_type="SLOTS", theoretical_loss_cents=1_000_000,
    )
    record_gaming_session(
        member_id=mb["id"], property_id=prop["id"],
        started_at="2027-11-01T13:00:00Z", ended_at="2027-11-01T14:00:00Z",
        game_type="SLOTS", theoretical_loss_cents=1_000_000,
    )
    ar = schedule_annual_reset(
        reset_year=reset_year, scheduled_for=scheduled_for,
    )
    set_clock(clock_after_scheduled)
    # Refresh both members so the test can assert their post-reset state.
    refreshed_a = get_success_data(
        api_client.get_member(
            ma["id"], make_loyalty_manager_headers("lm_1"),
        )
    )
    refreshed_b = get_success_data(
        api_client.get_member(
            mb["id"], make_loyalty_manager_headers("lm_1"),
        )
    )
    return {
        "property": prop,
        "member_a": refreshed_a,
        "member_b": refreshed_b,
        "annual_reset_run": ar,
    }


def bootstrap_due_annual_reset_with_only_excluded_member(
    clock_before_scheduled: str = "2027-12-01T00:00:00Z",
    reset_year: int = 2027,
    scheduled_for: str = "2028-01-01T00:00:00Z",
    clock_after_scheduled: str = "2028-01-01T01:00:00Z",
    exclusion_until: str = "2029-12-02T00:00:00Z",
) -> Dict[str, Any]:
    """Empty-eligible-set boundary: the only member is EXCLUDED, so
    /execute must produce members_reset_count == 0 and the lifetime
    invariant remains zero (PRD §3.8)."""
    set_clock(clock_before_scheduled)
    prop = create_property()
    mem = create_member(
        property_id=prop["id"], full_name="Sole Excluded",
        email="excluded@example.com",
    )
    self_exclude_member(
        member_id=mem["id"], exclusion_until=exclusion_until,
        reason="exclude all",
    )
    ar = schedule_annual_reset(
        reset_year=reset_year, scheduled_for=scheduled_for,
    )
    set_clock(clock_after_scheduled)
    return {
        "property": prop, "member": mem, "annual_reset_run": ar,
    }


def bootstrap_property_with_n_overlapping_bookings(
    n: int,
    clock: str = "2026-12-01T00:00:00Z",
    check_in: str = "2027-01-10T15:00:00Z",
    check_out: str = "2027-01-12T11:00:00Z",
) -> Dict[str, Any]:
    """Property + n PLATINUM members each holding a PENDING booking on the
    same overlapping window. Used to demonstrate aggregate-capacity
    overlap rejection at n+1 (PRD §3.6 occupancy cap = 20).

    Returns the property and a list of n bookings."""
    set_clock(clock)
    prop = create_property()
    bookings: List[dict] = []
    for i in range(n):
        mem = create_member(
            property_id=prop["id"],
            full_name=f"Overflow M {i}",
            email=f"of{i}@example.com",
        )
        promote_member_to_platinum(
            member_id=mem["id"], property_id=prop["id"],
            started_at=f"2026-12-01T{i:02d}:30:00Z",
            ended_at=f"2026-12-01T{i:02d}:45:00Z",
        )
        v = get_member_version(mem["id"])
        bk = create_booking(
            member_id=mem["id"], property_id=prop["id"],
            expected_member_version=v,
            check_in=check_in, check_out=check_out,
        )
        bookings.append(bk)
    return {"property": prop, "bookings": bookings}


def bootstrap_two_managers_for_occ_test(
    clock: str = "2026-01-01T00:00:00Z",
) -> Dict[str, Any]:
    """Property + two Hosts + PLATINUM member, ready for two sequential
    POST /host-assignments to demonstrate OCC stale-version rejection on
    the second call (PRD §2.5)."""
    ctx = bootstrap_property_and_platinum_member(clock=clock)
    h1 = create_host(
        property_id=ctx["property"]["id"],
        employee_email="h1@caesars.example",
    )
    h2 = create_host(
        property_id=ctx["property"]["id"],
        employee_email="h2@caesars.example",
    )
    return {
        "property": ctx["property"],
        "member": ctx["member"],
        "host_1": h1,
        "host_2": h2,
    }


def bootstrap_cyclic_exclusion_setup(
    clock_first: str = "2026-01-01T00:00:00Z",
    clock_after_expiry: str = "2027-01-03T00:00:00Z",
    exclusion_until: str = "2027-01-02T00:00:00Z",
) -> Dict[str, Any]:
    """Member who has self-excluded once and then reinstated (after the
    clock advanced past exclusion_until). Ready for a second
    self-exclusion to demonstrate the REINSTATED→EXCLUDED cycle
    (PRD §3.7)."""
    ctx = bootstrap_property_and_gold_member(clock=clock_first)
    se1 = self_exclude_member(
        member_id=ctx["member"]["id"],
        exclusion_until=exclusion_until,
        reason="first cycle",
    )
    set_clock(clock_after_expiry)
    get_success_data(
        api_client.reinstate_self_exclusion(
            se1["id"], make_member_headers(ctx["member"]["id"]),
        )
    )
    refreshed = get_success_data(
        api_client.get_member(
            ctx["member"]["id"], make_loyalty_manager_headers("lm_1"),
        )
    )
    return {
        "property": ctx["property"],
        "member": refreshed,
        "first_self_exclusion": se1,
    }
