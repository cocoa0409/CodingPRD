"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures
produce clear "Setup failed" errors rather than confusing assertion failures.

Identity threading: after creating an Instructor or Member, every ownership-gated
call uses make_instructor_headers(instructor["id"]) / make_member_headers(
member["id"]) — never a shared constant — so ownership checks pass.

The whole API is mounted under /culinary; the server starts against an empty
database before every test, so each helper builds its preconditions from scratch.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_instructor_payload,
    create_member_payload,
    create_template_payload,
    create_series_payload,
    create_session_payload,
    create_ingredient_line_payload,
    create_booking_payload,
    create_waitlist_payload,
    create_substitution_payload,
    create_gift_card_payload,
    create_wallet_adjustment_payload,
)
from .test_users import (
    TEST_USERS,
    make_instructor_headers,
    make_member_headers,
)

ADMIN = TEST_USERS["studio_admin_headers"]


# ─── Atomic creators ────────────────────────────────────────────────
def create_instructor(max_skill_level="PROFESSIONAL", **overrides):
    res = api_client.create_instructor(
        create_instructor_payload(max_skill_level=max_skill_level, **overrides), ADMIN
    )
    return get_success_data(res)


def create_member(**overrides):
    res = api_client.create_member(create_member_payload(**overrides), ADMIN)
    return get_success_data(res)


def create_published_template(**overrides):
    """Create a template then publish it. Returns the PUBLISHED template."""
    res = api_client.create_template(create_template_payload(**overrides), ADMIN)
    tmpl = get_success_data(res)
    pub = api_client.publish_template(tmpl["id"], ADMIN)
    return get_success_data(pub)


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def seed_wallet(member_id, amount_cents):
    res = api_client.adjust_wallet(
        member_id, create_wallet_adjustment_payload(amount_cents), ADMIN
    )
    return get_success_data(res)


def create_gift_card(member_id, initial_value_cents, **overrides):
    res = api_client.create_gift_card(
        create_gift_card_payload(member_id, initial_value_cents, **overrides),
        make_member_headers(member_id),
    )
    return get_success_data(res)


def add_ingredient_line(session_id, instructor_id, **overrides):
    res = api_client.create_ingredient_line(
        session_id, create_ingredient_line_payload(**overrides),
        make_instructor_headers(instructor_id),
    )
    return get_success_data(res)


# ─── Tier 1/2: Session creation + opening ───────────────────────────
def create_session(template_id, instructor_id, **overrides):
    """Create a standalone SCHEDULED session. Returns the session."""
    res = api_client.create_session(
        create_session_payload(template_id, instructor_id, **overrides), ADMIN
    )
    return get_success_data(res)


def create_open_session(
    instructor_max_skill="PROFESSIONAL",
    template_overrides=None,
    session_overrides=None,
    ingredient_overrides=None,
):
    """
    Full chain to an OPEN GROUP session with one ingredient line:
    instructor -> published template -> session -> ingredient line -> open.

    Returns (instructor, template, session) where `session` is the OPEN session.
    """
    instructor = create_instructor(max_skill_level=instructor_max_skill)
    template = create_published_template(**(template_overrides or {}))
    session = create_session(
        template["id"], instructor["id"], **(session_overrides or {})
    )
    add_ingredient_line(session["id"], instructor["id"], **(ingredient_overrides or {}))
    opened = get_success_data(
        api_client.open_session(session["id"], make_instructor_headers(instructor["id"]))
    )
    return instructor, template, opened


def get_session_version(session_id):
    return get_success_data(api_client.get_session(session_id, ADMIN))["version"]


def get_gift_card_version(gift_card_id, member_id):
    return get_success_data(
        api_client.get_gift_card(gift_card_id, make_member_headers(member_id))
    )["version"]


# ─── Tier 3: Booking lifecycle shortcuts ────────────────────────────
def create_booking(session_id, member_id, seats_requested=1, **overrides):
    res = api_client.create_booking(
        create_booking_payload(session_id, member_id, seats_requested, **overrides),
        make_member_headers(member_id),
    )
    return get_success_data(res)


def confirm_booking(booking_id, session_id, member_id):
    """Confirm a PENDING booking using the session's current version (OCC)."""
    sv = get_session_version(session_id)
    res = api_client.confirm_booking(booking_id, sv, make_member_headers(member_id))
    return get_success_data(res)


def create_confirmed_booking(session_id, member_id, seats_requested=1, **overrides):
    """Create a booking and confirm it. Returns the confirmed booking."""
    booking = create_booking(session_id, member_id, seats_requested, **overrides)
    return confirm_booking(booking["id"], session_id, member_id)


def setup_confirmed_booking_scenario(
    instructor_max_skill="PROFESSIONAL",
    template_overrides=None,
    session_overrides=None,
    seats_requested=1,
    clock=None,
):
    """
    Open session + a registered member holding a CONFIRMED booking.

    Returns (instructor, template, session, member, booking) where booking is
    CONFIRMED. The session is re-fetched so confirmed_seats/version are current.
    """
    if clock is not None:
        set_clock(clock)
    instructor, template, session = create_open_session(
        instructor_max_skill=instructor_max_skill,
        template_overrides=template_overrides,
        session_overrides=session_overrides,
    )
    member = create_member()
    booking = create_confirmed_booking(session["id"], member["id"], seats_requested)
    session = get_success_data(api_client.get_session(session["id"], ADMIN))
    return instructor, template, session, member, booking


# ─── Substitution scenario shortcut ─────────────────────────────────
def request_substitution(booking_id, ingredient_line_id, alternate_unit_cost_cents, member_id):
    res = api_client.create_substitution(
        create_substitution_payload(
            booking_id, ingredient_line_id, alternate_unit_cost_cents
        ),
        make_member_headers(member_id),
    )
    return get_success_data(res)


def setup_requested_substitution(
    skill_level="BEGINNER",
    base_price_cents=5000,
    seats_requested=1,
    dietary_tag="CONTAINS_NUT",
    line_unit_cost_cents=500,
    line_qty_per_seat=0.02,
    alternate_unit_cost_cents=900,
):
    """
    A CONFIRMED booking on a session with one non-NEUTRAL ingredient line, plus a
    REQUESTED substitution against that line.

    Returns (instructor, member, session, line, booking, substitution).
    """
    instructor = create_instructor()
    template = create_published_template(
        skill_level=skill_level,
        base_price_cents=base_price_cents,
        default_capacity=max(seats_requested, 2),
    )
    session = create_session(
        template["id"], instructor["id"], planned_seats=max(seats_requested, 2)
    )
    line = add_ingredient_line(
        session["id"], instructor["id"],
        name="line", qty_per_seat=line_qty_per_seat,
        unit_cost_cents=line_unit_cost_cents, dietary_tag=dietary_tag,
    )
    opened = get_success_data(
        api_client.open_session(session["id"], make_instructor_headers(instructor["id"]))
    )
    member = create_member()
    booking = create_confirmed_booking(opened["id"], member["id"], seats_requested)
    substitution = request_substitution(
        booking["id"], line["id"], alternate_unit_cost_cents, member["id"]
    )
    return instructor, member, opened, line, booking, substitution


# ─── Reliability / strike accumulation ──────────────────────────────
def drive_member_to_no_shows(member_id, instructor_id, num_no_shows, start_clock="2026-07-01T00:00:00Z"):
    """
    Settle `num_no_shows` NO_SHOW strikes on a member by, for each strike:
    create a tiny GROUP session -> open -> member confirms a 1-seat booking ->
    lock -> mark-no-show -> complete (which settles the PENDING strike).

    Each settled NO_SHOW subtracts 25 from reliability. Requires a published
    template; one is created internally. Uses distinct station/start times so
    the sessions never contend for a station.
    """
    set_clock(start_clock)
    template = create_published_template(
        skill_level="BEGINNER", base_price_cents=1000, default_capacity=1,
        station_fixed_cost_cents=100,
    )
    instr_headers = make_instructor_headers(instructor_id)
    for k in range(num_no_shows):
        session = create_session(
            template["id"], instructor_id,
            station_id=f"STRIKE-{member_id[:8]}-{k}",
            start_at=f"2026-07-{2 + k:02d}T14:00:00Z",
            end_at=f"2026-07-{2 + k:02d}T15:00:00Z",
            planned_seats=1,
        )
        add_ingredient_line(session["id"], instructor_id, name="x", qty_per_seat=1, unit_cost_cents=1)
        opened = get_success_data(api_client.open_session(session["id"], instr_headers))
        booking = create_booking(opened["id"], member_id, 1)
        confirm_booking(booking["id"], opened["id"], member_id)
        get_success_data(api_client.lock_session(opened["id"], instr_headers))
        get_success_data(api_client.mark_no_show(booking["id"], instr_headers))
        get_success_data(api_client.complete_session(opened["id"], instr_headers))


def setup_blocked_member(num_no_shows=3):
    """
    Register a member and drive them to BLOCKED via `num_no_shows` settled
    NO_SHOW strikes (3 -> score 25 < 40 -> BLOCKED). Returns (instructor, member).
    """
    instructor = create_instructor()
    member = create_member()
    drive_member_to_no_shows(member["id"], instructor["id"], num_no_shows)
    return instructor, member


# ─── Waitlist scenario ──────────────────────────────────────────────
def join_waitlist(session_id, member_id, seats_requested=1):
    res = api_client.join_waitlist(
        session_id, create_waitlist_payload(member_id, seats_requested),
        make_member_headers(member_id),
    )
    return get_success_data(res)


# ─── Series scenario ────────────────────────────────────────────────
def create_published_series(template_id, instructor_id, **overrides):
    res = api_client.create_series(
        create_series_payload(template_id, instructor_id, **overrides), ADMIN
    )
    series = get_success_data(res)
    pub = api_client.publish_series(series["id"], ADMIN)
    return get_success_data(pub)
