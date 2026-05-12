"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures
surface as 'Setup failed' errors rather than confusing assertion failures.

Identity threading is mandatory per PRD §2.1: whenever a fixture creates
an entity-backed role's backing record (Venue, Player, StaffMember), any
ownership-gated call must use make_<role>_headers(<actual-id>), NEVER the
shared TEST_USERS fallback. The shared fallbacks would carry an X-User-ID
that never matches any real entity id, so every ownership check would reject.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_booking_payload,
    create_maintenance_window_payload,
    create_player_payload,
    create_review_payload,
    create_room_payload,
    create_session_slot_payload,
    create_settlement_run_payload,
    create_staff_assignment_payload,
    create_staff_member_payload,
    create_theme_payload,
    create_venue_payload,
    create_waitlist_entry_payload,
    iso_z,
    moderate_review_payload,
    publish_theme_revision_payload,
    refund_booking_payload,
    unique_chain_id,
)
from .test_users import (
    TEST_USERS,
    make_content_moderator_headers,
    make_player_headers,
    make_platform_admin_headers,
    make_script_author_headers,
    make_venue_operator_headers,
)


# ──────────────────────────────────────────────────────────────────────────
# Time / clock helpers
# ──────────────────────────────────────────────────────────────────────────

# Tracks the highest logical-clock instant the test suite has driven the
# server to via /_clock/advance. The server's clock is monotonically forward
# (PRD §2.6), so tests running later in the session inherit any advance from
# earlier tests. now_iso() must reflect this so newly-built slot timestamps
# remain strictly in the future relative to the server's current clock —
# otherwise lead-time tier checks, start-window checks, and match-deadline
# cascades fire from a "logical past" the helpers cannot see.
_logical_clock_high_water: datetime = datetime.now(tz=timezone.utc)


def now_iso() -> str:
    """Return an ISO 8601 timestamp at-or-after the server's logical clock.

    Uses max(real_wall_clock, logical_clock_high_water) so that downstream
    helpers that build future timestamps (`add_hours(now_iso(), 48)`) always
    produce times that are strictly in the server's future, even after a
    previous test advanced the logical clock far ahead of real time.
    """
    real = datetime.now(tz=timezone.utc)
    base = real if real >= _logical_clock_high_water else _logical_clock_high_water
    return iso_z(base)


def add_minutes(ts: str, minutes: float) -> str:
    """Return `ts` shifted by `minutes` minutes (may be negative)."""
    base = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return iso_z(base + timedelta(minutes=minutes))


def add_hours(ts: str, hours: float) -> str:
    return add_minutes(ts, hours * 60)


def advance_clock_to(ts: str) -> None:
    """Advance the server's logical clock to the given ISO 8601 UTC instant.
    PRD §2.6 / §3.7: clock advances trigger time-gated cascades (match-deadline
    lapses, deposit-hold TTL expirations, waitlist promotion sweeps)."""
    global _logical_clock_high_water
    admin = TEST_USERS["platform_admin_headers"]
    get_success_data(api_client.advance_clock(ts, admin))
    target = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if target > _logical_clock_high_water:
        _logical_clock_high_water = target


# ──────────────────────────────────────────────────────────────────────────
# Tier 1 — basic creation helpers (single API call)
# ──────────────────────────────────────────────────────────────────────────

def create_venue(**overrides: Any) -> Dict[str, Any]:
    """Create a venue (PlatformAdmin role). Returns the created Venue record."""
    admin = TEST_USERS["platform_admin_headers"]
    payload = create_venue_payload(**overrides)
    return get_success_data(api_client.create_venue(payload, admin))


def create_player(**overrides: Any) -> Dict[str, Any]:
    """Create a player. PRD §3.5: "Player identity is recorded as `Player.id`
    and equals `X-User-ID` whenever the role is `Player`." Each call therefore
    needs a fresh X-User-ID so distinct players do not collapse into one row.
    PlatformAdmin self-registration would also work; here we self-register as
    Player with a freshly-minted UUID so tests that need N independent player
    ids get N distinct rows."""
    import uuid as _uuid
    fresh_player_id = str(_uuid.uuid4())
    headers = make_player_headers(fresh_player_id)
    payload = create_player_payload(**overrides)
    return get_success_data(api_client.create_player(payload, headers))


def create_staff_member(chain_id: str, **overrides: Any) -> Dict[str, Any]:
    """Register a StaffMember (PlatformAdmin only per PRD §3.8)."""
    admin = TEST_USERS["platform_admin_headers"]
    payload = create_staff_member_payload(chain_id, **overrides)
    return get_success_data(api_client.create_staff_member(payload, admin))


# ──────────────────────────────────────────────────────────────────────────
# Tier 2 — entity hierarchy: venue → room → theme(published) → slot
# ──────────────────────────────────────────────────────────────────────────

def create_room(venue: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    """Create a room under the given venue. Threaded with venue-id headers
    per PRD §2.1 ownership rule."""
    headers = make_venue_operator_headers(venue["id"])
    payload = create_room_payload(**overrides)
    return get_success_data(api_client.create_room(venue["id"], payload, headers))


def create_published_theme(
    chain_id: str,
    compatible_room_ids: List[str],
    *,
    author_staff_member: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create a Theme in DRAFT and publish it (PRD §3.2). Returns PUBLISHED Theme.
    The acting ScriptAuthor must be a StaffMember in the same chain_id; if not
    provided, one is created.
    """
    if author_staff_member is None:
        author_staff_member = create_staff_member(chain_id)
    author_headers = make_script_author_headers(author_staff_member["id"])
    payload = create_theme_payload(chain_id, compatible_room_ids, **overrides)
    theme = get_success_data(api_client.create_theme(payload, author_headers))
    published = get_success_data(api_client.publish_theme(theme["id"], author_headers))
    return published


def create_session_slot(
    venue: Dict[str, Any],
    room: Dict[str, Any],
    theme: Dict[str, Any],
    *,
    starts_at: Optional[str] = None,
    visibility: str = "PRIVATE_ONLY",
    required_seats_for_launch: Optional[int] = None,
    price_cents: Optional[int] = None,
    match_preferences: Optional[Dict[str, Any]] = None,
    hours_ahead: float = 48.0,
) -> Dict[str, Any]:
    """Create a SessionSlot (PRD §3.3). Defaults starts_at to `hours_ahead`
    hours from now."""
    headers = make_venue_operator_headers(venue["id"])
    if starts_at is None:
        starts_at = add_hours(now_iso(), hours_ahead)
    if required_seats_for_launch is None:
        required_seats_for_launch = theme["min_players"]
    payload = create_session_slot_payload(
        theme_id=theme["id"],
        starts_at=starts_at,
        visibility=visibility,
        required_seats_for_launch=required_seats_for_launch,
        price_cents=price_cents,
        match_preferences=match_preferences,
    )
    return get_success_data(api_client.create_session_slot(venue["id"], room["id"], payload, headers))


def setup_basic_scenario(
    *,
    chain_id: Optional[str] = None,
    venue_overrides: Optional[Dict[str, Any]] = None,
    room_overrides: Optional[Dict[str, Any]] = None,
    theme_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Standard preamble: ACTIVE venue + ACTIVE room + PUBLISHED theme.
    Returns (venue, room, theme).
    """
    if chain_id is None:
        chain_id = unique_chain_id()
    venue = create_venue(chain_id=chain_id, **(venue_overrides or {}))
    room = create_room(venue, **(room_overrides or {}))
    theme = create_published_theme(chain_id, [room["id"]], **(theme_overrides or {}))
    return venue, room, theme


def setup_scenario_with_slot(
    *,
    visibility: str = "PRIVATE_ONLY",
    required_seats_for_launch: Optional[int] = None,
    hours_ahead: float = 48.0,
    price_cents: Optional[int] = None,
    match_preferences: Optional[Dict[str, Any]] = None,
    chain_id: Optional[str] = None,
    venue_overrides: Optional[Dict[str, Any]] = None,
    room_overrides: Optional[Dict[str, Any]] = None,
    theme_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Standard preamble plus one freshly-created SCHEDULED/OPEN slot.
    Returns (venue, room, theme, slot)."""
    venue, room, theme = setup_basic_scenario(
        chain_id=chain_id,
        venue_overrides=venue_overrides,
        room_overrides=room_overrides,
        theme_overrides=theme_overrides,
    )
    slot = create_session_slot(
        venue, room, theme,
        visibility=visibility,
        required_seats_for_launch=required_seats_for_launch,
        hours_ahead=hours_ahead,
        price_cents=price_cents,
        match_preferences=match_preferences,
    )
    return venue, room, theme, slot


# ──────────────────────────────────────────────────────────────────────────
# Tier 3 — Booking lifecycle helpers
# ──────────────────────────────────────────────────────────────────────────

def create_booking(slot: Dict[str, Any], lead_player: Dict[str, Any], team_player_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Create a Booking on the given slot. The lead player MUST appear in
    team_player_ids per PRD §3.5; if no list is supplied, [lead_player['id']]
    is used."""
    headers = make_player_headers(lead_player["id"])
    if team_player_ids is None:
        team_player_ids = [lead_player["id"]]
    payload = create_booking_payload(team_player_ids)
    return get_success_data(api_client.create_booking(slot["id"], payload, headers))


def confirm_booking(booking: Dict[str, Any], lead_player: Dict[str, Any]) -> Dict[str, Any]:
    """Move a booking PENDING_DEPOSIT -> CONFIRMED via the Player path."""
    headers = make_player_headers(lead_player["id"])
    return get_success_data(api_client.confirm_deposit(booking["id"], None, headers))


def create_and_confirm_booking(
    slot: Dict[str, Any],
    lead_player: Dict[str, Any],
    team_player_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create + confirm a booking. Returns the CONFIRMED booking."""
    booking = create_booking(slot, lead_player, team_player_ids=team_player_ids)
    return confirm_booking(booking, lead_player)


def cancel_booking_as_player(booking: Dict[str, Any], lead_player: Dict[str, Any]) -> Dict[str, Any]:
    headers = make_player_headers(lead_player["id"])
    return get_success_data(api_client.cancel_booking(booking["id"], headers))


def cancel_booking_as_operator(booking: Dict[str, Any], venue: Dict[str, Any]) -> Dict[str, Any]:
    headers = make_venue_operator_headers(venue["id"])
    return get_success_data(api_client.cancel_booking(booking["id"], headers))


def get_booking(booking_id: str, viewer_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = viewer_headers or TEST_USERS["platform_admin_headers"]
    return get_success_data(api_client.get_booking(booking_id, headers))


def get_session_slot(slot_id: str, viewer_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = viewer_headers or TEST_USERS["platform_admin_headers"]
    return get_success_data(api_client.get_session_slot(slot_id, headers))


def get_player(player_id: str, viewer_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    headers = viewer_headers or TEST_USERS["platform_admin_headers"]
    return get_success_data(api_client.get_player(player_id, headers))


# ──────────────────────────────────────────────────────────────────────────
# Tier 3.5 — Staffing helpers
# ──────────────────────────────────────────────────────────────────────────

def create_staff_assignment(slot: Dict[str, Any], venue: Dict[str, Any], staff: Dict[str, Any], role_type: str = "HOST") -> Dict[str, Any]:
    """Create a staff assignment (PRD §3.8). The venue must own the slot
    (resolved via slot.venue_id) and X-User-ID must equal venue.id."""
    headers = make_venue_operator_headers(venue["id"])
    payload = create_staff_assignment_payload(slot["id"], staff["id"], role_type)
    return get_success_data(api_client.create_staff_assignment(payload, headers))


def assign_full_staffing(
    slot: Dict[str, Any],
    venue: Dict[str, Any],
    theme: Dict[str, Any],
    *,
    chain_id: str,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Create one HOST staff assignment + the required number of NPC staff
    assignments to satisfy theme.required_host_qualifications and
    theme.required_npc_count. Returns (host_assignment, npc_assignments)."""
    host_quals = list(theme.get("required_host_qualifications") or [])
    host_staff = create_staff_member(chain_id, roles_held=["HOST"], qualifications=host_quals)
    host_assignment = create_staff_assignment(slot, venue, host_staff, role_type="HOST")

    npcs: List[Dict[str, Any]] = []
    for _ in range(int(theme.get("required_npc_count") or 0)):
        npc_staff = create_staff_member(chain_id, roles_held=["NPC"], qualifications=[])
        npcs.append(create_staff_assignment(slot, venue, npc_staff, role_type="NPC"))
    return host_assignment, npcs


# ──────────────────────────────────────────────────────────────────────────
# Tier 3.6 — Slot lifecycle helpers (start, complete, cancel)
# ──────────────────────────────────────────────────────────────────────────

def start_slot(slot: Dict[str, Any], venue: Dict[str, Any]) -> Dict[str, Any]:
    headers = make_venue_operator_headers(venue["id"])
    return get_success_data(api_client.start_session_slot(slot["id"], headers))


def complete_slot(slot: Dict[str, Any], venue: Dict[str, Any]) -> Dict[str, Any]:
    headers = make_venue_operator_headers(venue["id"])
    return get_success_data(api_client.complete_session_slot(slot["id"], headers))


def cancel_slot(slot: Dict[str, Any], venue: Dict[str, Any]) -> Dict[str, Any]:
    headers = make_venue_operator_headers(venue["id"])
    return get_success_data(api_client.cancel_session_slot(slot["id"], headers))


def check_in_booking(booking: Dict[str, Any], venue: Dict[str, Any]) -> Dict[str, Any]:
    headers = make_venue_operator_headers(venue["id"])
    return get_success_data(api_client.check_in_booking(booking["id"], headers))


def refund_booking(booking: Dict[str, Any], venue: Dict[str, Any], refund_amount_cents: int) -> Dict[str, Any]:
    headers = make_venue_operator_headers(venue["id"])
    return get_success_data(api_client.refund_booking(booking["id"], refund_booking_payload(refund_amount_cents), headers))


# ──────────────────────────────────────────────────────────────────────────
# Tier 4 — Composite lifecycle macros (slot → SETTLED, slot → COMPLETED, ...)
# ──────────────────────────────────────────────────────────────────────────

def setup_slot_with_confirmed_booking(
    *,
    seat_count: int = 2,
    visibility: str = "PRIVATE_ONLY",
    hours_ahead: float = 48.0,
    price_cents: Optional[int] = None,
    chain_id: Optional[str] = None,
    venue_overrides: Optional[Dict[str, Any]] = None,
    theme_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build everything needed for a CONFIRMED booking on a SCHEDULED slot.

    Returns dict {venue, room, theme, slot, lead_player, players, booking}.
    `theme.max_players` defaults to seat_count, `min_players` to seat_count
    so the slot's required_seats_for_launch matches seat_count.
    """
    theme_overrides = dict(theme_overrides or {})
    theme_overrides.setdefault("min_players", seat_count)
    theme_overrides.setdefault("max_players", max(seat_count, 4))
    venue, room, theme = setup_basic_scenario(
        chain_id=chain_id,
        venue_overrides=venue_overrides,
        theme_overrides=theme_overrides,
    )
    slot = create_session_slot(
        venue, room, theme,
        visibility=visibility,
        required_seats_for_launch=seat_count,
        hours_ahead=hours_ahead,
        price_cents=price_cents,
    )
    players = [create_player() for _ in range(seat_count)]
    lead_player = players[0]
    team_ids = [p["id"] for p in players]
    booking = create_and_confirm_booking(slot, lead_player, team_player_ids=team_ids)
    return {
        "venue": venue,
        "room": room,
        "theme": theme,
        "slot": slot,
        "lead_player": lead_player,
        "players": players,
        "booking": booking,
    }


def drive_slot_to_completed(
    state: Dict[str, Any],
    *,
    chain_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Take a state from setup_slot_with_confirmed_booking() and drive it to
    schedule_status=COMPLETED with the booking SETTLED.

    Steps (PRD §3.3, §3.6):
      1. Create HOST + required-NPC staffing.
      2. Advance clock into the start window.
      3. POST /session-slots/{id}/start.
      4. POST /bookings/{id}/check-in.
      5. POST /session-slots/{id}/complete.
    Returns updated state with refreshed slot, booking, host_assignment, npcs.
    """
    venue, room, theme, slot = state["venue"], state["room"], state["theme"], state["slot"]
    booking = state["booking"]
    if chain_id is None:
        chain_id = venue["chain_id"]

    host_assignment, npcs = assign_full_staffing(slot, venue, theme, chain_id=chain_id)

    # Advance to inside the start window: starts_at exactly is fine — START_GRACE
    # is implementation-specific so we use starts_at as a safe midpoint per PRD §3.3.
    advance_clock_to(slot["starts_at"])
    started_slot = start_slot(slot, venue)
    checked_in = check_in_booking(booking, venue)
    # Advance past slot.ends_at so completion is unambiguously after the curtain.
    advance_clock_to(add_minutes(slot["ends_at"], 1))
    completed_slot = complete_slot(slot, venue)
    # Refresh booking
    refreshed_booking = get_booking(booking["id"])
    state.update({
        "slot": completed_slot,
        "booking": refreshed_booking,
        "host_assignment": host_assignment,
        "npcs": npcs,
    })
    return state


def setup_slot_at_completed(
    *,
    seat_count: int = 2,
    price_cents: Optional[int] = None,
    chain_id: Optional[str] = None,
    venue_overrides: Optional[Dict[str, Any]] = None,
    theme_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Full lifecycle: builds, confirms, starts, checks in, completes a slot.
    Used by refund / settlement / review tests that need a SETTLED booking.
    """
    state = setup_slot_with_confirmed_booking(
        seat_count=seat_count,
        price_cents=price_cents,
        chain_id=chain_id,
        venue_overrides=venue_overrides,
        theme_overrides=theme_overrides,
    )
    return drive_slot_to_completed(state, chain_id=chain_id)


# ──────────────────────────────────────────────────────────────────────────
# Tier 4.5 — Settlement helpers
# ──────────────────────────────────────────────────────────────────────────

def create_settlement_run_around_slot(slot: Dict[str, Any], chain_id: str) -> Dict[str, Any]:
    """Create a DRAFT settlement run whose period brackets slot.ends_at."""
    admin = TEST_USERS["platform_admin_headers"]
    period_start = add_minutes(slot["starts_at"], -1)
    period_end = add_minutes(slot["ends_at"], 60 * 24)  # one-day window after end
    payload = create_settlement_run_payload(chain_id, period_start, period_end)
    return get_success_data(api_client.create_settlement_run(payload, admin))


def finalize_settlement_run(run: Dict[str, Any]) -> Dict[str, Any]:
    admin = TEST_USERS["platform_admin_headers"]
    return get_success_data(api_client.finalize_settlement_run(run["id"], admin))


def get_settlement_run(run_id: str) -> Dict[str, Any]:
    admin = TEST_USERS["platform_admin_headers"]
    return get_success_data(api_client.get_settlement_run(run_id, admin))


# ──────────────────────────────────────────────────────────────────────────
# Tier 5 — Review helpers
# ──────────────────────────────────────────────────────────────────────────

def submit_review(
    booking: Dict[str, Any],
    lead_player: Dict[str, Any],
    *,
    theme_score: int = 5,
    venue_score: int = 5,
    host_score: Optional[int] = 5,
    comment: str = "Great session, very immersive and well-paced. Highly recommend!",
) -> Dict[str, Any]:
    """Submit a review against a SETTLED booking."""
    headers = make_player_headers(lead_player["id"])
    payload = create_review_payload(
        theme_score=theme_score,
        venue_score=venue_score,
        host_score=host_score,
        comment=comment,
    )
    return get_success_data(api_client.create_review(booking["id"], payload, headers))


def moderate_review(review: Dict[str, Any], decision: str) -> Dict[str, Any]:
    """ContentModerator decides APPROVE | REJECT | HIDE."""
    headers = TEST_USERS["content_moderator_headers"]
    return get_success_data(api_client.moderate_review(review["id"], moderate_review_payload(decision), headers))


def get_review(review_id: str) -> Dict[str, Any]:
    headers = TEST_USERS["content_moderator_headers"]
    return get_success_data(api_client.get_review(review_id, headers))


# ──────────────────────────────────────────────────────────────────────────
# Tier 5 — Waitlist helpers
# ──────────────────────────────────────────────────────────────────────────

def create_waitlist_entry(slot: Dict[str, Any], lead_player: Dict[str, Any], requested_seat_count: int) -> Dict[str, Any]:
    headers = make_player_headers(lead_player["id"])
    payload = create_waitlist_entry_payload(requested_seat_count)
    return get_success_data(api_client.create_waitlist_entry(slot["id"], payload, headers))


def list_waitlist_entries(slot: Dict[str, Any], viewer_player: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """PRD §4: GET /session-slots/{slotId}/waitlist-entries authorises only
    Player and VenueOperator (not PlatformAdmin). When no viewer is supplied
    we fall back to the slot's owning venue operator since slot.venue_id is
    always present and a fresh venue identity satisfies §2.1's ownership
    check."""
    if viewer_player:
        headers = make_player_headers(viewer_player["id"])
    else:
        headers = make_venue_operator_headers(slot["venue_id"])
    resp = api_client.list_waitlist_entries(slot["id"], headers)
    data = get_success_data(resp)
    if isinstance(data, list):
        return data
    # Some implementations may wrap the list under a key.
    return data if isinstance(data, list) else []


# ──────────────────────────────────────────────────────────────────────────
# Tier 6 — Difficulty-targeted setup helpers
# ──────────────────────────────────────────────────────────────────────────

def setup_settled_booking_with_split(
    *,
    paid_amount_cents_per_seat: int = 5000,
    seat_count: int = 2,
    deposit_policy_cents: int = 2000,
    revenue_share_bps: int = 4500,
    author_royalty_bps: int = 2000,
    host_commission_bps: int = 1500,
    platform_fee_bps: int = 2000,
    author_royalty_bps_override: Optional[int] = None,
    commission_bps_override: Optional[int] = None,
    chain_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Drive a slot all the way to COMPLETED with a single SETTLED booking.

    Allows tweaking venue bps splits and per-staff/per-theme overrides so
    settlement_allocation tests can pin every input dimension independently.
    """
    if chain_id is None:
        chain_id = unique_chain_id()
    venue_overrides = {
        "deposit_policy_cents": deposit_policy_cents,
        "revenue_share_bps": revenue_share_bps,
        "author_royalty_bps": author_royalty_bps,
        "host_commission_bps": host_commission_bps,
        "platform_fee_bps": platform_fee_bps,
    }
    theme_overrides: Dict[str, Any] = {}
    if author_royalty_bps_override is not None:
        theme_overrides["author_royalty_bps_override"] = author_royalty_bps_override

    venue = create_venue(chain_id=chain_id, **venue_overrides)
    room = create_room(venue)
    # Theme + author StaffMember (must share chain_id). Force the theme's
    # min_players/max_players to bracket seat_count so the slot's
    # required_seats_for_launch=seat_count passes PRD §3.3 ("must be at least
    # the theme's minimum and at most the theme's maximum").
    theme_overrides.setdefault("min_players", min(seat_count, 2))
    theme_overrides.setdefault("max_players", max(seat_count, 4))
    author = create_staff_member(chain_id, roles_held=["HOST"], qualifications=[])
    theme = create_published_theme(chain_id, [room["id"]], author_staff_member=author, **theme_overrides)
    slot = create_session_slot(
        venue, room, theme,
        visibility="PRIVATE_ONLY",
        required_seats_for_launch=seat_count,
        hours_ahead=48.0,
        price_cents=paid_amount_cents_per_seat,
    )
    # Players + booking.
    players = [create_player() for _ in range(seat_count)]
    lead = players[0]
    team_ids = [p["id"] for p in players]
    booking = create_and_confirm_booking(slot, lead, team_player_ids=team_ids)
    # Host assignment with optional override.
    host_kwargs: Dict[str, Any] = {"roles_held": ["HOST"], "qualifications": list(theme.get("required_host_qualifications") or [])}
    if commission_bps_override is not None:
        host_kwargs["commission_bps_override"] = commission_bps_override
    host_staff = create_staff_member(chain_id, **host_kwargs)
    host_assignment = create_staff_assignment(slot, venue, host_staff, role_type="HOST")
    # NPC staffing if required.
    npcs: List[Dict[str, Any]] = []
    for _ in range(int(theme.get("required_npc_count") or 0)):
        npc = create_staff_member(chain_id, roles_held=["NPC"], qualifications=[])
        npcs.append(create_staff_assignment(slot, venue, npc, role_type="NPC"))
    # Drive lifecycle.
    advance_clock_to(slot["starts_at"])
    start_slot(slot, venue)
    check_in_booking(booking, venue)
    advance_clock_to(add_minutes(slot["ends_at"], 1))
    completed_slot = complete_slot(slot, venue)
    refreshed_booking = get_booking(booking["id"])
    return {
        "chain_id": chain_id,
        "venue": venue,
        "room": room,
        "theme": theme,
        "slot": completed_slot,
        "lead_player": lead,
        "players": players,
        "booking": refreshed_booking,
        "host_staff": host_staff,
        "host_assignment": host_assignment,
        "npcs": npcs,
        "author_staff": author,
    }


def setup_finalized_settlement_around_slot(
    state: Dict[str, Any],
) -> Dict[str, Any]:
    """Take a state with a COMPLETED slot + SETTLED booking and produce a
    FINALIZED settlement run covering it. Returns updated state with key 'run'.
    """
    run = create_settlement_run_around_slot(state["slot"], state["chain_id"])
    finalized = finalize_settlement_run(run)
    state["run"] = finalized
    return state


def setup_public_teamup_slot(
    *,
    required_seats_for_launch: int = 2,
    max_players: int = 4,
    hours_ahead: float = 48.0,
    price_cents: int = 5000,
    deposit_policy_cents: int = 2000,
    match_preferences: Optional[Dict[str, Any]] = None,
    chain_id: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Build venue/room/theme/slot tuned for PUBLIC_TEAMUP matchmaking tests."""
    venue_overrides = {"deposit_policy_cents": deposit_policy_cents}
    theme_overrides = {
        "min_players": min(required_seats_for_launch, max_players),
        "max_players": max_players,
        "base_price_cents": price_cents,
    }
    venue, room, theme = setup_basic_scenario(
        chain_id=chain_id,
        venue_overrides=venue_overrides,
        theme_overrides=theme_overrides,
    )
    slot = create_session_slot(
        venue, room, theme,
        visibility="PUBLIC_TEAMUP",
        required_seats_for_launch=required_seats_for_launch,
        price_cents=price_cents,
        match_preferences=match_preferences,
        hours_ahead=hours_ahead,
    )
    return venue, room, theme, slot


def setup_slot_full_with_waitlist(
    *,
    chain_id: Optional[str] = None,
    deposit_policy_cents: int = 2000,
    price_cents: int = 5000,
) -> Dict[str, Any]:
    """A 4-seat slot fully filled by two confirmed bookings (2 + 2), with one
    QUEUED waitlist entry requesting 2 seats. Used to test promotion sweep.
    Returns dict with all necessary references.
    """
    if chain_id is None:
        chain_id = unique_chain_id()
    venue, room, theme = setup_basic_scenario(
        chain_id=chain_id,
        venue_overrides={"deposit_policy_cents": deposit_policy_cents},
        theme_overrides={"min_players": 2, "max_players": 4, "base_price_cents": price_cents},
    )
    slot = create_session_slot(
        venue, room, theme,
        visibility="PRIVATE_ONLY",
        required_seats_for_launch=2,
        hours_ahead=48.0,
        price_cents=price_cents,
    )
    # Two bookings of 2 seats each → confirmed_seat_count=4 (full).
    p1a, p1b = create_player(), create_player()
    p2a, p2b = create_player(), create_player()
    b1 = create_and_confirm_booking(slot, p1a, team_player_ids=[p1a["id"], p1b["id"]])
    b2 = create_and_confirm_booking(slot, p2a, team_player_ids=[p2a["id"], p2b["id"]])
    # Waitlist player (separate identity).
    waitlister = create_player()
    w1 = create_waitlist_entry(slot, waitlister, requested_seat_count=2)
    return {
        "chain_id": chain_id,
        "venue": venue,
        "room": room,
        "theme": theme,
        "slot": slot,
        "booking_1": b1,
        "booking_1_lead": p1a,
        "booking_2": b2,
        "booking_2_lead": p2a,
        "waitlist_entry": w1,
        "waitlister": waitlister,
    }


def setup_review_pending_moderation(
    *,
    theme_score: int = 5,
    venue_score: int = 5,
    host_score: Optional[int] = 5,
    comment: str = "A wonderful session, well worth the visit. Will return.",
    chain_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Drive a slot through to SETTLED, then submit a review. Returns dict
    {state..., review} where review.status starts as PENDING_MODERATION."""
    state = setup_slot_at_completed(chain_id=chain_id)
    review = submit_review(
        state["booking"], state["lead_player"],
        theme_score=theme_score, venue_score=venue_score, host_score=host_score,
        comment=comment,
    )
    state["review"] = review
    return state


# ──────────────────────────────────────────────────────────────────────────
# Tier 6 — Audit-log helper
# ──────────────────────────────────────────────────────────────────────────

def fetch_audit_log(
    *,
    subject_entity_type: Optional[str] = None,
    subject_entity_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    admin = TEST_USERS["platform_admin_headers"]
    params: Dict[str, Any] = {"limit": limit}
    if subject_entity_type is not None:
        params["subject_entity_type"] = subject_entity_type
    if subject_entity_id is not None:
        params["subject_entity_id"] = subject_entity_id
    if actor_user_id is not None:
        params["actor_user_id"] = actor_user_id
    resp = api_client.list_audit_log(admin, params=params)
    data = get_success_data(resp)
    if isinstance(data, list):
        return data
    return []


__all__ = [
    "now_iso", "add_minutes", "add_hours", "advance_clock_to",
    "create_venue", "create_player", "create_staff_member", "create_room",
    "create_published_theme", "create_session_slot",
    "setup_basic_scenario", "setup_scenario_with_slot",
    "create_booking", "confirm_booking", "create_and_confirm_booking",
    "cancel_booking_as_player", "cancel_booking_as_operator",
    "get_booking", "get_session_slot", "get_player",
    "create_staff_assignment", "assign_full_staffing",
    "start_slot", "complete_slot", "cancel_slot", "check_in_booking", "refund_booking",
    "setup_slot_with_confirmed_booking", "drive_slot_to_completed", "setup_slot_at_completed",
    "create_settlement_run_around_slot", "finalize_settlement_run", "get_settlement_run",
    "submit_review", "moderate_review", "get_review",
    "create_waitlist_entry", "list_waitlist_entries",
    "setup_settled_booking_with_split", "setup_finalized_settlement_around_slot",
    "setup_public_teamup_slot", "setup_slot_full_with_waitlist",
    "setup_review_pending_moderation",
    "fetch_audit_log",
]
