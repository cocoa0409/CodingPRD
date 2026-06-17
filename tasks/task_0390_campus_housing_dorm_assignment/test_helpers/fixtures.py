"""Composite setup helpers for multi-step test prerequisites.

These encapsulate the long API-call chains that most tests need to reach an
interesting state (an ACTIVE assignment requires student -> building -> room ->
cycle -> application -> submit -> run-lottery -> open-assignment -> accept, a
9-call preamble). Each helper uses get_success_data() (lenient validator) so a
broken setup raises a clear "Setup step failed" error rather than a confusing
assertion failure downstream.

Identity threading: Student / ResidentAdvisor are entity-backed roles, so every
ownership-gated call uses make_student_headers(<student_id>) /
make_ra_headers(<student_id>) with the real Student.id. The opaque
HousingOfficer uses the shared officer headers.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_building_payload,
    create_room_payload,
    create_student_payload,
    create_cycle_payload,
    create_application_payload,
    create_roommate_group_payload,
    create_membership_payload,
    create_damage_charge_payload,
    create_break_request_payload,
)
from .test_users import make_officer_headers, make_student_headers, make_ra_headers


# ─── Primitive creators ───────────────────────────────────────────────────────

def create_student(full_name="Test Student", class_year="SENIOR",
                   gender_identity="NONBINARY", lottery_number=1):
    """Register a student (HousingOfficer). Returns the Student dict."""
    res = api_client.create_student(
        create_student_payload(
            full_name=full_name, class_year=class_year,
            gender_identity=gender_identity, lottery_number=lottery_number),
        make_officer_headers())
    return get_success_data(res)


def create_building(name="Test Hall", building_type="TRADITIONAL", **overrides):
    """Create a building (HousingOfficer). Returns the Building dict."""
    res = api_client.create_building(
        create_building_payload(name=name, building_type=building_type, **overrides),
        make_officer_headers())
    return get_success_data(res)


def create_room(building_id, room_number="101", room_type="SINGLE",
                gender_inclusivity="ALL_GENDER", **overrides):
    """Create a room under a building (HousingOfficer). Returns the Room dict."""
    res = api_client.create_room(
        building_id,
        create_room_payload(room_number=room_number, room_type=room_type,
                            gender_inclusivity=gender_inclusivity, **overrides),
        make_officer_headers())
    return get_success_data(res)


def create_cycle(term_label="FALL_2026"):
    """Create a housing cycle in APPLICATION_OPEN (HousingOfficer)."""
    res = api_client.create_cycle(create_cycle_payload(term_label=term_label),
                                  make_officer_headers())
    return get_success_data(res)


def create_draft_application(cycle_id, student_id, **overrides):
    """Create a DRAFT application owned by the given student."""
    res = api_client.create_application(
        create_application_payload(cycle_id, student_id, **overrides),
        make_student_headers(student_id))
    return get_success_data(res)


def submit_application(application_id, student_id):
    """Submit a draft application (owning student). Returns the Application dict."""
    res = api_client.submit_application(application_id, make_student_headers(student_id))
    return get_success_data(res)


def create_submitted_application(cycle_id, student_id, **overrides):
    """Create + submit an application. Returns the SUBMITTED Application dict."""
    app = create_draft_application(cycle_id, student_id, **overrides)
    return submit_application(app["id"], student_id)


# ─── Cycle phase progression ──────────────────────────────────────────────────

def run_lottery(cycle_id):
    res = api_client.run_lottery(cycle_id, make_officer_headers())
    return get_success_data(res)


def open_assignment(cycle_id):
    res = api_client.open_assignment(cycle_id, make_officer_headers())
    return get_success_data(res)


def close_cycle(cycle_id):
    res = api_client.close_cycle(cycle_id, make_officer_headers())
    return get_success_data(res)


def accept_offer(application_id, student_id):
    """Accept an OFFERED application using its current version. Returns the new
    Assignment dict (the accept endpoint returns the Application, so this fetches
    the freshly-minted assignment via the application_id filter)."""
    app = get_success_data(api_client.get_application(application_id, make_officer_headers()))
    res = api_client.accept_application(
        application_id, {"expected_application_version": app["version"]},
        make_student_headers(student_id))
    get_success_data(res)
    listed, _ = _list(api_client.list_assignments(make_officer_headers(),
                                                  params={"application_id": application_id}))
    assert listed, "Setup step failed: no assignment minted on accept"
    return listed[0]


def _list(response):
    """Return (data_list, meta) from a 2xx list response without strict envelope coupling."""
    if not (200 <= response.status_code < 300):
        body = response.json() if response.text else {}
        raise AssertionError(f"Setup list call failed: HTTP {response.status_code} {body}")
    body = response.json()
    return body["data"], body.get("meta", {})


# ─── Tier 2/3: ACTIVE assignment scenarios ───────────────────────────────────

def setup_active_assignment(student_kwargs=None, building_kwargs=None,
                            room_kwargs=None, preferred_room_type="SINGLE",
                            preferred_building_type="NO_PREFERENCE",
                            term_label="FALL_ASG"):
    """Full chain to a single ACTIVE assignment.

    student -> building -> room -> cycle -> application -> submit ->
    run-lottery -> open-assignment -> accept.

    Returns dict: {student, building, room, cycle, application, assignment}.
    """
    student_kwargs = student_kwargs or {}
    building_kwargs = building_kwargs or {}
    room_kwargs = room_kwargs or {}

    student = create_student(**student_kwargs)
    building = create_building(**building_kwargs)
    room = create_room(building["id"], **room_kwargs)
    cycle = create_cycle(term_label=term_label)
    app = create_submitted_application(
        cycle["id"], student["id"],
        preferred_building_type=preferred_building_type,
        preferred_room_type=preferred_room_type)
    run_lottery(cycle["id"])
    open_assignment(cycle["id"])
    assignment = accept_offer(app["id"], student["id"])
    # refresh application to its post-accept (ACCEPTED) state
    application = get_success_data(api_client.get_application(app["id"], make_officer_headers()))
    return {
        "student": student,
        "building": building,
        "room": room,
        "cycle": cycle,
        "application": application,
        "assignment": assignment,
    }


def setup_offered_application(student_kwargs=None, room_type="SINGLE",
                             gender_inclusivity="ALL_GENDER",
                             building_kwargs=None, term_label="FALL_OFF"):
    """Chain to an OFFERED application in an ASSIGNMENT_OPEN cycle (not yet
    accepted). Returns dict: {student, building, room, cycle, application}."""
    student_kwargs = student_kwargs or {}
    building_kwargs = building_kwargs or {}
    student = create_student(**student_kwargs)
    building = create_building(**building_kwargs)
    room = create_room(building["id"], room_type=room_type,
                       gender_inclusivity=gender_inclusivity)
    cycle = create_cycle(term_label=term_label)
    create_submitted_application(cycle["id"], student["id"],
                                 preferred_room_type=room_type)
    run_lottery(cycle["id"])
    open_assignment(cycle["id"])
    application = get_success_data(api_client.get_application(
        _only_app_of(cycle["id"], student["id"]), make_officer_headers()))
    return {"student": student, "building": building, "room": room,
            "cycle": cycle, "application": application}


def _only_app_of(cycle_id, student_id):
    listed, _ = _list(api_client.list_applications(
        make_officer_headers(), params={"cycle_id": cycle_id, "student_id": student_id}))
    assert listed, "Setup step failed: no application found"
    return listed[0]["id"]


# ─── Damage charge helpers ────────────────────────────────────────────────────

def create_damage_charge(assignment_id, category="REPAIR", assessed_cents=10000,
                         split_basis="SOLE"):
    res = api_client.create_damage_charge(
        create_damage_charge_payload(assignment_id, category=category,
                                     assessed_cents=assessed_cents,
                                     split_basis=split_basis),
        make_officer_headers())
    return get_success_data(res)


def bill_charge(charge_id):
    return get_success_data(api_client.bill_damage_charge(charge_id, make_officer_headers()))


def waive_charge(charge_id):
    return get_success_data(api_client.waive_damage_charge(charge_id, make_officer_headers()))


def pay_charge(charge_id):
    return get_success_data(api_client.pay_damage_charge(charge_id, make_officer_headers()))


def get_meal_plan_for_assignment(assignment_id):
    """Fetch the single MealPlan linked to an assignment (auto-created on accept)."""
    listed, _ = _list(api_client.list_meal_plans(
        make_officer_headers(), params={"assignment_id": assignment_id}))
    assert listed, "Setup step failed: no meal plan for assignment"
    return listed[0]


# ─── Multi-room / multi-occupant shared-room scenarios ────────────────────────

def setup_shared_room_assignments(num_occupants, room_type="TRIPLE",
                                  gender_inclusivity="ALL_GENDER",
                                  term_label="FALL_SHARE"):
    """Fill a single room with `num_occupants` ACTIVE assignments.

    All occupants prefer the same room_type so the lottery packs them tightest-fit
    into the one room. Returns dict: {building, room, cycle, students, assignments}.
    """
    building = create_building(name="Shared Hall", building_type="TRADITIONAL")
    room = create_room(building["id"], room_number="SH1", room_type=room_type,
                       gender_inclusivity=gender_inclusivity)
    cycle = create_cycle(term_label=term_label)

    students = []
    app_ids = []
    for i in range(num_occupants):
        s = create_student(full_name=f"Occupant {i}", class_year="SENIOR",
                           gender_identity="NONBINARY", lottery_number=10 + i)
        app = create_submitted_application(cycle["id"], s["id"],
                                           preferred_room_type=room_type)
        students.append(s)
        app_ids.append(app["id"])

    run_lottery(cycle["id"])
    open_assignment(cycle["id"])

    assignments = []
    for s, app_id in zip(students, app_ids):
        assignments.append(accept_offer(app_id, s["id"]))

    return {"building": building, "room": room, "cycle": cycle,
            "students": students, "assignments": assignments}


def setup_two_active_assignments(gender_inclusivity="ALL_GENDER",
                                 gender_identity="NONBINARY",
                                 term_label="FALL_TWO"):
    """Two ACTIVE single-occupant assignments in two SINGLE rooms of one building,
    cycle in ASSIGNMENT_OPEN. Both students share gender so they are compatible
    with both rooms (for swap scenarios).

    Returns dict: {building, room_a, room_b, cycle, student_a, student_b,
    assignment_a, assignment_b}.
    """
    building = create_building(name="Two Hall", building_type="TRADITIONAL")
    room_a = create_room(building["id"], room_number="RA", room_type="SINGLE",
                         gender_inclusivity=gender_inclusivity)
    room_b = create_room(building["id"], room_number="RB", room_type="SINGLE",
                         gender_inclusivity=gender_inclusivity)
    cycle = create_cycle(term_label=term_label)

    student_a = create_student(full_name="Swap A", class_year="SENIOR",
                               gender_identity=gender_identity, lottery_number=40)
    student_b = create_student(full_name="Swap B", class_year="SENIOR",
                               gender_identity=gender_identity, lottery_number=41)
    app_a = create_submitted_application(cycle["id"], student_a["id"],
                                         preferred_room_type="SINGLE")
    app_b = create_submitted_application(cycle["id"], student_b["id"],
                                         preferred_room_type="SINGLE")
    run_lottery(cycle["id"])
    open_assignment(cycle["id"])
    assignment_a = accept_offer(app_a["id"], student_a["id"])
    assignment_b = accept_offer(app_b["id"], student_b["id"])
    return {"building": building, "room_a": room_a, "room_b": room_b,
            "cycle": cycle, "student_a": student_a, "student_b": student_b,
            "assignment_a": assignment_a, "assignment_b": assignment_b}


# ─── Roommate group helpers ───────────────────────────────────────────────────

def create_roommate_group(cycle_id, owner_student_id, target_size=2):
    res = api_client.create_roommate_group(
        create_roommate_group_payload(cycle_id, owner_student_id, target_size=target_size),
        make_student_headers(owner_student_id))
    return get_success_data(res)


def invite_member(group_id, owner_student_id, invited_student_id):
    res = api_client.create_membership(
        group_id, create_membership_payload(invited_student_id),
        make_student_headers(owner_student_id))
    return get_success_data(res)


def accept_member(group_id, membership_id, invited_student_id):
    res = api_client.accept_membership(group_id, membership_id,
                                       make_student_headers(invited_student_id))
    return get_success_data(res)


def setup_full_forming_group(target_size=2, term_label="FALL_GRP"):
    """A FORMING group at target_size (owner + (target_size-1) ACCEPTED invitees).

    Returns dict: {cycle, owner, group, members (list of invited students),
    memberships (list of membership dicts)}.
    """
    cycle = create_cycle(term_label=term_label)
    owner = create_student(full_name="Group Owner", class_year="JUNIOR",
                           gender_identity="MALE", lottery_number=30)
    group = create_roommate_group(cycle["id"], owner["id"], target_size=target_size)
    members = []
    memberships = []
    for i in range(target_size - 1):
        m = create_student(full_name=f"Mate {i}", class_year="JUNIOR",
                           gender_identity="MALE", lottery_number=31 + i)
        mem = invite_member(group["id"], owner["id"], m["id"])
        accept_member(group["id"], mem["id"], m["id"])
        members.append(m)
        memberships.append(mem)
    return {"cycle": cycle, "owner": owner, "group": group,
            "members": members, "memberships": memberships}


# ─── Break housing helpers ────────────────────────────────────────────────────

def setup_break_eligible_assignment(break_housing_capacity=2,
                                    nightly_break_rate_cents=4500,
                                    term_label="FALL_BRK", lottery_number=100):
    """An ACTIVE assignment whose room belongs to a break-eligible building.

    Returns dict: {student, building, room, cycle, application, assignment}.
    """
    student = create_student(full_name="Break Student", class_year="SENIOR",
                             gender_identity="FEMALE", lottery_number=lottery_number)
    building = create_building(name="Break Hall", building_type="APARTMENT",
                               offers_break_housing=True,
                               break_housing_capacity=break_housing_capacity)
    room = create_room(building["id"], room_number="BR1", room_type="SINGLE",
                       gender_inclusivity="ALL_GENDER",
                       nightly_break_rate_cents=nightly_break_rate_cents)
    cycle = create_cycle(term_label=term_label)
    app = create_submitted_application(cycle["id"], student["id"],
                                       preferred_room_type="SINGLE")
    run_lottery(cycle["id"])
    open_assignment(cycle["id"])
    assignment = accept_offer(app["id"], student["id"])
    application = get_success_data(api_client.get_application(app["id"], make_officer_headers()))
    return {"student": student, "building": building, "room": room,
            "cycle": cycle, "application": application, "assignment": assignment}


def setup_break_eligible_double_two_occupants(break_housing_capacity=5,
                                              nightly_break_rate_cents=4500,
                                              term_label="FALL_BRK2"):
    """A break-eligible building with one DOUBLE room holding two ACTIVE
    assignments (so two residents can each request break housing on the SAME
    room — for per-room overlap scenarios).

    Returns dict: {building, room, cycle, students, assignments}.
    """
    building = create_building(name="Overlap Hall", building_type="APARTMENT",
                               offers_break_housing=True,
                               break_housing_capacity=break_housing_capacity)
    room = create_room(building["id"], room_number="OV1", room_type="DOUBLE",
                       gender_inclusivity="ALL_GENDER",
                       nightly_break_rate_cents=nightly_break_rate_cents)
    cycle = create_cycle(term_label=term_label)
    students = []
    app_ids = []
    for i in range(2):
        s = create_student(full_name=f"Overlap O{i}", class_year="SENIOR",
                           gender_identity="MALE", lottery_number=130 + i)
        app = create_submitted_application(cycle["id"], s["id"],
                                           preferred_room_type="DOUBLE")
        students.append(s)
        app_ids.append(app["id"])
    run_lottery(cycle["id"])
    open_assignment(cycle["id"])
    assignments = [accept_offer(a, s["id"]) for a, s in zip(app_ids, students)]
    return {"building": building, "room": room, "cycle": cycle,
            "students": students, "assignments": assignments}


def setup_break_eligible_two_rooms_one_occupant_each(break_housing_capacity=1,
                                                     nightly_break_rate_cents=4500,
                                                     term_label="FALL_BCAP"):
    """A break-eligible building with capacity `break_housing_capacity` and two
    SINGLE rooms, each holding one ACTIVE assignment (for per-building
    aggregate-capacity scenarios across different rooms).

    Returns dict: {building, room_a, room_b, cycle, students, assignments}.
    """
    building = create_building(name="Cap Hall", building_type="APARTMENT",
                               offers_break_housing=True,
                               break_housing_capacity=break_housing_capacity)
    room_a = create_room(building["id"], room_number="CAPA", room_type="SINGLE",
                         gender_inclusivity="ALL_GENDER",
                         nightly_break_rate_cents=nightly_break_rate_cents)
    room_b = create_room(building["id"], room_number="CAPB", room_type="SINGLE",
                         gender_inclusivity="ALL_GENDER",
                         nightly_break_rate_cents=nightly_break_rate_cents)
    cycle = create_cycle(term_label=term_label)
    students = []
    app_ids = []
    for i in range(2):
        s = create_student(full_name=f"Cap C{i}", class_year="SENIOR",
                           gender_identity="FEMALE", lottery_number=140 + i)
        app = create_submitted_application(cycle["id"], s["id"],
                                           preferred_room_type="SINGLE")
        students.append(s)
        app_ids.append(app["id"])
    run_lottery(cycle["id"])
    open_assignment(cycle["id"])
    assignments = [accept_offer(a, s["id"]) for a, s in zip(app_ids, students)]
    return {"building": building, "room_a": room_a, "room_b": room_b,
            "cycle": cycle, "students": students, "assignments": assignments}


def create_break_request(assignment_id, student_id, check_in_date, check_out_date):
    res = api_client.create_break_request(
        create_break_request_payload(assignment_id, check_in_date, check_out_date),
        make_student_headers(student_id))
    return get_success_data(res)


def approve_break_request(request_id):
    return get_success_data(api_client.approve_break_request(request_id, make_officer_headers()))


# ─── Incident helpers ─────────────────────────────────────────────────────────

def setup_room_with_incident(severity="MINOR", term_label="FALL_INC"):
    """A room carrying one OPEN incident filed by an RA.

    Returns dict: {ra, building, room, incident}.
    """
    ra = create_student(full_name="RA Filer", class_year="SENIOR",
                        gender_identity="MALE", lottery_number=250)
    building = create_building(name="Incident Hall", building_type="TRADITIONAL")
    room = create_room(building["id"], room_number="IH1", room_type="SINGLE",
                       gender_inclusivity="ALL_GENDER")
    res = api_client.create_incident_report(
        {"room_id": room["id"], "reporter_student_id": ra["id"], "severity": severity},
        make_ra_headers(ra["id"]))
    incident = get_success_data(res)
    return {"ra": ra, "building": building, "room": room, "incident": incident}
