"""Composite setup helpers for the Dance Studio Recital API.

These encapsulate the multi-step preambles that most test claims require. They use
get_success_data() (lenient) internally so setup failures surface as clear "Setup failed"
errors. Every fixture builds its preconditions from scratch — the harness restarts the
server (empty DB) before each test.

Identity threading: StudioAdmin is opaque, so all admin-driven configuration calls use the
admin headers. Instructor attendance calls use make_instructor_headers(instructor_id).
Parent ownership-gated calls use make_parent_headers(family_id).
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_instructor_headers, make_parent_headers
from . import factories as f

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Low-level single-entity builders
# ---------------------------------------------------------------------------
def create_term(**overrides):
    return get_success_data(api_client.create_term(f.create_term_payload(**overrides), ADMIN))


def create_room(**overrides):
    return get_success_data(api_client.create_room(f.create_room_payload(**overrides), ADMIN))


def create_instructor(**overrides):
    return get_success_data(api_client.create_instructor(f.create_instructor_payload(**overrides), ADMIN))


def create_family(**overrides):
    return get_success_data(api_client.create_family(f.create_family_payload(**overrides), ADMIN))


def create_student(family_id, **overrides):
    return get_success_data(
        api_client.create_student(family_id, f.create_student_payload(**overrides), ADMIN))


def create_section(term_id, room_id, instructor_id, **overrides):
    return get_success_data(api_client.create_section(
        f.create_section_payload(term_id, room_id, instructor_id, **overrides), ADMIN))


def add_session(section_id, **overrides):
    return get_success_data(
        api_client.create_session(section_id, f.create_session_payload(**overrides), ADMIN))


def grant_credit(family_id, amount_cents):
    return get_success_data(
        api_client.grant_credit(family_id, {"amount_cents": amount_cents}, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1 / Tier 2: Open term + scheduled sections
# ---------------------------------------------------------------------------
def setup_open_term_with_section(section_overrides=None, session_overrides=None,
                                 room_overrides=None, term_overrides=None,
                                 instructor_overrides=None):
    """Create term + room + instructor + one section (with one session) + open the term.

    Returns dict: term, room, instructor, section, session (section is OPEN after term opens).
    """
    term = create_term(**(term_overrides or {}))
    room = create_room(**(room_overrides or {}))
    instructor = create_instructor(**(instructor_overrides or {}))
    section = create_section(term["id"], room["id"], instructor["id"], **(section_overrides or {}))
    session = add_session(section["id"], **(session_overrides or {}))
    get_success_data(api_client.open_term(term["id"], ADMIN))
    section = get_success_data(api_client.get_section(section["id"], ADMIN))
    return {
        "term": term, "room": room, "instructor": instructor,
        "section": section, "session": session,
    }


def setup_open_term_two_sections(secA_overrides=None, secB_overrides=None):
    """Open term with TWO sections (each with a session), sharing a room and instructor.

    Sessions are placed at non-overlapping, non-conflicting times. Returns dict with
    term, room, instructor, secA, secB (both OPEN).
    """
    term = create_term()
    room = create_room(capacity=20)
    instructor = create_instructor()
    secA = create_section(term["id"], room["id"], instructor["id"], **(secA_overrides or {}))
    add_session(secA["id"], day_of_week=0, start_minute=600, end_minute=660)
    secB = create_section(term["id"], room["id"], instructor["id"], **(secB_overrides or {}))
    add_session(secB["id"], day_of_week=0, start_minute=700, end_minute=760)
    get_success_data(api_client.open_term(term["id"], ADMIN))
    secA = get_success_data(api_client.get_section(secA["id"], ADMIN))
    secB = get_success_data(api_client.get_section(secB["id"], ADMIN))
    return {"term": term, "room": room, "instructor": instructor, "secA": secA, "secB": secB}


def setup_open_term_three_sections(tuitions=(12000, 9000, 6000)):
    """Open term with THREE sections at the given monthly_tuition_cents, all sharing one
    room + instructor, sessions placed without conflict. Returns dict term/room/instructor/sections (list)."""
    term = create_term()
    room = create_room(capacity=20)
    instructor = create_instructor()
    sections = []
    disciplines = ["BALLET", "JAZZ", "TAP"]
    for i, tuition in enumerate(tuitions):
        sec = create_section(term["id"], room["id"], instructor["id"],
                             discipline=disciplines[i % len(disciplines)],
                             monthly_tuition_cents=tuition)
        add_session(sec["id"], day_of_week=2, start_minute=600 + i * 100, end_minute=660 + i * 100)
        sections.append(sec)
    get_success_data(api_client.open_term(term["id"], ADMIN))
    sections = [get_success_data(api_client.get_section(s["id"], ADMIN)) for s in sections]
    return {"term": term, "room": room, "instructor": instructor, "sections": sections}


# ---------------------------------------------------------------------------
# Tier 2 / Tier 3: Enrollment shortcuts
# ---------------------------------------------------------------------------
def create_enrollment(student_id, section_id, **overrides):
    return get_success_data(api_client.create_enrollment(
        f.create_enrollment_payload(student_id, section_id, **overrides), ADMIN))


def setup_confirmed_enrollment(section_overrides=None, student_overrides=None):
    """Open term + section + family + student + a single CONFIRMED enrollment.

    Returns dict: term, room, instructor, section, session, family, student, enrollment.
    """
    env = setup_open_term_with_section(section_overrides=section_overrides)
    family = create_family()
    student = create_student(family["id"], **(student_overrides or {}))
    enrollment = create_enrollment(student["id"], env["section"]["id"])
    env.update({"family": family, "student": student, "enrollment": enrollment})
    return env


def setup_delinquent_family(billing_month="2026-02", advance_to="2026-02-20T00:00:00Z"):
    """Build a family made DELINQUENT via a PAST_DUE invoice.

    Open term + two sections; family with a student CONFIRMED in secA; generate an invoice
    for billing_month, then advance the clock past the due day so the invoice flips PAST_DUE
    and the family flips DELINQUENT. Returns dict with term, secA, secB, family, student,
    enrollment_a (in secA), invoice.
    """
    env = setup_open_term_two_sections()
    family = create_family()
    student = create_student(family["id"])
    enr_a = create_enrollment(student["id"], env["secA"]["id"])
    invoice = get_success_data(api_client.generate_invoice(
        f.generate_invoice_payload(family["id"], env["term"]["id"], billing_month), ADMIN))
    get_success_data(api_client.set_clock(advance_to, ADMIN))
    family = get_success_data(api_client.get_family(family["id"], ADMIN))
    return {
        "term": env["term"], "secA": env["secA"], "secB": env["secB"],
        "family": family, "student": student, "enrollment_a": enr_a, "invoice": invoice,
    }


# ---------------------------------------------------------------------------
# Tier 4: Recital / seat setups
# ---------------------------------------------------------------------------
def setup_recital_on_sale(recital_overrides=None):
    """Open term (with a scheduled section so the term can open) + recital opened to ON_SALE.

    Returns dict: term, recital, recital_version (post open-sales).
    """
    env = setup_open_term_with_section()
    recital = get_success_data(api_client.create_recital(
        env["term"]["id"], f.create_recital_payload(**(recital_overrides or {})), ADMIN))
    recital = get_success_data(api_client.open_recital_sales(recital["id"], ADMIN))
    return {"term": env["term"], "recital": recital, "recital_version": recital["version"]}


def setup_recital_with_held_seat(recital_overrides=None, seat_label="A-1"):
    """ON_SALE recital + a family + one HELD seat. Returns dict: term, recital (refetched),
    family, seat, recital_version (current, post-hold)."""
    base = setup_recital_on_sale(recital_overrides=recital_overrides)
    family = create_family()
    seat = get_success_data(api_client.hold_seat(
        base["recital"]["id"],
        f.hold_seat_payload(family["id"], seat_label, base["recital_version"]),
        ADMIN))
    recital = get_success_data(api_client.get_recital(base["recital"]["id"], ADMIN))
    return {
        "term": base["term"], "recital": recital, "family": family,
        "seat": seat, "recital_version": recital["version"],
    }


# ---------------------------------------------------------------------------
# Tier 3 / Tier 4: Team / membership / trip setups
# ---------------------------------------------------------------------------
def create_team(**overrides):
    return get_success_data(api_client.create_team(f.create_team_payload(**overrides), ADMIN))


def roster_members(team, family_id, student_ids):
    """Roster a list of students onto a team, threading expected_team_version after each add.

    Returns (memberships list, final_team_version)."""
    version = team["version"]
    memberships = []
    for sid in student_ids:
        m_resp = api_client.create_membership(
            team["id"], f.create_membership_payload(sid, version), ADMIN)
        m = get_success_data(m_resp)
        memberships.append(m)
        # The membership response carries the bumped team version.
        version = m.get("team_version", None)
        if version is None:
            team_now = get_success_data(api_client.get_team(team["id"], ADMIN))
            version = team_now["version"]
    return memberships, version


def setup_locked_team_with_members(num_members, min_level="NOVICE", roster_cap=None,
                                   student_level="ELITE"):
    """Create a team, roster num_members students (one family), lock the team.

    Returns dict: family, team (LOCKED, refetched), memberships (list), students (list).
    """
    if roster_cap is None:
        roster_cap = max(num_members, 1)
    team = create_team(min_level=min_level, roster_cap=roster_cap)
    family = create_family()
    students = [create_student(family["id"], full_name=f"M{i}",
                               birth_date="2010-01-01", level=student_level)
                for i in range(num_members)]
    memberships, _ = roster_members(team, family["id"], [s["id"] for s in students])
    get_success_data(api_client.lock_team(team["id"], ADMIN))
    team = get_success_data(api_client.get_team(team["id"], ADMIN))
    return {"family": family, "team": team, "memberships": memberships, "students": students}


def setup_proposed_trip(num_participants, chaperone_ratio, chaperone_count,
                        per_member_cost_cents=50000, min_level="NOVICE"):
    """LOCKED team with num_participants ROSTERED members + a PROPOSED trip with all members GOING.

    Returns dict: family, team, trip, memberships, participants (list).
    """
    base = setup_locked_team_with_members(num_participants, min_level=min_level)
    trip = get_success_data(api_client.create_trip(
        base["team"]["id"],
        f.create_trip_payload(per_member_cost_cents=per_member_cost_cents,
                              chaperone_ratio=chaperone_ratio,
                              chaperone_count=chaperone_count),
        ADMIN))
    participants = []
    for m in base["memberships"]:
        p = get_success_data(api_client.create_participant(
            trip["id"], f.create_participant_payload(m["id"]), ADMIN))
        participants.append(p)
    trip = get_success_data(api_client.get_trip(trip["id"], ADMIN))
    return {
        "family": base["family"], "team": base["team"], "trip": trip,
        "memberships": base["memberships"], "participants": participants,
    }


# ---------------------------------------------------------------------------
# Tier 4: Costume setups
# ---------------------------------------------------------------------------
def setup_costume_draft_order(unit_price_cents=4500, rush_surcharge_cents=1500,
                              size_window_close_date="2026-05-01"):
    """CONFIRMED enrollment + a costume on its section + a DRAFT costume order.

    Returns dict: term, section, family, student, enrollment, costume, order.
    """
    env = setup_confirmed_enrollment()
    costume = get_success_data(api_client.create_costume(
        env["section"]["id"],
        f.create_costume_payload(unit_price_cents=unit_price_cents,
                                 rush_surcharge_cents=rush_surcharge_cents,
                                 size_window_close_date=size_window_close_date),
        ADMIN))
    order = get_success_data(api_client.create_costume_order(
        f.create_costume_order_payload(costume["id"], env["enrollment"]["id"]), ADMIN))
    return {
        "term": env["term"], "section": env["section"], "family": env["family"],
        "student": env["student"], "enrollment": env["enrollment"],
        "costume": costume, "order": order,
    }


# ---------------------------------------------------------------------------
# Tier 5: Invoice setups
# ---------------------------------------------------------------------------
def generate_invoice(family_id, term_id, billing_month="2026-02"):
    return get_success_data(api_client.generate_invoice(
        f.generate_invoice_payload(family_id, term_id, billing_month), ADMIN))
