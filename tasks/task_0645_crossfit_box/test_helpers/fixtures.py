"""Composite setup helpers.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints, because the harness restarts the server (empty DB) before every
test. Helpers use get_success_data() so setup failures surface as clear
"Setup failed" errors rather than confusing assertion failures.

Identity threading: Coach and Member are entity_backed roles. After creating
such an entity, ownership-gated calls use make_coach_headers(coach_id) /
make_member_headers(member_id) with the real entity id — never a shared
constant, which would never equal a real id and so fail every ownership check.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import (
    TEST_USERS,
    make_member_headers,
    make_coach_headers,
)
from . import factories as fac


BOX = TEST_USERS["box_manager_headers"]
ANON = TEST_USERS["anonymous_headers"]


# --- Low-level building blocks --------------------------------------------

def set_clock(iso8601: str):
    """Set the server logical clock (BoxManager-only)."""
    get_success_data(api_client.set_clock({"to_iso8601": iso8601}, BOX))


def create_coach(certified: bool = True, **overrides) -> dict:
    payload = fac.create_coach_payload(certified=certified, **overrides)
    return get_success_data(api_client.create_coach(payload, BOX))


def create_track(head_coach_id: str, track_type: str = "REGULAR", **overrides) -> dict:
    payload = fac.create_program_track_payload(
        head_coach_id, track_type=track_type, **overrides
    )
    return get_success_data(api_client.create_program_track(payload, BOX))


def create_unlimited_plan(**overrides) -> dict:
    payload = fac.create_unlimited_plan_payload(**overrides)
    return get_success_data(api_client.create_membership_plan(payload, BOX))


def create_punch_plan(punch_count: int = 5, **overrides) -> dict:
    payload = fac.create_punch_plan_payload(punch_count=punch_count, **overrides)
    return get_success_data(api_client.create_membership_plan(payload, BOX))


def register_member(home_box_member: bool = True, **overrides) -> dict:
    payload = fac.register_member_payload(home_box_member=home_box_member, **overrides)
    return get_success_data(api_client.register_member(payload, ANON))


def create_session(track_id, coach_id, starts_at, **overrides) -> dict:
    """Create a SCHEDULED session. Coach role is the head coach (entity_backed)."""
    payload = fac.create_session_payload(track_id, coach_id, starts_at, **overrides)
    return get_success_data(api_client.create_session(payload, make_coach_headers(coach_id)))


def create_membership(member_id, plan_id) -> dict:
    payload = fac.create_membership_payload(member_id, plan_id)
    return get_success_data(api_client.create_membership(payload, make_member_headers(member_id)))


def confirm_payment(membership_id) -> dict:
    return get_success_data(api_client.confirm_payment(membership_id, BOX))


def complete_foundations(membership_id, coach_id) -> dict:
    return get_success_data(
        api_client.complete_foundations(
            {"membership_id": membership_id}, make_coach_headers(coach_id)
        )
    )


def reserve(session_id, member_id, expected_session_version,
            membership_id=None, reservation_kind="MEMBERSHIP") -> dict:
    payload = fac.create_reservation_payload(
        session_id, member_id, reservation_kind, expected_session_version,
        membership_id=membership_id,
    )
    return get_success_data(
        api_client.create_reservation(payload, make_member_headers(member_id))
    )


# --- Tier 1/2: active membership for a member -----------------------------

def create_active_membership(member_id, plan_id) -> dict:
    """Create a membership and activate it (PENDING_PAYMENT -> ACTIVE)."""
    ms = create_membership(member_id, plan_id)
    return confirm_payment(ms["id"])


def setup_track_coach_plan(track_type: str = "REGULAR", requires_foundations: bool = False,
                           plan_kind: str = "UNLIMITED", punch_count: int = 5):
    """Active-coach + track + plan trio shared by most reservation scenarios.

    Returns (coach, track, plan).
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type=track_type)
    if plan_kind == "PUNCH":
        plan = create_punch_plan(punch_count=punch_count,
                                 requires_foundations=requires_foundations)
    else:
        plan = create_unlimited_plan(requires_foundations=requires_foundations)
    return coach, track, plan


def setup_member_with_active_membership(plan_id):
    """Register a member and give them an ACTIVE membership on plan_id.

    Returns (member, membership).
    """
    member = register_member(home_box_member=True)
    membership = create_active_membership(member["id"], plan_id)
    return member, membership


# --- Tier 3: a member holding one RESERVED seat on a session --------------

def setup_reserved_seat(session_starts_at: str,
                        clock_before: str = "2026-06-01T00:00:00Z",
                        capacity: int = 5,
                        drop_in_fee_cents: int = 0):
    """Foundations-free REGULAR session with one member holding a RESERVED seat.

    Walks: coach -> track -> unlimited plan -> set clock -> session ->
    member -> active membership -> reserve (MEMBERSHIP).
    Returns dict with coach, track, plan, session (post-reserve GET),
    member, membership, reservation, and session_version_after_reserve.
    """
    coach, track, plan = setup_track_coach_plan(
        track_type="REGULAR", requires_foundations=False, plan_kind="UNLIMITED"
    )
    set_clock(clock_before)
    session = create_session(track["id"], coach["id"], session_starts_at,
                             capacity=capacity, drop_in_fee_cents=drop_in_fee_cents)
    member, membership = setup_member_with_active_membership(plan["id"])
    reservation = reserve(session["id"], member["id"], session["version"],
                          membership_id=membership["id"],
                          reservation_kind="MEMBERSHIP")
    session_after = get_success_data(api_client.get_session(session["id"], BOX))
    return {
        "coach": coach,
        "track": track,
        "plan": plan,
        "session": session_after,
        "member": member,
        "membership": membership,
        "reservation": reservation,
        "session_version_after_reserve": session_after["version"],
    }


def setup_drop_in_reserved_seat(session_starts_at: str,
                                clock_before: str = "2026-06-01T00:00:00Z",
                                drop_in_fee_cents: int = 2500,
                                capacity: int = 5):
    """Foundations-free REGULAR session with a visiting athlete holding a
    DROP_IN RESERVED seat (charged drop_in_fee_cents).

    Returns dict with coach, track, session, visitor (member), reservation.
    """
    coach = create_coach(certified=True)
    track = create_track(coach["id"], track_type="REGULAR")
    set_clock(clock_before)
    session = create_session(track["id"], coach["id"], session_starts_at,
                             capacity=capacity, drop_in_fee_cents=drop_in_fee_cents)
    visitor = register_member(home_box_member=False)
    reservation = reserve(session["id"], visitor["id"], session["version"],
                          membership_id=None, reservation_kind="DROP_IN")
    return {
        "coach": coach,
        "track": track,
        "session": session,
        "visitor": visitor,
        "reservation": reservation,
    }


# --- Tier 4: a member suspended via 3 no-show strikes ---------------------

def setup_suspended_member(clock_setup: str = "2026-06-01T00:00:00Z",
                           clock_after_complete: str = "2026-06-05T00:00:00Z"):
    """Drive a member to reservation_suspended=true via 3 NO_SHOW strikes.

    Creates 3 REGULAR sessions (foundations-free, UNLIMITED), reserves each,
    advances the clock past their start, and completes each marking the
    member a NO_SHOW. Returns dict with coach, track, plan, member,
    membership, and the three sessions/reservations.
    """
    coach, track, plan = setup_track_coach_plan(
        track_type="REGULAR", requires_foundations=False, plan_kind="UNLIMITED"
    )
    set_clock(clock_setup)
    member, membership = setup_member_with_active_membership(plan["id"])

    sessions = []
    reservations = []
    starts = ["2026-06-02T18:00:00Z", "2026-06-03T18:00:00Z", "2026-06-04T18:00:00Z"]
    for st in starts:
        sess = create_session(track["id"], coach["id"], st, capacity=3)
        rv = reserve(sess["id"], member["id"], sess["version"],
                     membership_id=membership["id"], reservation_kind="MEMBERSHIP")
        sessions.append(sess)
        reservations.append(rv)

    set_clock(clock_after_complete)
    for sess, rv in zip(sessions, reservations):
        get_success_data(api_client.complete_session(
            sess["id"], {"attendance": {rv["id"]: "NO_SHOW"}},
            make_coach_headers(coach["id"]),
        ))

    return {
        "coach": coach,
        "track": track,
        "plan": plan,
        "member": member,
        "membership": membership,
        "sessions": sessions,
        "reservations": reservations,
    }


# --- Tier: capacity-1 session with held seat + waitlisted entry -----------

def setup_full_session_with_waitlist(session_starts_at: str = "2026-06-10T18:00:00Z",
                                     clock_before: str = "2026-06-01T00:00:00Z"):
    """Capacity-1 foundations-free session: m_hold holds the seat (RESERVED),
    m_wait is WAITLISTED at position 1.

    Returns dict with coach, track, plan, session, hold (member/membership/
    reservation), wait (member/membership/reservation).
    """
    coach, track, plan = setup_track_coach_plan(
        track_type="REGULAR", requires_foundations=False, plan_kind="UNLIMITED"
    )
    set_clock(clock_before)
    session = create_session(track["id"], coach["id"], session_starts_at, capacity=1)

    m_hold, ms_hold = setup_member_with_active_membership(plan["id"])
    rv_hold = reserve(session["id"], m_hold["id"], session["version"],
                      membership_id=ms_hold["id"], reservation_kind="MEMBERSHIP")
    session_v1 = get_success_data(api_client.get_session(session["id"], BOX))["version"]

    m_wait, ms_wait = setup_member_with_active_membership(plan["id"])
    rv_wait = reserve(session["id"], m_wait["id"], session_v1,
                      membership_id=ms_wait["id"], reservation_kind="MEMBERSHIP")

    return {
        "coach": coach,
        "track": track,
        "plan": plan,
        "session": session,
        "hold": {"member": m_hold, "membership": ms_hold, "reservation": rv_hold},
        "wait": {"member": m_wait, "membership": ms_wait, "reservation": rv_wait},
    }


# --- Tier: a team (FORMING) with one outstanding INVITED member -----------

def setup_team_with_invite(max_roster_size: int = 4):
    """Captain creates a FORMING team and invites one member (INVITED).

    Returns dict with captain, invitee, team, team_member (invite slot).
    """
    captain = register_member(home_box_member=True)
    invitee = register_member(home_box_member=True)
    team = get_success_data(api_client.create_team(
        fac.create_team_payload(captain["id"], max_roster_size=max_roster_size),
        make_member_headers(captain["id"]),
    ))
    tm = get_success_data(api_client.create_team_member(
        fac.create_team_member_payload(team["id"], invitee["id"]),
        make_member_headers(captain["id"]),
    ))
    return {"captain": captain, "invitee": invitee, "team": team, "team_member": tm}


# --- Tier: leaderboard-eligible member -----------------------------------

def make_leaderboard_eligible_member(coach_id, track_id, plan_id, session_starts_at):
    """Register a member and make them leaderboard-eligible for `track_id`.

    PRD §3.6 restricts the leaderboard candidate set to "members who hold an
    `ACTIVE` membership on a plan attached to a session of the requested
    track". To realize that precondition this helper gives the member an
    ACTIVE membership on `plan_id` and reserves them a seat on a session of
    `track_id`, attaching the plan to a session of the track.

    The clock defaults to 2026-01-01T00:00:00Z, so `session_starts_at` must be
    >= 60 minutes ahead for the reservation window to be open; callers pass a
    distinct `session_starts_at` per member so the shared coach is not
    double-booked.

    Returns the member dict.
    """
    member = register_member(home_box_member=True)
    membership = create_active_membership(member["id"], plan_id)
    session = create_session(track_id, coach_id, session_starts_at, capacity=5)
    reserve(session["id"], member["id"], session["version"],
            membership_id=membership["id"], reservation_kind="MEMBERSHIP")
    return member


# --- Tier: a verified benchmark result for leaderboard tests --------------

def record_and_verify_result(member_id, coach_id, benchmark_name, metric_kind,
                             value, recorded_at):
    """Record a benchmark result (as the member) and verify it (as a certified coach).

    Returns the verified result.
    """
    result = get_success_data(api_client.create_benchmark_result(
        fac.create_benchmark_result_payload(
            member_id, benchmark_name, metric_kind, value, recorded_at
        ),
        make_member_headers(member_id),
    ))
    return get_success_data(
        api_client.verify_benchmark_result(result["id"], make_coach_headers(coach_id))
    )
