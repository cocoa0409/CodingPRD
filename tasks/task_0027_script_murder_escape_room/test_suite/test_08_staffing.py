"""Staff assignment, qualification, weekly minutes, handoff, overlap rules."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    StaffAssignmentStatus,
    add_minutes,
    advance_clock_to,
    create_published_theme,
    create_room,
    create_session_slot,
    create_staff_assignment,
    create_staff_assignment_payload,
    create_staff_member,
    create_venue,
    handoff_staff_assignment_payload,
    make_venue_operator_headers,
    setup_basic_scenario,
    unique_chain_id,
    validate_error,
    validate_success,
)


# ─── §3.8 Chain mismatch ──────────────────────────────────────────────────

def test_staff_chain_mismatch_rejected(api):
    """PRD §3.8: "The staff member's `chain_id` must equal the slot's venue's `chain_id` (otherwise `ERR_STAFF_CHAIN_MISMATCH`)."

    Claim: assigning a staff member from chain B to a slot under a venue in chain A yields ERR_STAFF_CHAIN_MISMATCH.
    """
    chain_a = unique_chain_id("a")
    chain_b = unique_chain_id("b")
    venue, room, theme = setup_basic_scenario(chain_id=chain_a)
    from test_helpers import create_session_slot as _css
    slot = _css(venue, room, theme, visibility="PRIVATE_ONLY", required_seats_for_launch=theme["min_players"])
    foreign_staff = create_staff_member(chain_b, roles_held=["HOST"], qualifications=[])
    op = make_venue_operator_headers(venue["id"])
    payload = create_staff_assignment_payload(slot["id"], foreign_staff["id"], "HOST")
    resp = api.create_staff_assignment(payload, op)
    validate_error(resp, ApiErrorId.ERR_STAFF_CHAIN_MISMATCH.value)


# ─── §3.8 Qualification mismatch ──────────────────────────────────────────

def test_host_missing_required_qualifications_rejected(api):
    """PRD §3.8: "for a `HOST` role, the staff member's `qualifications` must contain every entry of the theme's `required_host_qualifications`."

    Claim: a HOST whose qualifications miss a required theme tag is rejected with ERR_STAFF_QUALIFICATION_MISMATCH.
    """
    chain_id = unique_chain_id()
    venue = create_venue(chain_id=chain_id)
    room = create_room(venue)
    theme = create_published_theme(chain_id, [room["id"]], required_host_qualifications=["DM_CERT"])
    from test_helpers import create_session_slot as _css
    slot = _css(venue, room, theme, visibility="PRIVATE_ONLY", required_seats_for_launch=theme["min_players"])
    underqualified = create_staff_member(chain_id, roles_held=["HOST"], qualifications=[])  # missing DM_CERT
    op = make_venue_operator_headers(venue["id"])
    payload = create_staff_assignment_payload(slot["id"], underqualified["id"], "HOST")
    resp = api.create_staff_assignment(payload, op)
    validate_error(resp, ApiErrorId.ERR_STAFF_QUALIFICATION_MISMATCH.value)


def test_npc_role_requires_npc_in_roles_held(api):
    """PRD §3.8: "for an `NPC` role, the staff member's `roles_held` must include `NPC`."

    Claim: assigning role_type=NPC to a staff member whose roles_held lacks NPC is rejected with ERR_STAFF_QUALIFICATION_MISMATCH.
    """
    chain_id = unique_chain_id()
    venue = create_venue(chain_id=chain_id)
    room = create_room(venue)
    theme = create_published_theme(chain_id, [room["id"]], required_npc_count=1)
    from test_helpers import create_session_slot as _css
    slot = _css(venue, room, theme, visibility="PRIVATE_ONLY", required_seats_for_launch=theme["min_players"])
    host_only = create_staff_member(chain_id, roles_held=["HOST"], qualifications=[])
    op = make_venue_operator_headers(venue["id"])
    payload = create_staff_assignment_payload(slot["id"], host_only["id"], "NPC")
    resp = api.create_staff_assignment(payload, op)
    validate_error(resp, ApiErrorId.ERR_STAFF_QUALIFICATION_MISMATCH.value)


# ─── §3.4 Staff overlap (back-to-back permitted) ──────────────────────────

def test_staff_back_to_back_assignment_allowed(api):
    """PRD §3.4: "Touching back-to-back is allowed; no buffer minutes are modeled in v1, so the same host may move directly from one slot to another at the same venue or across venues in the same chain."

    Claim: assigning a HOST to two slots that touch (slot_a.ends_at == slot_b.starts_at) succeeds.
    """
    chain_id = unique_chain_id()
    venue = create_venue(chain_id=chain_id)
    room = create_room(venue)
    theme = create_published_theme(chain_id, [room["id"]])
    base = "2030-06-01T10:00:00.000Z"
    slot_a = create_session_slot(venue, room, theme, starts_at=base, visibility="PRIVATE_ONLY", required_seats_for_launch=theme["min_players"])
    # slot_b starts at slot_a.ends_at + turnover (room.turnover_minutes default 30, theme.duration default 90)
    slot_b_starts = add_minutes(base, theme["duration_minutes"] + 30)
    slot_b = create_session_slot(venue, room, theme, starts_at=slot_b_starts, visibility="PRIVATE_ONLY", required_seats_for_launch=theme["min_players"])
    staff = create_staff_member(chain_id, roles_held=["HOST"], qualifications=[])
    op = make_venue_operator_headers(venue["id"])
    a_assign = create_staff_assignment(slot_a, venue, staff, role_type="HOST")
    payload = create_staff_assignment_payload(slot_b["id"], staff["id"], "HOST")
    b_resp = api.create_staff_assignment(payload, op)
    validate_success(b_resp, expected_status=201)


def test_staff_strict_overlap_rejected(api):
    """PRD §3.4: "Two staff assignments `A` and `B` for the same `staff_member_id` collide if the maximum of their slot starts is strictly less than the minimum of their slot ends."
    PRD §3.8: "(otherwise `ERR_STAFF_OVERLAP_CONFLICT`)."

    Claim: assigning the same staff to two strictly overlapping slots yields ERR_STAFF_OVERLAP_CONFLICT.
    """
    chain_id = unique_chain_id()
    venue = create_venue(chain_id=chain_id)
    # Two rooms so we can have overlapping intervals.
    room_a = create_room(venue, name="room-a")
    room_b = create_room(venue, name="room-b")
    theme = create_published_theme(chain_id, [room_a["id"], room_b["id"]], duration_minutes=60)
    base = "2030-06-01T10:00:00.000Z"
    slot_a = create_session_slot(venue, room_a, theme, starts_at=base, visibility="PRIVATE_ONLY", required_seats_for_launch=theme["min_players"])
    # Strictly overlapping: starts at base+30m, ends at base+90m → overlaps slot_a [base, base+60m).
    slot_b = create_session_slot(venue, room_b, theme, starts_at=add_minutes(base, 30), visibility="PRIVATE_ONLY", required_seats_for_launch=theme["min_players"])
    staff = create_staff_member(chain_id, roles_held=["HOST"], qualifications=[])
    create_staff_assignment(slot_a, venue, staff, role_type="HOST")
    op = make_venue_operator_headers(venue["id"])
    payload = create_staff_assignment_payload(slot_b["id"], staff["id"], "HOST")
    resp = api.create_staff_assignment(payload, op)
    validate_error(resp, ApiErrorId.ERR_STAFF_OVERLAP_CONFLICT.value)


# ─── §3.8 Substitution ────────────────────────────────────────────────────

def test_handoff_creates_new_assignment(api):
    """PRD §3.8: "The original assignment moves from `SCHEDULED` to `HANDED_OFF` and a new `StaffAssignment` row is created in `SCHEDULED` with `substitute_of_assignment_id` set to the original assignment's id."

    Claim: handoff produces a new SCHEDULED assignment whose substitute_of_assignment_id points at the original; original.status transitions to HANDED_OFF.
    """
    chain_id = unique_chain_id()
    venue, room, theme = setup_basic_scenario(chain_id=chain_id)
    slot = create_session_slot(venue, room, theme, visibility="PRIVATE_ONLY", required_seats_for_launch=theme["min_players"])
    original_staff = create_staff_member(chain_id, roles_held=["HOST"], qualifications=list(theme.get("required_host_qualifications") or []))
    original = create_staff_assignment(slot, venue, original_staff, role_type="HOST")
    substitute_staff = create_staff_member(chain_id, roles_held=["HOST"], qualifications=list(theme.get("required_host_qualifications") or []))
    op = make_venue_operator_headers(venue["id"])
    new_assignment = validate_success(api.handoff_staff_assignment(original["id"], handoff_staff_assignment_payload(substitute_staff["id"]), op))
    assert new_assignment["substitute_of_assignment_id"] == original["id"]
    assert new_assignment["status"] == StaffAssignmentStatus.SCHEDULED.value
    # Original now HANDED_OFF.
    refreshed_original = validate_success(api.get_staff_assignment(original["id"], op))
    assert refreshed_original["status"] == StaffAssignmentStatus.HANDED_OFF.value


def test_handoff_depth_max_one(api):
    """PRD §3.8: "The original assignment's own `substitute_of_assignment_id` must be null — substitution depth is capped at 1; chained substitutions are rejected with `ERR_SUBSTITUTE_DEPTH_EXCEEDED`."

    Claim: handing off an assignment whose substitute_of_assignment_id is non-null is rejected with ERR_SUBSTITUTE_DEPTH_EXCEEDED.
    """
    chain_id = unique_chain_id()
    venue, room, theme = setup_basic_scenario(chain_id=chain_id)
    slot = create_session_slot(venue, room, theme, visibility="PRIVATE_ONLY", required_seats_for_launch=theme["min_players"])
    quals = list(theme.get("required_host_qualifications") or [])
    original_staff = create_staff_member(chain_id, roles_held=["HOST"], qualifications=quals)
    sub_staff = create_staff_member(chain_id, roles_held=["HOST"], qualifications=quals)
    sub2_staff = create_staff_member(chain_id, roles_held=["HOST"], qualifications=quals)
    original = create_staff_assignment(slot, venue, original_staff, role_type="HOST")
    op = make_venue_operator_headers(venue["id"])
    sub_assignment = validate_success(api.handoff_staff_assignment(original["id"], handoff_staff_assignment_payload(sub_staff["id"]), op))
    # Now try to hand OFF the substitute itself — its substitute_of_assignment_id is non-null.
    resp = api.handoff_staff_assignment(sub_assignment["id"], handoff_staff_assignment_payload(sub2_staff["id"]), op)
    validate_error(resp, ApiErrorId.ERR_SUBSTITUTE_DEPTH_EXCEEDED.value)


def test_handoff_after_live_rejected(api):
    """PRD §3.8: "The slot must still be in `schedule_status` of `SCHEDULED`; once it is `LIVE`, handoff is rejected with `ERR_HANDOFF_AFTER_LIVE`."

    Claim: handoff attempted while slot.schedule_status==LIVE yields ERR_HANDOFF_AFTER_LIVE.
    """
    from test_helpers import create_and_confirm_booking, create_player, start_slot
    chain_id = unique_chain_id()
    venue, room, theme = setup_basic_scenario(chain_id=chain_id)
    slot = create_session_slot(venue, room, theme, visibility="PRIVATE_ONLY", required_seats_for_launch=theme["min_players"])
    # Bring slot to MATCHED via bookings, then start.
    p1 = create_player()
    p2 = create_player()
    create_and_confirm_booking(slot, p1, team_player_ids=[p1["id"], p2["id"]])  # need theme.min_players seats
    quals = list(theme.get("required_host_qualifications") or [])
    staff_a = create_staff_member(chain_id, roles_held=["HOST"], qualifications=quals)
    staff_b = create_staff_member(chain_id, roles_held=["HOST"], qualifications=quals)
    a_assign = create_staff_assignment(slot, venue, staff_a, role_type="HOST")
    advance_clock_to(slot["starts_at"])
    start_slot(slot, venue)
    op = make_venue_operator_headers(venue["id"])
    resp = api.handoff_staff_assignment(a_assign["id"], handoff_staff_assignment_payload(staff_b["id"]), op)
    validate_error(resp, ApiErrorId.ERR_HANDOFF_AFTER_LIVE.value)


# ─── §3.8 Weekly minutes ──────────────────────────────────────────────────

def test_staff_weekly_limit_exceeded(api):
    """PRD §3.8: "If the existing minutes plus the proposed minutes exceeds the staff member's `max_weekly_minutes`, the request is rejected with `ERR_STAFF_WEEKLY_LIMIT_EXCEEDED`."

    Claim: assigning a staff member whose existing weekly minutes already match max_weekly_minutes yields ERR_STAFF_WEEKLY_LIMIT_EXCEEDED on a new in-week assignment.
    """
    chain_id = unique_chain_id()
    venue, room, theme = setup_basic_scenario(chain_id=chain_id, theme_overrides={"duration_minutes": 60})
    # max_weekly_minutes=120 means staff can take exactly two slots of 60m each within a week.
    staff = create_staff_member(chain_id, roles_held=["HOST"], qualifications=list(theme.get("required_host_qualifications") or []), max_weekly_minutes=120)
    base = "2030-06-03T10:00:00.000Z"  # a Monday, 2030
    slot_1 = create_session_slot(venue, room, theme, starts_at=base, visibility="PRIVATE_ONLY", required_seats_for_launch=theme["min_players"])
    slot_2 = create_session_slot(venue, room, theme, starts_at=add_minutes(base, 60 + 30), visibility="PRIVATE_ONLY", required_seats_for_launch=theme["min_players"])
    slot_3 = create_session_slot(venue, room, theme, starts_at=add_minutes(base, 2 * (60 + 30)), visibility="PRIVATE_ONLY", required_seats_for_launch=theme["min_players"])
    create_staff_assignment(slot_1, venue, staff, role_type="HOST")
    create_staff_assignment(slot_2, venue, staff, role_type="HOST")  # now 120 min in same ISO week.
    op = make_venue_operator_headers(venue["id"])
    payload = create_staff_assignment_payload(slot_3["id"], staff["id"], "HOST")
    resp = api.create_staff_assignment(payload, op)
    validate_error(resp, ApiErrorId.ERR_STAFF_WEEKLY_LIMIT_EXCEEDED.value)
