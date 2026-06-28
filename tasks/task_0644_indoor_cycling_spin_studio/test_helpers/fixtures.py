"""Composite setup helpers for the Spin Studio API.

Every fixture builds its preconditions from scratch via PRD-declared endpoints
(the test harness restarts the server with an empty database before each test).
Fixtures use get_success_data() internally so setup failures surface clearly.

Identity threading: after registering a Member or Instructor, ownership-gated calls
use make_member_headers(member_id) / make_instructor_headers(instructor_id) with the
real entity id — never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as api
from .test_users import (
    TEST_USERS,
    make_member_headers,
    make_instructor_headers,
)

MGR = TEST_USERS["studio_manager_headers"]
ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601):
    """Set the logical clock. Returns now_utc payload."""
    return get_success_data(api.set_clock(to_iso8601, MGR))


# ---------------------------------------------------------------------------
# Primitive creators (each returns the created resource dict)
# ---------------------------------------------------------------------------
def create_studio(name="Downtown", city="NYC", **overrides):
    payload = {"name": name, "city": city}
    payload.update(overrides)
    return get_success_data(api.create_studio(payload, MGR))


def create_room(studio_id, name="Main"):
    return get_success_data(api.create_room(studio_id, {"name": name}, MGR))


def create_bike(studio_id, room_id, position_row=1, position_col=1, label="A1"):
    return get_success_data(
        api.create_bike(
            studio_id,
            room_id,
            {"position_row": position_row, "position_col": position_col, "label": label},
            MGR,
        )
    )


def create_instructor(email="i1@x.com", full_name="Instr One"):
    return get_success_data(
        api.create_instructor({"email": email, "full_name": full_name}, MGR)
    )


def register_member(home_studio_id, email="m1@x.com", full_name="Mem One"):
    return get_success_data(
        api.register_member(
            {"email": email, "full_name": full_name, "home_studio_id": home_studio_id},
            ANON,
        )
    )


def create_credit_pack(
    member_id,
    kind="CLASS_PACK",
    purchased_credits=5,
    price_cents=5000,
    expires_at="2026-12-31T00:00:00Z",
    **overrides,
):
    payload = {
        "member_id": member_id,
        "kind": kind,
        "purchased_credits": purchased_credits,
        "price_cents": price_cents,
        "expires_at": expires_at,
    }
    payload.update(overrides)
    return get_success_data(
        api.create_credit_pack(payload, make_member_headers(member_id))
    )


def create_session(
    studio_id,
    room_id,
    instructor_id,
    start_utc="2026-06-20T18:00:00Z",
    end_utc="2026-06-20T19:00:00Z",
    **overrides,
):
    payload = {
        "room_id": room_id,
        "instructor_id": instructor_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
    }
    payload.update(overrides)
    return get_success_data(api.create_session(studio_id, payload, MGR))


def create_product(studio_id, sku="BOTTLE", name="Water Bottle", unit_price_cents=1000, stock_qty=10):
    return get_success_data(
        api.create_product(
            studio_id,
            {"sku": sku, "name": name, "unit_price_cents": unit_price_cents, "stock_qty": stock_qty},
            MGR,
        )
    )


def book(studio_id, session_id, member_id, bike_id, expected_session_version, **overrides):
    """Book a bike. Returns the created reservation (raises on setup failure)."""
    payload = {
        "member_id": member_id,
        "bike_id": bike_id,
        "expected_session_version": expected_session_version,
    }
    payload.update(overrides)
    return get_success_data(
        api.create_reservation(studio_id, session_id, payload, make_member_headers(member_id))
    )


def check_in(studio_id, session_id, reservation_id, instructor_id):
    return get_success_data(
        api.check_in_reservation(
            studio_id, session_id, reservation_id, make_instructor_headers(instructor_id)
        )
    )


def cancel_reservation(studio_id, session_id, reservation_id, member_id):
    return get_success_data(
        api.cancel_reservation(
            studio_id, session_id, reservation_id, make_member_headers(member_id)
        )
    )


def join_waitlist(studio_id, session_id, member_id, credit_pack_id):
    return get_success_data(
        api.join_waitlist(
            studio_id,
            session_id,
            {"member_id": member_id, "credit_pack_id": credit_pack_id},
            make_member_headers(member_id),
        )
    )


def get_session(session_id, member_id=None):
    headers = make_member_headers(member_id) if member_id else MGR
    return get_success_data(api.get_session(session_id, headers))


def get_pack(pack_id, member_id=None):
    headers = make_member_headers(member_id) if member_id else MGR
    return get_success_data(api.get_credit_pack(pack_id, headers))


def get_member(member_id):
    return get_success_data(api.get_member(member_id, make_member_headers(member_id)))


# ---------------------------------------------------------------------------
# Tier 1/2: Base estate setup helpers
# ---------------------------------------------------------------------------
def setup_studio_estate(n_bikes=1, clock="2026-06-01T00:00:00Z", **studio_overrides):
    """Set clock, create a studio + one room + n ACTIVE bikes + one instructor.

    Returns dict: studio, room, bikes (list), instructor.
    """
    set_clock(clock)
    studio = create_studio(**studio_overrides)
    room = create_room(studio["id"])
    bikes = []
    for i in range(n_bikes):
        bikes.append(
            create_bike(
                studio["id"], room["id"], position_row=1, position_col=i + 1, label=f"A{i + 1}"
            )
        )
    instructor = create_instructor()
    return {
        "studio": studio,
        "room": room,
        "bikes": bikes,
        "instructor": instructor,
    }


def setup_member_with_pack(
    studio_id,
    email="m1@x.com",
    full_name="Mem One",
    kind="CLASS_PACK",
    purchased_credits=5,
    price_cents=5000,
    expires_at="2026-12-31T00:00:00Z",
    **pack_overrides,
):
    """Register a member at studio_id and grant one credit pack. Returns (member, pack)."""
    member = register_member(studio_id, email=email, full_name=full_name)
    pack = create_credit_pack(
        member["id"],
        kind=kind,
        purchased_credits=purchased_credits,
        price_cents=price_cents,
        expires_at=expires_at,
        **pack_overrides,
    )
    return member, pack


def setup_booking_ready(
    n_bikes=1,
    start_utc="2026-06-20T18:00:00Z",
    end_utc="2026-06-20T19:00:00Z",
    clock="2026-06-01T00:00:00Z",
    purchased_credits=5,
    **session_overrides,
):
    """Full estate + a member with a pack + a scheduled future session.

    Returns dict: studio, room, bikes, instructor, member, pack, session.
    The session is freshly created so session['version'] is its current version.
    """
    estate = setup_studio_estate(n_bikes=n_bikes, clock=clock)
    member, pack = setup_member_with_pack(
        estate["studio"]["id"], purchased_credits=purchased_credits
    )
    session = create_session(
        estate["studio"]["id"],
        estate["room"]["id"],
        estate["instructor"]["id"],
        start_utc=start_utc,
        end_utc=end_utc,
        **session_overrides,
    )
    return {
        **estate,
        "member": member,
        "pack": pack,
        "session": session,
    }


# ---------------------------------------------------------------------------
# Tier 3: Lifecycle shortcuts
# ---------------------------------------------------------------------------
def setup_booked_reservation(
    n_bikes=1,
    start_utc="2026-06-20T18:00:00Z",
    end_utc="2026-06-20T19:00:00Z",
    clock="2026-06-01T00:00:00Z",
    purchased_credits=5,
    shoe_size=None,
):
    """Estate + member + pack + session + one booked reservation on bike[0].

    Returns dict with all of setup_booking_ready plus 'reservation'.
    """
    ctx = setup_booking_ready(
        n_bikes=n_bikes,
        start_utc=start_utc,
        end_utc=end_utc,
        clock=clock,
        purchased_credits=purchased_credits,
    )
    overrides = {}
    if shoe_size is not None:
        overrides["shoe_size"] = shoe_size
    reservation = book(
        ctx["studio"]["id"],
        ctx["session"]["id"],
        ctx["member"]["id"],
        ctx["bikes"][0]["id"],
        ctx["session"]["version"],
        **overrides,
    )
    ctx["reservation"] = reservation
    return ctx


def setup_attended_reservation(
    n_bikes=1,
    start_utc="2026-06-02T10:00:00Z",
    end_utc="2026-06-02T11:00:00Z",
    book_clock="2026-06-01T00:00:00Z",
    checkin_clock="2026-06-02T10:30:00Z",
    purchased_credits=5,
):
    """Estate + member + pack + session + booked + checked-in (ATTENDED) reservation.

    Returns dict with all of setup_booked_reservation (reservation now ATTENDED).
    """
    ctx = setup_booked_reservation(
        n_bikes=n_bikes,
        start_utc=start_utc,
        end_utc=end_utc,
        clock=book_clock,
        purchased_credits=purchased_credits,
    )
    set_clock(checkin_clock)
    check_in(
        ctx["studio"]["id"],
        ctx["session"]["id"],
        ctx["reservation"]["id"],
        ctx["instructor"]["id"],
    )
    return ctx


def setup_member_past_first_ride(
    studio_id,
    room_id,
    instructor_id,
    bike_id,
    purchased_credits=5,
    price_cents=5000,
    first_ride_start="2026-06-02T10:00:00Z",
    first_ride_end="2026-06-02T11:00:00Z",
    first_ride_checkin="2026-06-02T10:30:00Z",
    **pack_overrides,
):
    """Register a member, grant a CLASS_PACK, then book + check in one ride so the
    first-ride comp is consumed and the pack still has all its credits (the comp debits
    no credit). After this the member's NEXT booking debits a real pack credit.

    Returns (member, pack). The pack's remaining_credits still equals purchased_credits.
    """
    member = register_member(studio_id, email="m1@x.com", full_name="Mem One")
    pack = create_credit_pack(
        member["id"],
        kind="CLASS_PACK",
        purchased_credits=purchased_credits,
        price_cents=price_cents,
        **pack_overrides,
    )
    s = create_session(
        studio_id, room_id, instructor_id,
        start_utc=first_ride_start, end_utc=first_ride_end,
    )
    r = book(studio_id, s["id"], member["id"], bike_id, s["version"])
    set_clock(first_ride_checkin)
    check_in(studio_id, s["id"], r["id"], instructor_id)
    return member, pack


# ---------------------------------------------------------------------------
# Tier 4: Strike accumulation toward suspension threshold
# ---------------------------------------------------------------------------
def setup_member_with_late_cancels(
    num_strikes,
    clock="2026-06-01T00:00:00Z",
    final_strike=True,
):
    """Build a member who accrues `num_strikes` strike-bearing LATE_CANCELs.

    Each late cancel is performed on its own future session: the member books, then
    the clock is advanced strictly inside the late-cancel window (default 12h) and
    the booking is cancelled, producing a LATE_CANCEL penalty (a strike).

    If final_strike is False, the final (num_strikes-th) reservation is left BOOKED
    and NOT yet cancelled so the caller can trigger the last cancel as the test action.
    In that case the return dict carries 'pending_session' and 'pending_reservation'
    and 'pending_cancel_clock'.

    Returns dict: studio, room, bikes, instructor, member, pack, plus the above.
    """
    estate = setup_studio_estate(n_bikes=1, clock=clock)
    studio_id = estate["studio"]["id"]
    member, pack = setup_member_with_pack(studio_id, purchased_credits=10)
    bike_id = estate["bikes"][0]["id"]
    instr_id = estate["instructor"]["id"]

    # Sessions on consecutive evenings; cancel each at noon same day (inside 12h window
    # since start is 18:00 and window is 720 minutes -> boundary at 06:00; noon is late).
    sessions = []
    reservations = []
    for i in range(num_strikes):
        day = 5 + i  # 2026-06-05, 06, 07, ...
        s = create_session(
            studio_id,
            estate["room"]["id"],
            instr_id,
            start_utc=f"2026-06-{day:02d}T18:00:00Z",
            end_utc=f"2026-06-{day:02d}T19:00:00Z",
        )
        sessions.append(s)
        r = book(studio_id, s["id"], member["id"], bike_id, s["version"])
        reservations.append(r)

    # Cancel the first (num_strikes - 1) (or all if final_strike) inside the late window.
    to_cancel = num_strikes if final_strike else num_strikes - 1
    for i in range(to_cancel):
        day = 5 + i
        set_clock(f"2026-06-{day:02d}T12:00:00Z")
        cancel_reservation(studio_id, sessions[i]["id"], reservations[i]["id"], member["id"])

    result = {
        **estate,
        "member": member,
        "pack": pack,
        "sessions": sessions,
        "reservations": reservations,
    }
    if not final_strike:
        last = num_strikes - 1
        result["pending_session"] = sessions[last]
        result["pending_reservation"] = reservations[last]
        result["pending_cancel_clock"] = f"2026-06-{5 + last:02d}T12:00:00Z"
    return result


# ---------------------------------------------------------------------------
# Tier 5: Full session / capacity scenarios
# ---------------------------------------------------------------------------
def setup_full_session_two_members(
    clock="2026-06-01T00:00:00Z",
    start_utc="2026-06-20T18:00:00Z",
    end_utc="2026-06-20T19:00:00Z",
):
    """A 1-bike session booked to capacity by member A; member B exists with a pack
    but holds no reservation on the session.

    Returns dict: studio, room, bikes, instructor, member_a, pack_a, member_b, pack_b,
    session, reservation_a. The session's live version is re-read into
    session['version'] AFTER member A's booking, so it is current for member B.
    """
    estate = setup_studio_estate(n_bikes=1, clock=clock)
    studio_id = estate["studio"]["id"]
    member_a, pack_a = setup_member_with_pack(studio_id, email="ma@x.com", full_name="Mem A")
    member_b, pack_b = setup_member_with_pack(studio_id, email="mb@x.com", full_name="Mem B")
    session = create_session(
        studio_id, estate["room"]["id"], estate["instructor"]["id"],
        start_utc=start_utc, end_utc=end_utc,
    )
    reservation_a = book(
        studio_id, session["id"], member_a["id"], estate["bikes"][0]["id"], session["version"]
    )
    # Re-read live session version for member B's perspective.
    live = get_session(session["id"], member_b["id"])
    session["version"] = live["version"]
    return {
        **estate,
        "member_a": member_a,
        "pack_a": pack_a,
        "member_b": member_b,
        "pack_b": pack_b,
        "session": session,
        "reservation_a": reservation_a,
    }


def setup_full_session_with_waitlist(
    clock="2026-06-01T00:00:00Z",
    start_utc="2026-06-20T18:00:00Z",
    end_utc="2026-06-20T19:00:00Z",
    waitlist_capacity=None,
    n_waiters=1,
):
    """A 1-bike session fully booked by member A, with `n_waiters` distinct members
    queued on the waitlist (each with their own pre-authorized 5-credit pack).

    Returns dict: studio, room, bikes, instructor, member_a, pack_a, reservation_a,
    session, waiters (list of {member, pack, entry}).
    The session version reflects the state after member A's booking.
    """
    estate = setup_studio_estate(n_bikes=1, clock=clock)
    studio_id = estate["studio"]["id"]
    member_a, pack_a = setup_member_with_pack(studio_id, email="ma@x.com", full_name="Mem A")
    session_overrides = {}
    if waitlist_capacity is not None:
        session_overrides["waitlist_capacity"] = waitlist_capacity
    session = create_session(
        studio_id, estate["room"]["id"], estate["instructor"]["id"],
        start_utc=start_utc, end_utc=end_utc, **session_overrides,
    )
    reservation_a = book(
        studio_id, session["id"], member_a["id"], estate["bikes"][0]["id"], session["version"]
    )
    waiters = []
    for i in range(n_waiters):
        m, p = setup_member_with_pack(
            studio_id, email=f"w{i}@x.com", full_name=f"Waiter {i}"
        )
        entry = join_waitlist(studio_id, session["id"], m["id"], p["id"])
        waiters.append({"member": m, "pack": p, "entry": entry})
    live = get_session(session["id"], member_a["id"])
    session["version"] = live["version"]
    return {
        **estate,
        "member_a": member_a,
        "pack_a": pack_a,
        "reservation_a": reservation_a,
        "session": session,
        "waiters": waiters,
    }


# ---------------------------------------------------------------------------
# Two-studio / multi-studio scenarios
# ---------------------------------------------------------------------------
def setup_two_studios(clock="2026-06-01T00:00:00Z"):
    """Two studios A and B, each with one room and one ACTIVE bike, plus one shared
    instructor.

    Returns dict: studio_a, room_a, bike_a, studio_b, room_b, bike_b, instructor.
    """
    set_clock(clock)
    studio_a = create_studio(name="StudioA", city="NYC")
    studio_b = create_studio(name="StudioB", city="LA")
    room_a = create_room(studio_a["id"], name="MainA")
    bike_a = create_bike(studio_a["id"], room_a["id"], label="A1")
    room_b = create_room(studio_b["id"], name="MainB")
    bike_b = create_bike(studio_b["id"], room_b["id"], label="B1")
    instructor = create_instructor()
    return {
        "studio_a": studio_a,
        "room_a": room_a,
        "bike_a": bike_a,
        "studio_b": studio_b,
        "room_b": room_b,
        "bike_b": bike_b,
        "instructor": instructor,
    }
