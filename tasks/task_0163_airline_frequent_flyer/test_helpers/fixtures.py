"""Composite setup helpers — multi-step state builders.

These helpers encapsulate the 5–15 API-call sequences required to reach
the system states tests need to assert on. They use get_success_data
(the lenient validator) so setup failures surface as clear "Setup
failed" errors rather than confusing assertion failures.

PRD §2.1 identity threading: ANY call performed as Member uses headers
minted via make_member_headers(member["id"]). The shared
TEST_USERS["member_fallback_headers"] is reserved for tests that do not
exercise ownership.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    add_days_iso,
    add_hours_iso,
    annual_rollover_payload,
    clock_advance_payload,
    create_award_booking_payload,
    create_flight_payload,
    create_gift_payload,
    create_member_payload,
    create_segment_payload,
    create_status_match_request_payload,
    create_upgrade_request_payload,
    iso_from_dt,
    iso_now_utc,
    points_adjustment_payload,
    random_idempotency_key,
)
from .test_users import (
    TEST_USERS,
    make_booking_agent_headers,
    make_member_headers,
    make_program_admin_headers,
)


# ---------------------------------------------------------------------------
# Convenience header accessors.
# ---------------------------------------------------------------------------
def admin_headers() -> Dict[str, str]:
    return TEST_USERS["program_admin_headers"]


def booking_agent_headers() -> Dict[str, str]:
    return TEST_USERS["booking_agent_headers"]


# ===========================================================================
# Tier 1: Single-entity factories (always-fresh primary entities).
# ===========================================================================
def create_member(home_region: str = "DOMESTIC",
                  **payload_overrides) -> Dict[str, Any]:
    """POST /members as ProgramAdmin; returns the created Member dict.
    The caller binds the returned id to make_member_headers() for any
    follow-up ownership-gated call.
    """
    payload = create_member_payload(
        home_region=home_region, **payload_overrides,
    )
    resp = api_client.create_member(payload, admin_headers())
    return get_success_data(resp)


def create_flight(**payload_overrides) -> Dict[str, Any]:
    payload = create_flight_payload(**payload_overrides)
    resp = api_client.create_flight(payload, admin_headers())
    return get_success_data(resp)


def get_member(member_id: str,
               as_admin: bool = True) -> Dict[str, Any]:
    headers = admin_headers() if as_admin else make_member_headers(member_id)
    resp = api_client.get_member(member_id, headers)
    return get_success_data(resp)


def get_flight(flight_id: str) -> Dict[str, Any]:
    resp = api_client.get_flight(flight_id, admin_headers())
    return get_success_data(resp)


def get_segment(member_id: str, segment_id: str) -> Dict[str, Any]:
    """GET via the member's segment list — there is no single-segment
    fetch endpoint declared in PRD §4. Returns the matching dict."""
    resp = api_client.list_segments(
        member_id, make_member_headers(member_id),
        params={"limit": 100},
    )
    data = get_success_data(resp)
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    for seg in data:
        if seg["id"] == segment_id:
            return seg
    raise AssertionError(
        f"Setup failed: segment {segment_id} not found for member {member_id}"
    )


def get_award_booking(member_id: str, booking_id: str) -> Dict[str, Any]:
    resp = api_client.get_award_booking(
        member_id, booking_id, make_member_headers(member_id),
    )
    return get_success_data(resp)


def list_points_transactions(member_id: str,
                             params: Optional[Dict[str, Any]] = None,
                             ) -> List[Dict[str, Any]]:
    resp = api_client.list_points_transactions(
        member_id, make_member_headers(member_id), params=params,
    )
    body = resp.json()
    return body["data"]


def list_membership_years(member_id: str) -> List[Dict[str, Any]]:
    resp = api_client.list_membership_years(
        member_id, make_member_headers(member_id),
        params={"limit": 100},
    )
    body = resp.json()
    return body["data"]


def list_certificates(member_id: str) -> List[Dict[str, Any]]:
    resp = api_client.list_certificates(
        member_id, make_member_headers(member_id),
        params={"limit": 100},
    )
    body = resp.json()
    return body["data"]


def list_upgrade_requests(member_id: str) -> List[Dict[str, Any]]:
    resp = api_client.list_upgrade_requests(
        member_id, make_member_headers(member_id),
        params={"limit": 100},
    )
    body = resp.json()
    return body["data"]


def list_status_match_requests(member_id: str) -> List[Dict[str, Any]]:
    resp = api_client.list_status_match_requests(
        member_id, make_member_headers(member_id),
        params={"limit": 100},
    )
    body = resp.json()
    return body["data"]


# ===========================================================================
# Tier 2: Multi-entity composite setups.
# ===========================================================================
def create_member_with_balance(points_balance: int,
                               home_region: str = "DOMESTIC",
                               ) -> Dict[str, Any]:
    """Member starts at balance 0; PRD §3.8 admin adjustment posts an
    ADMIN_ADJUSTMENT row for arbitrary signed delta. Returns the member
    after the adjustment.
    """
    member = create_member(home_region=home_region)
    if points_balance != 0:
        adj = points_adjustment_payload(
            points_delta=points_balance,
            reason="setup: seed balance",
        )
        get_success_data(
            api_client.post_points_adjustment(
                member["id"], adj, admin_headers(),
            )
        )
    return get_member(member["id"])


def create_segment_for_member(member_id: str, flight_id: str,
                              booked_cabin: str = "ECONOMY",
                              ) -> Dict[str, Any]:
    """POST /members/{memberId}/segments as that Member. PRD §2.1
    requires the member's own headers for ownership."""
    payload = create_segment_payload(
        flight_id=flight_id, booked_cabin=booked_cabin,
    )
    resp = api_client.create_segment(
        member_id, payload, make_member_headers(member_id),
    )
    return get_success_data(resp)


def depart_flight(flight_id: str) -> Dict[str, Any]:
    resp = api_client.depart_flight(flight_id, admin_headers())
    return get_success_data(resp)


def mark_segment_flown(member_id: str, segment_id: str) -> Dict[str, Any]:
    """PRD §4: mark-flown is BookingAgent or ProgramAdmin. BookingAgent
    is opaque so the shared header is canonical."""
    resp = api_client.mark_segment_flown(
        member_id, segment_id, booking_agent_headers(),
    )
    return get_success_data(resp)


def refund_segment(member_id: str, segment_id: str) -> Dict[str, Any]:
    resp = api_client.refund_segment(
        member_id, segment_id, admin_headers(),
    )
    return get_success_data(resp)


def fly_one_segment(member_id: str, flight_overrides: Optional[Dict] = None,
                    booked_cabin: str = "ECONOMY",
                    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """End-to-end: create flight, book a segment, depart the flight,
    mark the segment flown. Returns (flight, flown_segment).

    PRD §3.3 sets the ACCRUAL row's posted_at to Flight.departure_at and
    PRD §2.8 filters points_balance by posted_at <= now. To realise the
    PRD §3.3 invariant ("balance is incremented by the same amount via
    the ledger sum") immediately after mark-flown, the flight's
    departure_at must already be at or before the server clock when the
    segment is flown. We therefore override departure_at to a fresh
    near-past instant (in the current calendar year) by default.
    """
    overrides = dict(flight_overrides or {})
    if "departure_at" not in overrides:
        # Use a recent past instant so posted_at <= now after mark-flown,
        # while keeping the same calendar year as the server clock so
        # flown_year == current_membership_year.
        overrides["departure_at"] = iso_from_dt(
            datetime.now(timezone.utc) - timedelta(seconds=5),
        )
    flight = create_flight(**overrides)
    segment = create_segment_for_member(
        member_id, flight["id"], booked_cabin=booked_cabin,
    )
    depart_flight(flight["id"])
    flown = mark_segment_flown(member_id, segment["id"])
    return flight, flown


# ===========================================================================
# Tier 3: Tier / status-match progression.
# ===========================================================================
def promote_member_to_tier_via_status_match(member_id: str,
                                             target_tier: str = "GOLD",
                                             ) -> Dict[str, Any]:
    """PRD §3.7: create PENDING request → admin approves → member
    activates. The activation flips Member.tier and appends a 5000-point
    STATUS_MATCH_BONUS row.
    """
    smr = get_success_data(
        api_client.create_status_match_request(
            member_id,
            create_status_match_request_payload(
                competitor_tier=target_tier,
            ),
            make_member_headers(member_id),
        )
    )
    get_success_data(
        api_client.approve_status_match_request(
            member_id, smr["id"], admin_headers(),
        )
    )
    get_success_data(
        api_client.activate_status_match_request(
            member_id, smr["id"], make_member_headers(member_id),
        )
    )
    return get_member(member_id)


# ===========================================================================
# Tier 4: Accumulation / threshold targeting.
# ===========================================================================
def setup_member_with_ytd_qualifying_points(
    target_qualifying_points: int,
    initial_tier: str = "BASIC",
    flight_distance_miles: int = 1_000,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Fly enough segments under the supplied initial_tier to bank at
    least target_qualifying_points YTD.

    Uses a base_fare_cents tuned so each ECONOMY segment under the
    target tier credits a known number of qualifying points (PRD §3.3
    formula). For BASIC: base_fare_cents=200_000 ($2000) → 2000*5*1.0
    = 10_000 per segment. Loops until the YTD total reaches or exceeds
    the target. Returns (member, list-of-flown-segments).

    PRD §3.3: "qualifying_points_earned = max(MIN_PER_SEGMENT,
    min(MAX_PER_SEGMENT, floor(raw)))". Per-segment cap is 50_000, so
    targets above ~50_000 require multiple segments.
    """
    member = create_member()
    if initial_tier != "BASIC":
        member = promote_member_to_tier_via_status_match(
            member["id"], target_tier=initial_tier,
        )

    # Choose a base_fare so each segment earns 10_000 qualifying points
    # under BASIC tier (1.0 multiplier) and ECONOMY cabin (×5).
    # 10_000 = base_dollars * 5 * 1.0 → base_dollars = 2_000 → cents = 200_000.
    # For SILVER tier (×1.25) same fare yields 12_500 per segment.
    base_fare_cents = 200_000

    flown: List[Dict[str, Any]] = []
    earned = 0
    while earned < target_qualifying_points:
        _, seg = fly_one_segment(
            member["id"],
            flight_overrides={
                "base_fare_cents": base_fare_cents,
                "distance_miles": flight_distance_miles,
            },
        )
        flown.append(seg)
        earned += int(seg.get("qualifying_points_earned", 0))
        if len(flown) > 30:
            raise AssertionError(
                "Setup failed: too many segments needed to reach "
                f"target {target_qualifying_points}; current {earned}."
            )

    return get_member(member["id"]), flown


def setup_load_factor_band(flight_overrides: Dict[str, Any],
                           target_band: str,
                           ) -> Dict[str, Any]:
    """Create a flight and pre-load CONFIRMED award bookings on it so
    its load_factor lands in the target band.

    Bands per PRD §3.5:
      - "low"  → load_factor < 0.50 (demand 0.8)
      - "med"  → 0.50 ≤ load_factor < 0.80 (demand 1.0)
      - "high" → 0.80 ≤ load_factor < 0.95 (demand 1.5)
      - "peak" → 0.95 ≤ load_factor (demand 2.0)
    Confirmed segments are loaded into ECONOMY cabin (FIXED 12_500 each
    on DOMESTIC) and the helper seeds each filler member's balance so
    the confirm succeeds.
    """
    flight = create_flight(**flight_overrides)
    cap = (
        flight["capacity_economy"]
        + flight["capacity_business"]
        + flight["capacity_first"]
    )
    if target_band == "low":
        target_count = max(0, int(cap * 0.30))      # < 0.50
    elif target_band == "med":
        target_count = int(cap * 0.65)              # in [0.50, 0.80)
    elif target_band == "high":
        target_count = int(cap * 0.85)              # in [0.80, 0.95)
    elif target_band == "peak":
        target_count = max(int(cap * 0.97), cap - 1)  # >= 0.95
    else:
        raise ValueError(f"unknown band {target_band}")

    # Distribute fillers across cabins respecting each cabin's
    # remaining capacity. PRD §3.5 FIXED pricing yields a known
    # points_cost per (region, cabin) row.
    filled = {"ECONOMY": 0, "BUSINESS": 0, "FIRST": 0}
    cabin_capacity = {
        "ECONOMY": int(flight["capacity_economy"]),
        "BUSINESS": int(flight["capacity_business"]),
        "FIRST": int(flight["capacity_first"]),
    }
    for _ in range(target_count):
        # Pick the first cabin with remaining capacity.
        target_cabin = None
        for c in ("ECONOMY", "BUSINESS", "FIRST"):
            if filled[c] < cabin_capacity[c]:
                target_cabin = c
                break
        if target_cabin is None:
            break  # flight fully booked, cannot push higher
        # FIXED INTERNATIONAL FIRST costs 110_000; seed enough headroom.
        filler = create_member_with_balance(150_000)
        booking = get_success_data(
            api_client.create_award_booking(
                filler["id"],
                create_award_booking_payload(
                    flight["id"], cabin=target_cabin, pricing_mode="FIXED",
                ),
                make_member_headers(filler["id"]),
            )
        )
        get_success_data(
            api_client.confirm_award_booking(
                filler["id"], booking["id"],
                make_member_headers(filler["id"]),
            )
        )
        filled[target_cabin] += 1

    return get_flight(flight["id"])


def fill_flight_first_inventory_to_zero(flight_id: str) -> None:
    """For tests asserting ERR_UPGRADE_INVENTORY_EXHAUSTED. Books the
    flight's FIRST cabin via paid award redemptions until
    upgrade_inventory_first == 0."""
    while True:
        flight = get_flight(flight_id)
        if flight.get("upgrade_inventory_first", 0) <= 0:
            return
        filler = create_member_with_balance(150_000)
        booking = get_success_data(
            api_client.create_award_booking(
                filler["id"],
                create_award_booking_payload(
                    flight_id, cabin="FIRST", pricing_mode="FIXED",
                ),
                make_member_headers(filler["id"]),
            )
        )
        get_success_data(
            api_client.confirm_award_booking(
                filler["id"], booking["id"],
                make_member_headers(filler["id"]),
            )
        )


# ===========================================================================
# Tier 5: AwardBooking + CompanionCertificate composite setups.
# ===========================================================================
def grant_companion_certificate(member_id: str) -> Dict[str, Any]:
    """POST /members/{memberId}/certificates as ProgramAdmin (PRD §3.5
    admin-grant). Emits an ACTIVE certificate with issued_reason
    ADMIN_GRANT and expires_at = now + 12 months."""
    resp = api_client.grant_certificate(member_id, admin_headers())
    return get_success_data(resp)


def setup_held_award_booking(
    cabin: str = "ECONOMY",
    pricing_mode: str = "FIXED",
    route_region: str = "DOMESTIC",
    member_balance: int = 50_000,
    member: Optional[Dict[str, Any]] = None,
    flight: Optional[Dict[str, Any]] = None,
    companion_certificate_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Create member (with balance), flight, and a HELD AwardBooking.
    Returns (member, flight, booking)."""
    if member is None:
        member = create_member_with_balance(member_balance)
    if flight is None:
        flight = create_flight(route_region=route_region)

    payload = create_award_booking_payload(
        flight["id"], cabin=cabin, pricing_mode=pricing_mode,
    )
    if companion_certificate_id is not None:
        payload["companion_certificate_id"] = companion_certificate_id
    booking = get_success_data(
        api_client.create_award_booking(
            member["id"], payload, make_member_headers(member["id"]),
        )
    )
    return member, flight, booking


def setup_confirmed_award_booking(
    cabin: str = "ECONOMY",
    pricing_mode: str = "FIXED",
    route_region: str = "DOMESTIC",
    member_balance: int = 50_000,
    member: Optional[Dict[str, Any]] = None,
    flight: Optional[Dict[str, Any]] = None,
    companion_certificate_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """HELD → CONFIRMED. Returns (member, flight, confirmed_booking)."""
    member, flight, booking = setup_held_award_booking(
        cabin=cabin, pricing_mode=pricing_mode, route_region=route_region,
        member_balance=member_balance, member=member, flight=flight,
        companion_certificate_id=companion_certificate_id,
    )
    confirmed = get_success_data(
        api_client.confirm_award_booking(
            member["id"], booking["id"],
            make_member_headers(member["id"]),
        )
    )
    return member, flight, confirmed


# ===========================================================================
# Tier 6: UpgradeRequest composite setups.
# ===========================================================================
def setup_waitlisted_upgrade_request(
    member: Optional[Dict[str, Any]] = None,
    flight: Optional[Dict[str, Any]] = None,
    booked_cabin: str = "BUSINESS",
    target_cabin: str = "FIRST",
    points_offered: int = 5_000,
    member_tier: str = "GOLD",
    member_balance: int = 30_000,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build a Member with the requested tier, a flight, a booked
    segment, and a WAITLISTED UpgradeRequest.

    Returns (member, flight, segment, upgrade_request).
    PRD §3.4: "the acting member's tier must be at least GOLD." Setting
    member_tier="BASIC" or "SILVER" produces the negative-test scenario
    (the upgrade-request creation itself will be rejected).
    """
    if member is None:
        member = create_member_with_balance(member_balance)
    # Bump tier via status match if needed.
    if member_tier in ("GOLD", "PLATINUM") and member.get("tier") not in (
        "GOLD", "PLATINUM",
    ):
        member = promote_member_to_tier_via_status_match(
            member["id"], target_tier=member_tier,
        )
    elif member_tier == "SILVER" and member.get("tier") not in (
        "SILVER", "GOLD", "PLATINUM",
    ):
        member = promote_member_to_tier_via_status_match(
            member["id"], target_tier="SILVER",
        )
    # BASIC stays BASIC; nothing to do.

    if flight is None:
        flight = create_flight()

    segment = create_segment_for_member(
        member["id"], flight["id"], booked_cabin=booked_cabin,
    )

    payload = create_upgrade_request_payload(
        target_cabin=target_cabin, points_offered=points_offered,
    )
    ur = get_success_data(
        api_client.create_upgrade_request(
            member["id"], segment["id"], payload,
            make_member_headers(member["id"]),
        )
    )
    return member, flight, segment, ur


# ===========================================================================
# Tier 7: Status-match setups.
# ===========================================================================
def setup_pending_status_match(
    member: Optional[Dict[str, Any]] = None,
    competitor_tier: str = "GOLD",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if member is None:
        member = create_member()
    smr = get_success_data(
        api_client.create_status_match_request(
            member["id"],
            create_status_match_request_payload(
                competitor_tier=competitor_tier,
            ),
            make_member_headers(member["id"]),
        )
    )
    return member, smr


def setup_approved_status_match(
    member: Optional[Dict[str, Any]] = None,
    competitor_tier: str = "GOLD",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    member, smr = setup_pending_status_match(
        member=member, competitor_tier=competitor_tier,
    )
    approved = get_success_data(
        api_client.approve_status_match_request(
            member["id"], smr["id"], admin_headers(),
        )
    )
    return member, approved


# ===========================================================================
# Tier 8: Clock-driven setups.
# ===========================================================================
def advance_clock_seconds(by_seconds: int) -> Dict[str, Any]:
    """POST /_clock/advance — ProgramAdmin-only per PRD §3.8."""
    resp = api_client.clock_advance(
        clock_advance_payload(by_seconds=by_seconds), admin_headers(),
    )
    return get_success_data(resp)


def run_sweep_expire_points() -> Dict[str, Any]:
    resp = api_client.sweep_expire_points(admin_headers())
    return get_success_data(resp)


def run_sweep_expire_bookings() -> Dict[str, Any]:
    resp = api_client.sweep_expire_bookings(admin_headers())
    return get_success_data(resp)


def run_sweep_expire_certificates() -> Dict[str, Any]:
    resp = api_client.sweep_expire_certificates(admin_headers())
    return get_success_data(resp)


def run_sweep_expire_status_matches() -> Dict[str, Any]:
    resp = api_client.sweep_expire_status_matches(admin_headers())
    return get_success_data(resp)


def run_sweep_promote_upgrades(flight_id: Optional[str] = None,
                               ) -> Dict[str, Any]:
    payload = {"flight_id": flight_id} if flight_id else {}
    resp = api_client.sweep_promote_upgrades(admin_headers(), payload)
    return get_success_data(resp)


def run_annual_rollover(target_year: int) -> Dict[str, Any]:
    resp = api_client.sweep_annual_rollover(
        annual_rollover_payload(target_year=target_year),
        admin_headers(),
    )
    return get_success_data(resp)


__all__ = [
    "admin_headers",
    "advance_clock_seconds",
    "booking_agent_headers",
    "create_flight",
    "create_member",
    "create_member_with_balance",
    "create_segment_for_member",
    "depart_flight",
    "fill_flight_first_inventory_to_zero",
    "fly_one_segment",
    "get_award_booking",
    "get_flight",
    "get_member",
    "get_segment",
    "grant_companion_certificate",
    "list_certificates",
    "list_membership_years",
    "list_points_transactions",
    "list_status_match_requests",
    "list_upgrade_requests",
    "mark_segment_flown",
    "promote_member_to_tier_via_status_match",
    "refund_segment",
    "run_annual_rollover",
    "run_sweep_expire_bookings",
    "run_sweep_expire_certificates",
    "run_sweep_expire_points",
    "run_sweep_expire_status_matches",
    "run_sweep_promote_upgrades",
    "setup_approved_status_match",
    "setup_confirmed_award_booking",
    "setup_held_award_booking",
    "setup_load_factor_band",
    "setup_member_with_ytd_qualifying_points",
    "setup_pending_status_match",
    "setup_waitlisted_upgrade_request",
]
