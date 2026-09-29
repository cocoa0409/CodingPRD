"""Composite setup helpers.

Every helper builds its preconditions from scratch against an empty database,
using only endpoints the PRD publishes.  Setup calls go through the lenient
``get_success_data`` validator so a broken precondition surfaces as a clear
setup failure rather than as a confusing assertion inside a test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_application_payload,
    create_break_housing_request_payload,
    create_building_payload,
    create_duty_shift_payload,
    create_floor_payload,
    create_incident_report_payload,
    create_program_event_payload,
    create_room_change_case_payload,
    create_room_inspection_payload,
    create_room_payload,
    create_student_payload,
    unique_email,
)
from .test_users import (
    TEST_USERS,
    make_conduct_officer_headers,
    make_ra_headers,
    make_student_headers,
)

DIRECTOR = TEST_USERS["director_headers"]
BURSAR = TEST_USERS["bursar_headers"]
OFFICER_ONE = make_conduct_officer_headers("co-1")
OFFICER_TWO = make_conduct_officer_headers("co-2")

ALL_MODULES_FOR_CERTIFICATION = ["CRISIS", "TITLE_IX", "FIRE_SAFETY", "DIVERSITY"]


# --------------------------------------------------------------------------
# Tier 0: single-resource helpers
# --------------------------------------------------------------------------
def set_clock(instant: str) -> dict:
    """Move the server's logical clock and return the clock response."""
    return get_success_data(api_client.set_clock({"to_iso8601": instant}, DIRECTOR))


def create_building(**overrides) -> dict:
    return get_success_data(
        api_client.create_building(create_building_payload(**overrides), DIRECTOR)
    )


def create_floor(building_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_floor(create_floor_payload(building_id, **overrides), DIRECTOR)
    )


def create_room(floor_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_room(create_room_payload(floor_id, **overrides), DIRECTOR)
    )


def create_student(**overrides) -> dict:
    return get_success_data(
        api_client.create_student(create_student_payload(**overrides), DIRECTOR)
    )


def place_student(student_id: str, room_id: str) -> dict:
    """Place a resident into a room; returns the updated resident."""
    return get_success_data(
        api_client.room_assignment(
            student_id, {"action": "PLACE", "room_id": room_id}, DIRECTOR
        )
    )


def vacate_student(student_id: str) -> dict:
    return get_success_data(
        api_client.room_assignment(student_id, {"action": "VACATE"}, DIRECTOR)
    )


def read_room(room_id: str) -> dict:
    return get_success_data(api_client.get_room(room_id, DIRECTOR))


def read_floor(floor_id: str) -> dict:
    return get_success_data(api_client.get_floor(floor_id, DIRECTOR))


def read_building(building_id: str) -> dict:
    return get_success_data(api_client.get_building(building_id, DIRECTOR))


def read_student(student_id: str) -> dict:
    return get_success_data(api_client.get_student(student_id, DIRECTOR))


def read_ra(ra_id: str) -> dict:
    return get_success_data(api_client.get_ra(ra_id, DIRECTOR))


def read_duty_shift(shift_id: str) -> dict:
    return get_success_data(api_client.get_duty_shift(shift_id, DIRECTOR))


def read_application(application_id: str) -> dict:
    return get_success_data(api_client.get_application(application_id, DIRECTOR))


def read_incident_report(report_id: str) -> dict:
    return get_success_data(api_client.get_incident_report(report_id, DIRECTOR))


def read_conduct_case(case_id: str) -> dict:
    return get_success_data(api_client.get_conduct_case(case_id, DIRECTOR))


def read_room_inspection(inspection_id: str) -> dict:
    return get_success_data(api_client.get_room_inspection(inspection_id, DIRECTOR))


def read_damage_charge(charge_id: str) -> dict:
    return get_success_data(api_client.get_damage_charge(charge_id, DIRECTOR))


def read_room_change_case(case_id: str) -> dict:
    return get_success_data(api_client.get_room_change_case(case_id, DIRECTOR))


def read_program_event(event_id: str) -> dict:
    return get_success_data(api_client.get_program_event(event_id, DIRECTOR))


def read_break_housing_request(request_id: str) -> dict:
    return get_success_data(
        api_client.get_break_housing_request(request_id, DIRECTOR)
    )


def room_version(room_id: str) -> int:
    return read_room(room_id)["version"]


def student_version(student_id: str) -> int:
    return read_student(student_id)["version"]


# --------------------------------------------------------------------------
# Tier 1: hall / floor / room building blocks
# --------------------------------------------------------------------------
def setup_hall_with_floor(break_housing_enabled: bool = False, **floor_overrides) -> dict:
    """A hall at posture OPEN with one floor. Returns {building, floor}."""
    building = create_building(break_housing_enabled=break_housing_enabled)
    floor = create_floor(building["id"], **floor_overrides)
    return {"building": building, "floor": floor}


def setup_hall_with_rooms(
    room_specs=None, break_housing_enabled: bool = False, **floor_overrides
) -> dict:
    """A hall with one floor and the requested rooms.

    ``room_specs`` is a list of dicts of room overrides, e.g.
    ``[{"room_number": "201", "bed_capacity": 2}, ...]``.
    Returns {building, floor, rooms} where ``rooms`` is a list in creation order.
    """
    if room_specs is None:
        room_specs = [{"room_number": "201", "bed_capacity": 2}]
    base = setup_hall_with_floor(
        break_housing_enabled=break_housing_enabled, **floor_overrides
    )
    rooms = [create_room(base["floor"]["id"], **spec) for spec in room_specs]
    base["rooms"] = rooms
    return base


# --------------------------------------------------------------------------
# Tier 2: the staffing axis — application -> RA -> floor -> employment/training
# --------------------------------------------------------------------------
def create_ra(
    floor_id=None,
    full_name: str = "Ada Ray",
    email=None,
    class_year: str = "JUNIOR",
    term_code: str = None,
    interview_score: float = 88,
    activate: bool = True,
    start_training: bool = True,
    modules=None,
    certify: bool = True,
) -> dict:
    """Walk a resident all the way from an RA application to a staffed RA row.

    Returns {student, application, ra} with ``ra`` read back after the last
    action taken.  Every stage is optional so tests can stop the RA on a
    specific point of either lifecycle dimension.
    """
    student = create_student(
        full_name=full_name,
        email=email or unique_email("ra"),
        class_year=class_year,
    )
    student_headers = make_student_headers(student["id"])
    application = get_success_data(
        api_client.create_application(
            create_application_payload(
                student["id"], term_code=term_code or TEST_DEFAULTS["TERM_CODE"]
            ),
            student_headers,
        )
    )
    get_success_data(
        api_client.submit_application(application["id"], {}, student_headers)
    )
    get_success_data(
        api_client.review_application(
            application["id"], {"interview_score": interview_score}, DIRECTOR
        )
    )
    get_success_data(
        api_client.decide_application(application["id"], {"decision": "OFFER"}, DIRECTOR)
    )
    application = get_success_data(
        api_client.respond_to_application(
            application["id"], {"response": "ACCEPT"}, student_headers
        )
    )
    ra_id = application["created_ra_id"]

    if floor_id is not None:
        get_success_data(
            api_client.assign_ra_floor(ra_id, {"floor_id": floor_id}, DIRECTOR)
        )
    if activate:
        get_success_data(
            api_client.ra_employment(ra_id, {"action": "ACTIVATE"}, DIRECTOR)
        )
    if start_training:
        get_success_data(
            api_client.ra_certification(ra_id, {"action": "START_TRAINING"}, DIRECTOR)
        )
        for module_code in (
            ALL_MODULES_FOR_CERTIFICATION if modules is None else modules
        ):
            get_success_data(
                api_client.log_training_module(
                    ra_id, {"module_code": module_code}, DIRECTOR
                )
            )
        if certify:
            get_success_data(
                api_client.ra_certification(ra_id, {"action": "CERTIFY"}, DIRECTOR)
            )

    return {
        "student": student,
        "application": application,
        "ra": read_ra(ra_id),
        "ra_headers": make_ra_headers(ra_id),
    }


def setup_certified_ra_on_floor(**hall_overrides) -> dict:
    """Hall + floor + one ACTIVE, CERTIFIED RA staffing that floor."""
    base = setup_hall_with_floor(**hall_overrides)
    staff = create_ra(floor_id=base["floor"]["id"])
    base.update(staff)
    return base


def setup_certified_ra_with_rooms(room_specs=None, **hall_overrides) -> dict:
    """Hall + floor + rooms + one ACTIVE, CERTIFIED RA staffing that floor."""
    base = setup_hall_with_rooms(room_specs=room_specs, **hall_overrides)
    staff = create_ra(floor_id=base["floor"]["id"])
    base.update(staff)
    return base


# --------------------------------------------------------------------------
# Tier 3: duty rotation shortcuts
# --------------------------------------------------------------------------
def create_duty_shift(floor_id: str, start_at: str, end_at: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_duty_shift(
            create_duty_shift_payload(floor_id, start_at, end_at, **overrides), DIRECTOR
        )
    )


def assign_duty_shift(shift_id: str, ra_id: str) -> dict:
    return get_success_data(
        api_client.assign_duty_shift(shift_id, {"ra_id": ra_id}, DIRECTOR)
    )


def create_and_assign_duty_shift(
    floor_id: str, ra_id: str, start_at: str, end_at: str, **overrides
) -> dict:
    shift = create_duty_shift(floor_id, start_at, end_at, **overrides)
    return assign_duty_shift(shift["id"], ra_id)


def complete_duty_shift(shift_id: str, ra_headers: dict, start_at: str, end_at: str) -> dict:
    """Drive an ASSIGNED block through CHECK_IN and COMPLETE on the clock."""
    set_clock(start_at)
    get_success_data(
        api_client.duty_shift_outcome(shift_id, {"action": "CHECK_IN"}, ra_headers)
    )
    set_clock(end_at)
    return get_success_data(
        api_client.duty_shift_outcome(shift_id, {"action": "COMPLETE"}, ra_headers)
    )


def mark_duty_shift_missed(shift_id: str, after_end_at: str) -> dict:
    set_clock(after_end_at)
    return get_success_data(
        api_client.duty_shift_outcome(shift_id, {"action": "MARK_MISSED"}, DIRECTOR)
    )


# --------------------------------------------------------------------------
# Tier 4: incidents, conduct cases and the sanction cascade
# --------------------------------------------------------------------------
def file_and_submit_incident_report(
    ra_headers: dict, room_id: str, subject_student_id: str, **overrides
) -> dict:
    report = get_success_data(
        api_client.create_incident_report(
            create_incident_report_payload(room_id, subject_student_id, **overrides),
            ra_headers,
        )
    )
    return get_success_data(
        api_client.submit_incident_report(report["id"], {}, ra_headers)
    )


def route_incident_to_conduct(
    ra_headers: dict, room_id: str, subject_student_id: str, **overrides
) -> dict:
    """File, submit and ROUTE a report. Returns {report, conduct_case}."""
    report = file_and_submit_incident_report(
        ra_headers, room_id, subject_student_id, **overrides
    )
    report = get_success_data(
        api_client.triage_incident_report(
            report["id"], {"disposition": "ROUTE"}, DIRECTOR
        )
    )
    return {
        "report": report,
        "conduct_case": read_conduct_case(report["conduct_case_id"]),
    }


def sanction_conduct_case(case_id: str, hearing_at: str) -> dict:
    """Schedule the hearing as one officer and SANCTION as a different one."""
    get_success_data(
        api_client.schedule_hearing(case_id, {"hearing_at": hearing_at}, OFFICER_ONE)
    )
    return get_success_data(
        api_client.decide_conduct_case(case_id, {"outcome": "SANCTION"}, OFFICER_TWO)
    )


def route_and_sanction(
    ra_headers: dict,
    room_id: str,
    subject_student_id: str,
    hearing_at: str,
    **overrides,
) -> dict:
    routed = route_incident_to_conduct(
        ra_headers, room_id, subject_student_id, **overrides
    )
    case = sanction_conduct_case(routed["conduct_case"]["id"], hearing_at)
    return {"report": routed["report"], "conduct_case": case}


# --------------------------------------------------------------------------
# Tier 5: inspections and the damage ledger
# --------------------------------------------------------------------------
def schedule_inspection(ra_headers: dict, room_id: str, **overrides) -> dict:
    """Schedule an inspection, reading the room's live version first."""
    version = room_version(room_id)
    return get_success_data(
        api_client.create_room_inspection(
            create_room_inspection_payload(room_id, version, **overrides), ra_headers
        )
    )


def complete_inspection(
    inspection_id: str,
    ra_headers: dict,
    condition_score: int = 62,
    damage_lines=None,
    responsible_student_id=None,
) -> dict:
    payload = {
        "condition_score": condition_score,
        "damage_lines": damage_lines if damage_lines is not None else [],
    }
    if responsible_student_id is not None:
        payload["responsible_student_id"] = responsible_student_id
    return get_success_data(
        api_client.complete_room_inspection(inspection_id, payload, ra_headers)
    )


def setup_pending_damage_charge(
    damage_lines=None,
    financial_hardship_flag: bool = True,
    last_renovation_year: int = 2021,
    condition_score: int = 62,
    inspection_type: str = "CHECK_OUT",
) -> dict:
    """Hall + floor + room 201 + certified RA + a resident of that room, walked
    through a completed inspection that synthesizes a PENDING damage charge.

    Returns {building, floor, room, ra, ra_headers, resident, resident_headers,
    inspection, charge}.
    """
    if damage_lines is None:
        damage_lines = [
            {"component_code": "WALL", "quantity": 2},
            {"component_code": "DOOR", "quantity": 1},
        ]
    base = setup_certified_ra_with_rooms(
        room_specs=[
            {
                "room_number": "201",
                "bed_capacity": 2,
                "last_renovation_year": last_renovation_year,
            }
        ]
    )
    room = base["rooms"][0]
    resident = create_student(
        full_name="Bo Lin",
        email=unique_email("bo"),
        class_year="SOPHOMORE",
        financial_hardship_flag=financial_hardship_flag,
    )
    place_student(resident["id"], room["id"])
    inspection = schedule_inspection(
        base["ra_headers"], room["id"], inspection_type=inspection_type
    )
    inspection = complete_inspection(
        inspection["id"],
        base["ra_headers"],
        condition_score=condition_score,
        damage_lines=damage_lines,
        responsible_student_id=resident["id"],
    )
    base["room"] = room
    base["resident"] = resident
    base["resident_headers"] = make_student_headers(resident["id"])
    base["inspection"] = inspection
    base["charge"] = read_damage_charge(inspection["damage_charge_id"])
    return base


def setup_billed_damage_charge(**overrides) -> dict:
    """As above, then billed by the bursar. Adds the billed charge under 'charge'."""
    base = setup_pending_damage_charge(**overrides)
    base["charge"] = get_success_data(
        api_client.bill_damage_charge(base["charge"]["id"], {}, BURSAR)
    )
    return base


# --------------------------------------------------------------------------
# Tier 6: room-change cases
# --------------------------------------------------------------------------
def open_room_change_case(
    student_id: str, from_room_id: str, headers=None, **overrides
) -> dict:
    """Open a case, reading the resident's live version for the expectation."""
    version = student_version(student_id)
    return get_success_data(
        api_client.create_room_change_case(
            create_room_change_case_payload(
                student_id, from_room_id, version, **overrides
            ),
            headers or DIRECTOR,
        )
    )


def request_placement(case_id: str, to_room_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.placement_request(
            case_id, {"to_room_id": to_room_id}, headers or DIRECTOR
        )
    )


def setup_requested_placement(
    origin: str = "SELF_REQUEST", room_specs=None, **hall_overrides
) -> dict:
    """Two rooms, a resident in 202 and a case whose placement_status is
    REQUESTED against room 201.  Returns {building, floor, rooms, resident, case}.
    """
    if room_specs is None:
        room_specs = [
            {"room_number": "201", "bed_capacity": 2},
            {"room_number": "202", "bed_capacity": 2},
        ]
    base = setup_hall_with_rooms(room_specs=room_specs, **hall_overrides)
    target, origin_room = base["rooms"][0], base["rooms"][1]
    resident = create_student(full_name="Dee Sun", email=unique_email("dee"))
    place_student(resident["id"], origin_room["id"])
    case = open_room_change_case(resident["id"], origin_room["id"], origin=origin)
    case = request_placement(case["id"], target["id"])
    base.update(
        {
            "resident": resident,
            "resident_headers": make_student_headers(resident["id"]),
            "case": case,
            "target_room": target,
            "origin_room": origin_room,
        }
    )
    return base


def setup_completed_move() -> dict:
    """Rooms 201 (two residents) and 202 (one resident); the first resident's
    SELF_REQUEST case has been approved and completed into room 202.
    """
    base = setup_hall_with_rooms(
        room_specs=[
            {"room_number": "201", "bed_capacity": 2},
            {"room_number": "202", "bed_capacity": 2},
        ]
    )
    room_201, room_202 = base["rooms"]
    mover = create_student(full_name="Dee Sun", email=unique_email("dee"))
    stayer = create_student(full_name="Eli Cross", email=unique_email("eli"), class_year="SENIOR")
    neighbour = create_student(
        full_name="Fay Ito", email=unique_email("fay"), class_year="SOPHOMORE"
    )
    place_student(mover["id"], room_201["id"])
    place_student(stayer["id"], room_201["id"])
    place_student(neighbour["id"], room_202["id"])
    case = open_room_change_case(mover["id"], room_201["id"])
    case = request_placement(case["id"], room_202["id"])
    get_success_data(
        api_client.placement_decision(case["id"], {"decision": "APPROVE"}, DIRECTOR)
    )
    case = get_success_data(
        api_client.placement_completion(
            case["id"], {"note": "keys handed over"}, DIRECTOR
        )
    )
    base.update(
        {
            "room_201": room_201,
            "room_202": room_202,
            "mover": mover,
            "stayer": stayer,
            "neighbour": neighbour,
            "case": case,
        }
    )
    return base


# --------------------------------------------------------------------------
# Tier 7: floor programming
# --------------------------------------------------------------------------
def allocate_budget(floor_id: str, amount_cents: int, term_code: str = None) -> dict:
    return get_success_data(
        api_client.allocate_floor_budget(
            floor_id,
            {
                "amount_cents": amount_cents,
                "term_code": term_code or TEST_DEFAULTS["TERM_CODE"],
            },
            DIRECTOR,
        )
    )


def propose_program(ra_headers: dict, floor_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_program_event(
            create_program_event_payload(floor_id, **overrides), ra_headers
        )
    )


def setup_approved_program(
    budget_cents: int = 100_000, requested_amount_cents: int = 40_000, **program_overrides
) -> dict:
    """Hall + floor with an allocated budget + a certified RA + one APPROVED
    program event encumbering the ask.  Returns {building, floor, ra, ra_headers, event}.
    """
    base = setup_certified_ra_on_floor()
    allocate_budget(base["floor"]["id"], budget_cents)
    event = propose_program(
        base["ra_headers"],
        base["floor"]["id"],
        requested_amount_cents=requested_amount_cents,
        **program_overrides,
    )
    event = get_success_data(
        api_client.decide_program_event(event["id"], {"decision": "APPROVE"}, DIRECTOR)
    )
    base["event"] = event
    return base


def hold_program(event_id: str, headers: dict, attendance_count: int = 30) -> dict:
    return get_success_data(
        api_client.program_event_outcome(
            event_id, {"action": "HOLD", "attendance_count": attendance_count}, headers
        )
    )


def setup_held_program(
    budget_cents: int = 100_000,
    requested_amount_cents: int = 40_000,
    scheduled_for: str = "2026-08-03T18:00:00Z",
    held_at: str = "2026-08-03T19:00:00Z",
    attendance_count: int = 30,
    **program_overrides,
) -> dict:
    """An APPROVED program driven past its scheduled instant and HELD."""
    base = setup_approved_program(
        budget_cents=budget_cents,
        requested_amount_cents=requested_amount_cents,
        scheduled_for=scheduled_for,
        **program_overrides,
    )
    set_clock(held_at)
    base["event"] = hold_program(
        base["event"]["id"], base["ra_headers"], attendance_count=attendance_count
    )
    return base


# --------------------------------------------------------------------------
# Tier 8: break housing
# --------------------------------------------------------------------------
def request_break_housing(student_id: str, room_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_break_housing_request(
            create_break_housing_request_payload(student_id, room_id, **overrides),
            DIRECTOR,
        )
    )


def approve_break_housing(request_id: str) -> dict:
    return get_success_data(
        api_client.decide_break_housing_request(
            request_id, {"decision": "APPROVE"}, DIRECTOR
        )
    )


def setup_approved_break_stay(
    start_date: str = "2026-12-18", end_date: str = "2026-12-24", bed_capacity: int = 2
) -> dict:
    """Break-enabled hall + room + resident in that room + an APPROVED stay."""
    base = setup_hall_with_rooms(
        room_specs=[{"room_number": "201", "bed_capacity": bed_capacity}],
        break_housing_enabled=True,
    )
    room = base["rooms"][0]
    resident = create_student(
        full_name="Bo Lin", email=unique_email("bo"), class_year="SOPHOMORE"
    )
    place_student(resident["id"], room["id"])
    stay = request_break_housing(
        resident["id"], room["id"], start_date=start_date, end_date=end_date
    )
    base["room"] = room
    base["resident"] = resident
    base["stay"] = approve_break_housing(stay["id"])
    return base


# --------------------------------------------------------------------------
# Tier 9: cyclic-workflow shortcuts
# --------------------------------------------------------------------------
def setup_application_at_revision_cap() -> dict:
    """An RA application driven twice around the revision cycle, left in
    UNDER_REVIEW with revision_count at the two-round cap.

    Returns {student, student_headers, application}.
    """
    student = create_student(
        full_name="Cy Park", email=unique_email("cy"), class_year="SOPHOMORE"
    )
    headers = make_student_headers(student["id"])
    application = get_success_data(
        api_client.create_application(
            create_application_payload(student["id"], essay_ref="E-CY-0"), headers
        )
    )
    app_id = application["id"]
    get_success_data(api_client.submit_application(app_id, {}, headers))
    get_success_data(
        api_client.review_application(app_id, {"interview_score": 71}, DIRECTOR)
    )
    get_success_data(
        api_client.decide_application(
            app_id,
            {
                "decision": "REQUEST_REVISION",
                "revision_notes": "expand the crisis scenario",
            },
            DIRECTOR,
        )
    )
    get_success_data(
        api_client.submit_application(app_id, {"essay_ref": "E-CY-1"}, headers)
    )
    get_success_data(
        api_client.review_application(app_id, {"interview_score": 76}, DIRECTOR)
    )
    get_success_data(
        api_client.decide_application(
            app_id,
            {
                "decision": "REQUEST_REVISION",
                "revision_notes": "still thin on conflict handling",
            },
            DIRECTOR,
        )
    )
    get_success_data(
        api_client.submit_application(app_id, {"essay_ref": "E-CY-2"}, headers)
    )
    application = get_success_data(
        api_client.review_application(app_id, {"interview_score": 80}, DIRECTOR)
    )
    return {
        "student": student,
        "student_headers": headers,
        "application": application,
    }


def setup_incident_report_at_return_cap() -> dict:
    """A submitted incident report sent back for detail twice, so return_count
    sits at the two-round cap and the report is SUBMITTED again.

    Returns {building, floor, rooms, ra, ra_headers, subject, report}.
    """
    base = setup_certified_ra_with_rooms(
        room_specs=[{"room_number": "201", "bed_capacity": 2}]
    )
    room = base["rooms"][0]
    subject = create_student(
        full_name="Bo Lin", email=unique_email("bo"), class_year="SOPHOMORE"
    )
    report = file_and_submit_incident_report(
        base["ra_headers"],
        room["id"],
        subject["id"],
        severity="MODERATE",
        policy_code="GUEST",
        narrative="Unescorted guest found on the floor after midnight.",
    )
    for note, narrative in (
        ("who was the guest", "Unescorted guest identified as a non-resident signed in by nobody."),
        ("add the time the guest left", "Unescorted guest signed in by nobody; left the building at 01:20."),
    ):
        get_success_data(
            api_client.triage_incident_report(
                report["id"], {"disposition": "RETURN", "note": note}, DIRECTOR
            )
        )
        report = get_success_data(
            api_client.submit_incident_report(
                report["id"], {"narrative": narrative}, base["ra_headers"]
            )
        )
    base["room"] = room
    base["subject"] = subject
    base["report"] = report
    return base


def setup_conflict_case_at_mediation_cap() -> dict:
    """A ROOMMATE_CONFLICT case driven through three recorded IMPASSE sessions,
    leaving mediation_round at the three-round cap.

    Returns {building, floor, rooms, resident, roommate, case}.
    """
    base = setup_hall_with_rooms(
        room_specs=[{"room_number": "201", "bed_capacity": 2}]
    )
    room = base["rooms"][0]
    resident = create_student(
        full_name="Bo Lin", email=unique_email("bo"), class_year="SOPHOMORE"
    )
    roommate = create_student(
        full_name="Cy Park", email=unique_email("cy"), class_year="SENIOR"
    )
    place_student(resident["id"], room["id"])
    place_student(roommate["id"], room["id"])
    case = open_room_change_case(
        resident["id"],
        room["id"],
        origin="ROOMMATE_CONFLICT",
        roommate_student_id=roommate["id"],
    )
    for session_at in (
        "2026-08-04T15:00:00Z",
        "2026-08-06T15:00:00Z",
        "2026-08-08T15:00:00Z",
    ):
        get_success_data(
            api_client.mediation_action(
                case["id"],
                {"action": "SCHEDULE_SESSION", "session_at": session_at},
                DIRECTOR,
            )
        )
        case = get_success_data(
            api_client.mediation_action(
                case["id"], {"action": "RECORD_SESSION", "outcome": "IMPASSE"}, DIRECTOR
            )
        )
    base.update({"room": room, "resident": resident, "roommate": roommate, "case": case})
    return base


# --------------------------------------------------------------------------
# Tier 10: duty-rotation scenarios
# --------------------------------------------------------------------------
def setup_floor_with_shifts(shift_specs, **ra_kwargs) -> dict:
    """Hall + floor + one RA staffing it + the requested unstaffed blocks.

    ``shift_specs`` is a list of dicts carrying ``shift_type``, ``start_at`` and
    ``end_at``.  Returns the RA bundle plus ``shifts`` in creation order.
    """
    base = setup_hall_with_floor()
    staff = create_ra(floor_id=base["floor"]["id"], **ra_kwargs)
    base.update(staff)
    base["shifts"] = [
        create_duty_shift(
            base["floor"]["id"], spec["start_at"], spec["end_at"],
            shift_type=spec.get("shift_type", "WEEKEND"),
        )
        for spec in shift_specs
    ]
    return base


def setup_two_certified_ras_on_one_floor() -> dict:
    """Hall + floor + two ACTIVE, CERTIFIED RAs staffing the same floor."""
    base = setup_hall_with_floor()
    first = create_ra(floor_id=base["floor"]["id"], full_name="Ada Ray")
    second = create_ra(
        floor_id=base["floor"]["id"],
        full_name="Bo Lin",
        class_year="SENIOR",
        interview_score=79,
    )
    base["first"] = first
    base["second"] = second
    return base


def setup_duty_load_scenario() -> dict:
    """One RA holding five blocks: one COMPLETED, one MISSED and three still
    ASSIGNED, with the logical clock parked at 2026-09-15T00:00:00Z.

    Returns the RA bundle plus ``shifts`` keyed s1..s5.
    """
    specs = [
        {"shift_type": "WEEKEND", "start_at": "2026-08-08T18:00:00Z", "end_at": "2026-08-09T08:00:00Z"},
        {"shift_type": "WEEKDAY", "start_at": "2026-08-20T18:00:00Z", "end_at": "2026-08-21T08:00:00Z"},
        {"shift_type": "WEEKEND", "start_at": "2026-09-20T18:00:00Z", "end_at": "2026-09-21T08:00:00Z"},
        {"shift_type": "WEEKDAY", "start_at": "2026-09-25T18:00:00Z", "end_at": "2026-09-26T08:00:00Z"},
        {"shift_type": "WEEKEND", "start_at": "2026-10-20T18:00:00Z", "end_at": "2026-10-21T08:00:00Z"},
    ]
    base = setup_floor_with_shifts(specs, interview_score=91)
    ra_id = base["ra"]["id"]
    for shift in base["shifts"]:
        assign_duty_shift(shift["id"], ra_id)

    complete_duty_shift(
        base["shifts"][0]["id"],
        base["ra_headers"],
        "2026-08-08T18:00:00Z",
        "2026-08-09T08:00:00Z",
    )
    mark_duty_shift_missed(base["shifts"][1]["id"], "2026-08-21T09:00:00Z")
    set_clock("2026-09-15T00:00:00Z")

    base["shift_map"] = {
        f"s{index + 1}": shift for index, shift in enumerate(base["shifts"])
    }
    return base


# --------------------------------------------------------------------------
# Tier 11: the conduct sanction cascade
# --------------------------------------------------------------------------
def setup_repeat_offender_awaiting_second_decision() -> dict:
    """A resident of room 202 who already carries one MODERATE sanction, holds a
    REQUESTED room-change case targeting room 201 and an APPROVED WINTER break
    stay, and whose second, SEVERE case has its hearing already scheduled.

    Returns {building, floor, rooms, ra, ra_headers, respondent, case (room change),
    stay, first_conduct_case, second_conduct_case, second_report}.
    """
    base = setup_certified_ra_with_rooms(
        room_specs=[
            {"room_number": "201", "bed_capacity": 2},
            {"room_number": "202", "bed_capacity": 2},
        ],
        break_housing_enabled=True,
    )
    room_201, room_202 = base["rooms"]
    respondent = create_student(
        full_name="Cy Park", email=unique_email("cy"), class_year="SOPHOMORE"
    )
    place_student(respondent["id"], room_202["id"])

    room_change = open_room_change_case(respondent["id"], room_202["id"])
    room_change = request_placement(room_change["id"], room_201["id"])

    stay = request_break_housing(
        respondent["id"],
        room_202["id"],
        start_date="2026-12-18",
        end_date="2026-12-24",
        reason="internship",
    )
    stay = approve_break_housing(stay["id"])

    first = route_and_sanction(
        base["ra_headers"],
        room_202["id"],
        respondent["id"],
        "2026-08-05T10:00:00Z",
        occurred_at="2026-07-30T22:00:00Z",
        severity="MODERATE",
        policy_code="NOISE",
        narrative="Amplified music after quiet hours, three prior warnings.",
    )
    second = route_incident_to_conduct(
        base["ra_headers"],
        room_202["id"],
        respondent["id"],
        occurred_at="2026-07-31T23:30:00Z",
        severity="SEVERE",
        policy_code="ALCOHOL",
        narrative="Hard alcohol distributed to underage residents in the lounge.",
    )
    get_success_data(
        api_client.schedule_hearing(
            second["conduct_case"]["id"],
            {"hearing_at": "2026-08-06T10:00:00Z"},
            OFFICER_ONE,
        )
    )

    base.update(
        {
            "room_201": room_201,
            "room_202": room_202,
            "respondent": respondent,
            "room_change_case": room_change,
            "stay": stay,
            "first_conduct_case": first["conduct_case"],
            "second_report": second["report"],
            "second_conduct_case": second["conduct_case"],
        }
    )
    return base


def setup_routed_conduct_case() -> dict:
    """Hall + floor + room + certified RA + a resident with one routed report
    whose conduct case is still OPEN.

    Returns {building, floor, rooms, ra, ra_headers, subject, report, conduct_case}.
    """
    base = setup_certified_ra_with_rooms(
        room_specs=[{"room_number": "201", "bed_capacity": 2}]
    )
    subject = create_student(
        full_name="Bo Lin", email=unique_email("bo"), class_year="SOPHOMORE"
    )
    routed = route_incident_to_conduct(
        base["ra_headers"],
        base["rooms"][0]["id"],
        subject["id"],
        occurred_at="2026-07-31T23:00:00Z",
        severity="MODERATE",
        policy_code="SAFETY",
        narrative="Fire door wedged open on the stairwell landing overnight.",
    )
    base["subject"] = subject
    base["report"] = routed["report"]
    base["conduct_case"] = routed["conduct_case"]
    return base
