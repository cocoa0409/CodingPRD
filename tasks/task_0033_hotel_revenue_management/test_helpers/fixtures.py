"""Composite setup helpers for the Hotel Revenue Management test suite.

The PRD's lifecycle has many interlocking phases — RoomType, Room,
MaintenanceBlock, Channel, RatePlan, ChannelRatePlanMapping, RateOverride,
OverbookingPolicy, Reservation (PENDING -> CONFIRMED -> CHECKED_IN ->
CHECKED_OUT, with detours through CANCELLED, NO_SHOW, WALKED_OUT) — and
most interesting tests need the system in a non-initial state. This module
encapsulates the common multi-call setup sequences.

Identity (PRD §2.1): every role's X-User-ID is opaque; identity is not
threaded against entity ids. The only identity rule the helpers honor is
segregation-of-duties on RateOverride.approve / reject — submitter's
X-User-ID and approver's X-User-ID must differ. The helpers default to a
fresh analyst id and a different fresh manager id whenever both calls
are made within one helper.

Setup calls use get_success_data (lenient validator) so that broken
preconditions surface as obvious 'Setup failed' mismatches rather than
confusing assertion errors.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    check_in_payload,
    create_channel_payload,
    create_channel_rate_plan_mapping_payload,
    create_maintenance_block_payload,
    create_overbooking_policy_payload,
    create_rate_override_payload,
    create_rate_plan_payload,
    create_reservation_payload,
    create_room_payload,
    create_room_type_payload,
    unique_priority_rank,
)
from .test_users import (
    TEST_USERS,
    make_admin_headers,
    make_agent_headers,
    make_analyst_headers,
    make_clerk_headers,
    make_housekeeping_headers,
    make_manager_headers,
)


# ===========================================================================
# Time helpers (PRD §2.4 — ISO 8601 UTC with 3 fractional digits)
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with exactly 3 fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def parse_iso(s: str) -> datetime:
    s2 = s.replace("Z", "+00:00")
    return datetime.fromisoformat(s2)


def add_hours(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(hours=n))


def add_days(s: str, n: int) -> str:
    return iso_z(parse_iso(s) + timedelta(days=n))


def date_only(s: str) -> str:
    """Reduce an ISO 8601 instant to its YYYY-MM-DD prefix."""
    return s.split("T")[0]


def date_plus_days(date_yyyy_mm_dd: str, n: int) -> str:
    """Add N days to a YYYY-MM-DD string and return YYYY-MM-DD."""
    d = datetime.strptime(date_yyyy_mm_dd, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return (d + timedelta(days=n)).strftime("%Y-%m-%d")


def date_at_midnight(date_yyyy_mm_dd: str) -> str:
    """Convert a YYYY-MM-DD to its 00:00:00.000Z instant."""
    return f"{date_yyyy_mm_dd}T00:00:00.000Z"


# ===========================================================================
# Test-driving wrappers
# ===========================================================================
def advance_clock(to_iso: str,
                  headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """POST /_clock/advance (PlatformAdmin only, PRD §3.7)."""
    res = api_client.advance_clock(
        to_iso, headers or TEST_USERS["admin_headers"],
    )
    return get_success_data(res)


def get_clock(headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    res = api_client.get_clock(headers or TEST_USERS["admin_headers"])
    return get_success_data(res)


# ===========================================================================
# Single-entity setup wrappers
# ===========================================================================
def create_room_type(*,
                     base_rate_cents: int = 20000,
                     max_occupancy: int = 2,
                     code: Optional[str] = None,
                     name: Optional[str] = None,
                     headers: Optional[Dict[str, str]] = None,
                     **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1 — RoomType create. PlatformAdmin only."""
    payload = create_room_type_payload(
        code=code, name=name,
        base_rate_cents=base_rate_cents, max_occupancy=max_occupancy,
        **overrides,
    )
    res = api_client.create_room_type(
        payload, headers or TEST_USERS["admin_headers"],
    )
    return get_success_data(res)


def create_room(*, room_type_id: str,
                room_number: Optional[str] = None,
                headers: Optional[Dict[str, str]] = None,
                **overrides: Any) -> Dict[str, Any]:
    payload = create_room_payload(
        room_type_id=room_type_id, room_number=room_number, **overrides,
    )
    res = api_client.create_room(
        payload, headers or TEST_USERS["admin_headers"],
    )
    return get_success_data(res)


def create_channel(*,
                   channel_type: str = "DIRECT",
                   commission_basis_points: int = 0,
                   priority_rank: Optional[int] = None,
                   code: Optional[str] = None,
                   headers: Optional[Dict[str, str]] = None,
                   **overrides: Any) -> Dict[str, Any]:
    payload = create_channel_payload(
        code=code, channel_type=channel_type,
        commission_basis_points=commission_basis_points,
        priority_rank=(priority_rank
                       if priority_rank is not None
                       else unique_priority_rank()),
        **overrides,
    )
    res = api_client.create_channel(
        payload, headers or TEST_USERS["admin_headers"],
    )
    return get_success_data(res)


def create_rate_plan(*, room_type_id: str,
                     refund_tier_code: str = "FLEXIBLE",
                     modification_allowed: bool = True,
                     code: Optional[str] = None,
                     headers: Optional[Dict[str, str]] = None,
                     **overrides: Any) -> Dict[str, Any]:
    payload = create_rate_plan_payload(
        room_type_id=room_type_id,
        code=code,
        refund_tier_code=refund_tier_code,
        modification_allowed=modification_allowed,
        **overrides,
    )
    res = api_client.create_rate_plan(
        payload, headers or TEST_USERS["manager_headers"],
    )
    return get_success_data(res)


def create_mapping(*, channel_id: str, rate_plan_id: str,
                   inventory_share_basis_points: int = 10000,
                   headers: Optional[Dict[str, str]] = None,
                   **overrides: Any) -> Dict[str, Any]:
    payload = create_channel_rate_plan_mapping_payload(
        channel_id=channel_id,
        rate_plan_id=rate_plan_id,
        inventory_share_basis_points=inventory_share_basis_points,
        **overrides,
    )
    res = api_client.create_channel_rate_plan_mapping(
        payload, headers or TEST_USERS["manager_headers"],
    )
    return get_success_data(res)


def create_overbooking_policy(*, room_type_id: str, stay_date: str,
                              overbook_ratio_basis_points: int = 1500,
                              estimated_no_show_probability_basis_points: int = 1000,
                              walkout_compensation_cents: int = 15000,
                              headers: Optional[Dict[str, str]] = None,
                              **overrides: Any) -> Dict[str, Any]:
    payload = create_overbooking_policy_payload(
        room_type_id=room_type_id,
        stay_date=stay_date,
        overbook_ratio_basis_points=overbook_ratio_basis_points,
        estimated_no_show_probability_basis_points=estimated_no_show_probability_basis_points,
        walkout_compensation_cents=walkout_compensation_cents,
        **overrides,
    )
    res = api_client.create_overbooking_policy(
        payload, headers or TEST_USERS["manager_headers"],
    )
    return get_success_data(res)


def create_reservation(*, room_type_id: str, rate_plan_id: str,
                       channel_id: str,
                       check_in_date: str, check_out_date: str,
                       guest_name: Optional[str] = None,
                       headers: Optional[Dict[str, str]] = None,
                       **overrides: Any) -> Dict[str, Any]:
    payload = create_reservation_payload(
        guest_name=guest_name,
        room_type_id=room_type_id,
        rate_plan_id=rate_plan_id,
        channel_id=channel_id,
        check_in_date=check_in_date,
        check_out_date=check_out_date,
        **overrides,
    )
    res = api_client.create_reservation(
        payload, headers or TEST_USERS["agent_headers"],
    )
    return get_success_data(res)


def confirm_reservation(reservation_id: str,
                        headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §3.5 — ReservationsAgent only."""
    res = api_client.confirm_reservation(
        reservation_id, headers or TEST_USERS["agent_headers"],
    )
    return get_success_data(res)


def cancel_reservation(reservation_id: str,
                       headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    res = api_client.cancel_reservation(
        reservation_id, headers or TEST_USERS["agent_headers"],
    )
    return get_success_data(res)


def get_reservation(reservation_id: str,
                    headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    res = api_client.get_reservation(
        reservation_id, headers or TEST_USERS["agent_headers"],
    )
    return get_success_data(res)


# ===========================================================================
# Tier 2: Composite distribution scaffolds
# ===========================================================================
def setup_basic_distribution(
    *,
    base_rate_cents: int = 20000,
    max_occupancy: int = 2,
    n_rooms: int = 4,
    refund_tier_code: str = "FLEXIBLE",
    modification_allowed: bool = True,
    channel_type: str = "DIRECT",
    commission_basis_points: int = 0,
    inventory_share_basis_points: int = 10000,
    n_channels: int = 1,
) -> Dict[str, Any]:
    """The minimum scaffold required to create + confirm a Reservation:
    a RoomType, N ACTIVE rooms bound to it, a RatePlan on that room type,
    a Channel, and a ChannelRatePlanMapping that wires them together at
    100% inventory share by default.

    Returns a dict {room_type, rooms, rate_plan, channel, mapping,
    channels[], rate_plans[], mappings[]}.

    When n_channels > 1, additional (rate_plan, channel, mapping) triples
    are created — each with its own RatePlan at the requested
    inventory_share_basis_points so that PRD §3.2's per-rate-plan
    10000-bp cap is not violated. Per PRD §3.5 the per-channel inventory
    cap is bounded by floor(physical_capacity * share / 10000) on a
    SINGLE channel; reaching the overbooking ceiling for a (room_type,
    date) therefore requires distributing reservations across multiple
    channel-and-rate-plan pairs. The first triple in the list is the
    legacy `channel`/`rate_plan`/`mapping` fields; the full list lives
    in `channels`/`rate_plans`/`mappings`.
    """
    rt = create_room_type(
        base_rate_cents=base_rate_cents, max_occupancy=max_occupancy,
    )
    rooms = [create_room(room_type_id=rt["id"]) for _ in range(n_rooms)]
    plans: List[Dict[str, Any]] = []
    channels: List[Dict[str, Any]] = []
    mappings: List[Dict[str, Any]] = []
    for _ in range(max(1, n_channels)):
        plan = create_rate_plan(
            room_type_id=rt["id"],
            refund_tier_code=refund_tier_code,
            modification_allowed=modification_allowed,
        )
        channel = create_channel(
            channel_type=channel_type,
            commission_basis_points=commission_basis_points,
        )
        mapping = create_mapping(
            channel_id=channel["id"], rate_plan_id=plan["id"],
            inventory_share_basis_points=inventory_share_basis_points,
        )
        plans.append(plan)
        channels.append(channel)
        mappings.append(mapping)
    return {
        "room_type": rt,
        "rooms": rooms,
        "rate_plan": plans[0],
        "channel": channels[0],
        "mapping": mappings[0],
        "rate_plans": plans,
        "channels": channels,
        "mappings": mappings,
    }


def setup_distribution_with_two_ota_channels(
    *,
    base_rate_cents: int = 20000,
    n_rooms: int = 4,
    ota1_commission_bp: int = 1500,
    ota2_commission_bp: int = 1500,
) -> Dict[str, Any]:
    """RoomType + N rooms + RatePlan + 2 OTA channels each mapped at 50%
    inventory share. Used for rate-parity scenarios (PRD §3.3)."""
    rt = create_room_type(base_rate_cents=base_rate_cents)
    rooms = [create_room(room_type_id=rt["id"]) for _ in range(n_rooms)]
    plan = create_rate_plan(room_type_id=rt["id"])
    ota1 = create_channel(channel_type="OTA",
                          commission_basis_points=ota1_commission_bp)
    ota2 = create_channel(channel_type="OTA",
                          commission_basis_points=ota2_commission_bp)
    map1 = create_mapping(channel_id=ota1["id"], rate_plan_id=plan["id"],
                          inventory_share_basis_points=5000)
    map2 = create_mapping(channel_id=ota2["id"], rate_plan_id=plan["id"],
                          inventory_share_basis_points=5000)
    return {
        "room_type": rt, "rooms": rooms, "rate_plan": plan,
        "ota1": ota1, "ota2": ota2, "map1": map1, "map2": map2,
    }


# ===========================================================================
# Tier 3: Reservation lifecycle shortcuts
# ===========================================================================
def create_pending_reservation(
    scaffold: Dict[str, Any],
    *,
    check_in_date: str,
    check_out_date: str,
    guest_name: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    channel_index: int = 0,
) -> Dict[str, Any]:
    """Create a Reservation in PENDING using a scaffold from
    setup_basic_distribution().

    `channel_index` selects which (channel, rate_plan) pair to use when
    the scaffold was built with n_channels > 1. Defaults to 0 (the
    legacy single-channel path). PRD §3.5 binds a Reservation to a
    specific (channel_id, rate_plan_id) pair, so callers that need to
    saturate per-channel inventory caps must rotate this index.
    """
    channels = scaffold.get("channels") or [scaffold["channel"]]
    plans = scaffold.get("rate_plans") or [scaffold["rate_plan"]]
    idx = channel_index % len(channels)
    return create_reservation(
        room_type_id=scaffold["room_type"]["id"],
        rate_plan_id=plans[idx]["id"],
        channel_id=channels[idx]["id"],
        check_in_date=check_in_date,
        check_out_date=check_out_date,
        guest_name=guest_name,
        headers=headers,
    )


def create_confirmed_reservation(
    scaffold: Dict[str, Any],
    *,
    check_in_date: str,
    check_out_date: str,
    guest_name: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
    channel_index: int = 0,
) -> Dict[str, Any]:
    """Create + confirm a Reservation. Returns the CONFIRMED entity."""
    res = create_pending_reservation(
        scaffold,
        check_in_date=check_in_date, check_out_date=check_out_date,
        guest_name=guest_name, headers=headers,
        channel_index=channel_index,
    )
    return confirm_reservation(
        res["id"], headers or TEST_USERS["agent_headers"],
    )


def create_checked_in_reservation(
    scaffold: Dict[str, Any],
    *,
    check_in_date: str,
    check_out_date: str,
    room_id: Optional[str] = None,
    headers_clerk: Optional[Dict[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create -> confirm -> check-in a Reservation. Advances the clock to
    check_in_date 12:00 so check-in's 'Today >= check_in_date' precondition
    holds. Returns (reservation, room_used)."""
    advance_clock(f"{check_in_date}T12:00:00.000Z")
    res = create_confirmed_reservation(
        scaffold,
        check_in_date=check_in_date, check_out_date=check_out_date,
    )
    chosen_room = scaffold["rooms"][0] if room_id is None else \
        next(r for r in scaffold["rooms"] if r["id"] == room_id)
    payload = check_in_payload(room_id=chosen_room["id"])
    api_resp = api_client.check_in_reservation(
        res["id"], payload,
        headers_clerk or TEST_USERS["clerk_headers"],
    )
    res2 = get_success_data(api_resp)
    return res2, chosen_room


# ===========================================================================
# Tier 3: RateOverride approval-chain shortcuts
# ===========================================================================
def submit_rate_override(
    *,
    room_type_id: str,
    stay_date: str,
    proposed_rate_cents: int = 25000,
    recommendation_source: str = "MANUAL_OVERRIDE",
    analyst_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Create + submit a RateOverride. Returns it in PENDING_APPROVAL.

    PRD §3.3: RevenueAnalyst creates and submits; the server records the
    submitter's X-User-ID for later segregation-of-duties checks.
    """
    headers = analyst_headers or TEST_USERS["analyst_headers"]
    payload = create_rate_override_payload(
        room_type_id=room_type_id,
        stay_date=stay_date,
        proposed_rate_cents=proposed_rate_cents,
        recommendation_source=recommendation_source,
    )
    create_resp = api_client.create_rate_override(payload, headers)
    draft = get_success_data(create_resp)
    submit_resp = api_client.submit_rate_override(draft["id"], headers)
    return get_success_data(submit_resp)


def approve_rate_override(
    override_id: str,
    *,
    manager_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Approve a PENDING_APPROVAL rate override. PRD §2.9 / §3.3 require
    the approver's X-User-ID to differ from the submitter's. The default
    manager_headers ('manager-001') differs from the default analyst
    headers ('analyst-001')."""
    res = api_client.approve_rate_override(
        override_id, manager_headers or TEST_USERS["manager_headers"],
    )
    return get_success_data(res)


def submit_and_approve_rate_override(
    *,
    room_type_id: str,
    stay_date: str,
    proposed_rate_cents: int = 25000,
    analyst_headers: Optional[Dict[str, str]] = None,
    manager_headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """End-to-end: create + submit + approve a RateOverride. Returns it
    in APPROVED with applied_rate_cents == proposed_rate_cents."""
    pending = submit_rate_override(
        room_type_id=room_type_id, stay_date=stay_date,
        proposed_rate_cents=proposed_rate_cents,
        analyst_headers=analyst_headers,
    )
    return approve_rate_override(
        pending["id"], manager_headers=manager_headers,
    )


# ===========================================================================
# Tier 4: Threshold targeting — overbooking ceiling boundary
# ===========================================================================
def setup_room_type_at_overbooking_boundary(
    *,
    physical_capacity: int,
    overbook_ratio_basis_points: int,
    stay_date: str,
    base_rate_cents: int = 20000,
    refund_tier_code: str = "FLEXIBLE",
    n_channels: Optional[int] = None,
) -> Dict[str, Any]:
    """Build a fresh RoomType + N rooms + RatePlan + DIRECT channel +
    OverbookingPolicy(stay_date, ratio). Returns a scaffold dict whose
    physical_capacity equals the requested integer count. Computed
    ceiling = physical_capacity + floor(physical_capacity * ratio / 10000).

    Per PRD §3.5 the per-channel inventory cap on a single channel at
    100% inventory_share is floor(physical_capacity * 1.0) =
    physical_capacity. To pre-fill or test confirmations up to the
    overbooking ceiling (which strictly exceeds physical_capacity when
    ratio > 0), reservations must be distributed across multiple
    channel-and-rate-plan pairs. We default `n_channels` so that the
    aggregate per-channel cap covers the ceiling: n_channels =
    ceil(ceiling / physical_capacity).
    """
    ceiling = physical_capacity + (
        physical_capacity * overbook_ratio_basis_points
    ) // 10000
    if n_channels is None:
        # ceil(ceiling / physical_capacity)
        n_channels = max(1, -(-ceiling // max(1, physical_capacity)))
    scaffold = setup_basic_distribution(
        base_rate_cents=base_rate_cents,
        n_rooms=physical_capacity,
        refund_tier_code=refund_tier_code,
        channel_type="DIRECT",
        commission_basis_points=0,
        inventory_share_basis_points=10000,
        n_channels=n_channels,
    )
    policy = create_overbooking_policy(
        room_type_id=scaffold["room_type"]["id"],
        stay_date=stay_date,
        overbook_ratio_basis_points=overbook_ratio_basis_points,
        estimated_no_show_probability_basis_points=0,
        walkout_compensation_cents=15000,
    )
    scaffold["overbooking_policy"] = policy
    scaffold["physical_capacity"] = physical_capacity
    scaffold["overbook_ratio_basis_points"] = overbook_ratio_basis_points
    scaffold["ceiling"] = ceiling
    return scaffold


def fill_reservations_to_count(
    scaffold: Dict[str, Any],
    *,
    check_in_date: str,
    check_out_date: str,
    count: int,
) -> List[Dict[str, Any]]:
    """Create + confirm `count` reservations against scaffold's
    (room_type, channels, rate_plans) for the date window. Reservations
    are round-robined across the available channels so per-channel
    inventory caps (PRD §3.5: floor(physical_capacity * share/10000)
    per channel) do not pre-empt the overbooking-ceiling check.
    Returns the list of CONFIRMED reservation entities."""
    out: List[Dict[str, Any]] = []
    n_channels = len(scaffold.get("channels") or [scaffold["channel"]])
    for i in range(count):
        res = create_confirmed_reservation(
            scaffold,
            check_in_date=check_in_date, check_out_date=check_out_date,
            guest_name=f"FillerGuest-{i}",
            channel_index=i % n_channels,
        )
        out.append(res)
    return out


def setup_with_n_confirmed_for_date(
    *,
    physical_capacity: int = 4,
    overbook_ratio_basis_points: int = 2500,
    stay_date: str = "2026-12-25",
    initial_confirmed: int = 4,
    base_rate_cents: int = 20000,
    refund_tier_code: str = "FLEXIBLE",
) -> Dict[str, Any]:
    """Build a scaffold and pre-fill it with initial_confirmed CONFIRMED
    reservations spanning a single night. The scaffold dict gains the
    field 'reservations' with the pre-filled list. The scaffold has
    ceil(ceiling / physical_capacity) channels so the pre-fill can
    saturate physical capacity AND the overbooking allowance without
    being pre-empted by a single channel's inventory cap (PRD §3.5)."""
    check_in = stay_date
    check_out = date_plus_days(stay_date, 1)
    scaffold = setup_room_type_at_overbooking_boundary(
        physical_capacity=physical_capacity,
        overbook_ratio_basis_points=overbook_ratio_basis_points,
        stay_date=stay_date,
        base_rate_cents=base_rate_cents,
        refund_tier_code=refund_tier_code,
    )
    scaffold["check_in_date"] = check_in
    scaffold["check_out_date"] = check_out
    scaffold["reservations"] = fill_reservations_to_count(
        scaffold,
        check_in_date=check_in, check_out_date=check_out,
        count=initial_confirmed,
    )
    # The next free channel index after the pre-fill; tests that confirm
    # one more reservation should use this so the new reservation lands
    # on a channel that still has slots remaining (PRD §3.5
    # ERR_INVENTORY_EXHAUSTED would otherwise pre-empt the overbooking
    # check).
    n_channels = len(scaffold.get("channels") or [scaffold["channel"]])
    scaffold["next_channel_index"] = initial_confirmed % n_channels
    scaffold["n_channels"] = n_channels
    return scaffold


# ===========================================================================
# Tier 4: Channel-share boundary
# ===========================================================================
def setup_channel_share_boundary(
    *,
    physical_capacity: int = 4,
    inventory_share_basis_points: int = 2500,
    base_rate_cents: int = 20000,
) -> Dict[str, Any]:
    """Build a single-channel scaffold whose channel_share for `physical_
    capacity` rooms at the given inventory share equals
    floor(physical_capacity * inventory_share / 10000).

    For physical_capacity=4 and share=2500bp → channel_share = floor(1.0) = 1.
    """
    scaffold = setup_basic_distribution(
        base_rate_cents=base_rate_cents,
        n_rooms=physical_capacity,
        channel_type="DIRECT",
        commission_basis_points=0,
        inventory_share_basis_points=inventory_share_basis_points,
    )
    scaffold["physical_capacity"] = physical_capacity
    scaffold["channel_share"] = (
        physical_capacity * inventory_share_basis_points
    ) // 10000
    return scaffold


# ===========================================================================
# Tier 4: Refund / no-show / walkout finalization scenarios
# ===========================================================================
def setup_confirmed_for_cancellation(
    *,
    refund_tier_code: str = "MODERATE",
    base_rate_cents: int = 20000,
    initial_clock_iso: str = "2026-06-01T10:00:00.000Z",
    check_in_date: str = "2026-06-09",
    check_out_date: str = "2026-06-11",
) -> Dict[str, Any]:
    """Set the clock to initial_clock_iso, build distribution, create +
    confirm a Reservation. Returns {scaffold, reservation, clock_iso}."""
    advance_clock(initial_clock_iso)
    scaffold = setup_basic_distribution(
        base_rate_cents=base_rate_cents,
        refund_tier_code=refund_tier_code,
        n_rooms=4,
        channel_type="DIRECT",
        commission_basis_points=0,
    )
    res = create_confirmed_reservation(
        scaffold,
        check_in_date=check_in_date,
        check_out_date=check_out_date,
    )
    return {
        "scaffold": scaffold,
        "reservation": res,
        "clock_iso": initial_clock_iso,
    }


def setup_walkout_ready(
    *,
    base_rate_cents: int = 20000,
    walkout_compensation_cents: int = 15000,
    check_in_date: str = "2027-01-15",
    check_out_date: str = "2027-01-16",
) -> Dict[str, Any]:
    """Build a scaffold with a single room and a high-overbook policy so
    the second confirmation is allowed; create + confirm two reservations
    that share that single room's date. The first reservation can be
    walked out only after the room is consumed (housekeeping_status
    OCCUPIED takes the only candidate room out of the VACANT_CLEAN set).

    Returns {scaffold, policy, res_a, res_b, room}.
    """
    advance_clock(date_at_midnight(check_in_date))  # 00:00 of arrival day
    rt = create_room_type(base_rate_cents=base_rate_cents)
    room = create_room(room_type_id=rt["id"])
    plan = create_rate_plan(room_type_id=rt["id"], refund_tier_code="FLEXIBLE")
    channel = create_channel(channel_type="DIRECT", commission_basis_points=0)
    mapping = create_mapping(
        channel_id=channel["id"], rate_plan_id=plan["id"],
        inventory_share_basis_points=10000,
    )
    # OverbookingPolicy that allows up to 200% of physical capacity (1 -> 3)
    policy = create_overbooking_policy(
        room_type_id=rt["id"],
        stay_date=check_in_date,
        overbook_ratio_basis_points=5000,  # +50% (max allowed by PRD §3.4)
        estimated_no_show_probability_basis_points=0,
        walkout_compensation_cents=walkout_compensation_cents,
    )
    scaffold = {
        "room_type": rt,
        "rooms": [room],
        "rate_plan": plan,
        "channel": channel,
        "mapping": mapping,
    }
    res_a = create_confirmed_reservation(
        scaffold,
        check_in_date=check_in_date, check_out_date=check_out_date,
        guest_name="GuestA",
    )
    # PRD §3.4 floor(1 * 5000/10000) = 0 → ceiling = 1. Cannot confirm a
    # second reservation under physical_capacity=1. Add a second room then
    # remove it from candidate set after first check-in. (We don't actually
    # need a second confirmed reservation for the basic walk-out path —
    # tests instead check first walk-out fails with VACANT_CLEAN room
    # available, then walk-out succeeds after check-in consumed the room.)
    return {
        "scaffold": scaffold,
        "policy": policy,
        "reservation": res_a,
        "room": room,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
    }


def setup_no_show_ready(
    *,
    refund_tier_code: str = "MODERATE",
    base_rate_cents: int = 40000,
    check_in_date: str = "2026-09-10",
    check_out_date: str = "2026-09-11",
    initial_clock_iso: str = "2026-09-01T10:00:00.000Z",
) -> Dict[str, Any]:
    """Pre-arrival scaffold with a CONFIRMED Reservation; the test then
    advances the clock past check_in_date + 24h to trigger the
    system NO_SHOW transition (PRD §3.7)."""
    advance_clock(initial_clock_iso)
    scaffold = setup_basic_distribution(
        base_rate_cents=base_rate_cents,
        refund_tier_code=refund_tier_code,
        n_rooms=1,
        channel_type="DIRECT",
        commission_basis_points=0,
    )
    res = create_confirmed_reservation(
        scaffold,
        check_in_date=check_in_date, check_out_date=check_out_date,
    )
    return {
        "scaffold": scaffold,
        "reservation": res,
        "check_in_date": check_in_date,
        "check_out_date": check_out_date,
    }


# ===========================================================================
# Tier 5: Cascade scenarios (maintenance, rate parity, dispute)
# ===========================================================================
def setup_active_maintenance_block(
    *,
    block_start_date: str = "2026-12-01",
    block_end_date: str = "2026-12-05",
    activate_at_iso: str = "2026-12-02T10:00:00.000Z",
) -> Dict[str, Any]:
    """RoomType + 1 Room + a SCHEDULED MaintenanceBlock; advance the
    clock so the block becomes ACTIVE and the room becomes OUT_OF_ORDER.
    Returns {room_type, room, block}."""
    advance_clock(date_at_midnight(block_start_date))  # earliest baseline
    rt = create_room_type()
    room = create_room(room_type_id=rt["id"])
    block_payload = create_maintenance_block_payload(
        room_id=room["id"],
        start_date=block_start_date,
        end_date=block_end_date,
        reason="Refurbishment",
    )
    create_resp = api_client.create_maintenance_block(
        block_payload, TEST_USERS["housekeeping_headers"],
    )
    block = get_success_data(create_resp)
    advance_clock(activate_at_iso)
    # Re-fetch room to get its current state.
    room_resp = api_client.list_rooms(
        TEST_USERS["admin_headers"], params={"room_type_id": rt["id"]},
    )
    rooms_data = get_success_data(room_resp)
    if isinstance(rooms_data, list):
        rooms_now = rooms_data
    else:
        rooms_now = [rooms_data]
    fresh_room = next((r for r in rooms_now if r["id"] == room["id"]), room)
    return {"room_type": rt, "room": fresh_room, "block": block}


def setup_rate_parity_violation_scaffold(
    *,
    base_rate_cents: int = 20000,
    n_rooms: int = 4,
    ota1_commission_bp: int = 1500,
    ota2_commission_bp: int = 4000,
    stay_date: str = "2026-11-01",
) -> Dict[str, Any]:
    """RoomType + 4 rooms + RatePlan + 2 OTA channels with DIFFERENT
    commission rates wide enough that approval of a RateOverride emits
    RATE_PARITY_VIOLATION_DETECTED.

    The two OTAs see grossed rates of:
      OTA1: rate * (10000 + 1500) / 10000 = 1.15 * rate
      OTA2: rate * (10000 + 4000) / 10000 = 1.40 * rate
    Ratio max/min - 1 = 1.40/1.15 - 1 ≈ 0.217 > 0.01, so a single approve
    triggers the parity audit (PRD §3.3)."""
    return setup_distribution_with_two_ota_channels(
        base_rate_cents=base_rate_cents,
        n_rooms=n_rooms,
        ota1_commission_bp=ota1_commission_bp,
        ota2_commission_bp=ota2_commission_bp,
    )


# ===========================================================================
# Audit log query helper
# ===========================================================================
def list_audit_logs(*,
                    event_type: Optional[str] = None,
                    subject_id: Optional[str] = None,
                    subject_entity: Optional[str] = None,
                    headers: Optional[Dict[str, str]] = None,
                    limit: int = 100) -> List[Dict[str, Any]]:
    """List audit logs, optionally filtered. Default uses admin headers
    because PRD §2.10 limits read access to PlatformAdmin and
    RevenueManager."""
    params: Dict[str, Any] = {"limit": limit, "offset": 0}
    if event_type is not None:
        params["event_type"] = event_type
    if subject_id is not None:
        params["subject_id"] = subject_id
    if subject_entity is not None:
        params["subject_entity"] = subject_entity
    res = api_client.list_audit_logs(
        headers or TEST_USERS["admin_headers"], params=params,
    )
    data = get_success_data(res)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("items", []) if "items" in data else []
    return []


__all__ = [
    # time helpers
    "iso_z", "parse_iso", "add_hours", "add_days",
    "date_only", "date_plus_days", "date_at_midnight",
    # clock
    "advance_clock", "get_clock",
    # entity wrappers
    "create_room_type", "create_room",
    "create_channel", "create_rate_plan", "create_mapping",
    "create_overbooking_policy", "create_reservation",
    "confirm_reservation", "cancel_reservation", "get_reservation",
    # composite scaffolds
    "setup_basic_distribution",
    "setup_distribution_with_two_ota_channels",
    # reservation lifecycle shortcuts
    "create_pending_reservation",
    "create_confirmed_reservation",
    "create_checked_in_reservation",
    # rate override approval-chain shortcuts
    "submit_rate_override", "approve_rate_override",
    "submit_and_approve_rate_override",
    # threshold targeting
    "setup_room_type_at_overbooking_boundary",
    "fill_reservations_to_count",
    "setup_with_n_confirmed_for_date",
    "setup_channel_share_boundary",
    # finalization scenarios
    "setup_confirmed_for_cancellation",
    "setup_walkout_ready",
    "setup_no_show_ready",
    # cascade scenarios
    "setup_active_maintenance_block",
    "setup_rate_parity_violation_scaffold",
    # audit logs
    "list_audit_logs",
]
