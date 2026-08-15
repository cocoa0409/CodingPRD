"""Composite setup helpers.

Every helper builds preconditions from scratch through the public API (the
harness restarts the server before each test, so each test starts empty).
Setup calls use get_success_data so failures surface as clear setup errors.

Identity threading (PRD §2.1): entity-backed roles always pass the actual
entity id into the make_*_headers builders — never the shared TEST_USERS
fallbacks — whenever the downstream call is ownership- or scope-gated.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_term_payload, create_dorm_payload, create_room_payload,
    create_parent_payload, create_guardian_payload, create_staff_payload,
    create_student_payload, create_dorm_assignment_payload,
    create_leave_request_payload, create_sign_event_payload,
    create_duty_shift_payload, create_night_check_payload,
    create_medication_order_payload, create_administration_payload,
    create_discipline_case_payload, create_break_period_payload,
    create_break_housing_request_payload, create_storage_unit_payload,
    create_storage_reservation_payload,
)
from .test_users import (
    TEST_USERS,
    make_student_headers, make_parent_headers, make_guardian_headers,
    make_dorm_parent_headers, make_nurse_headers, make_dean_headers,
    make_front_desk_headers,
)

ADMIN = TEST_USERS["admin_headers"]

_name_counter = [0]


def _uniq(tag: str) -> str:
    _name_counter[0] += 1
    return f"{tag}-{_name_counter[0]}"


# ─── Tier 1: single-resource creators ────────────────────────────────────────

def set_clock(to_iso8601: str) -> dict:
    """Advance the logical clock, running all time-based sweeps (PRD §2.4)."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def make_term(name="FALL_2026", starts_on="2026-08-24", ends_on="2026-12-18") -> dict:
    return get_success_data(api_client.create_term(
        create_term_payload(name=name, starts_on=starts_on, ends_on=ends_on), ADMIN))


def make_active_term(**kwargs) -> dict:
    """Create a term and activate it (at most one ACTIVE term, PRD §3.1)."""
    term = make_term(**kwargs)
    return get_success_data(api_client.activate_term(term["id"], ADMIN))


def make_dorm(name="Winslow House", gender_policy="ANY",
              curfew_weekday="22:30", curfew_weekend="23:30") -> dict:
    return get_success_data(api_client.create_dorm(
        create_dorm_payload(name=name, gender_policy=gender_policy,
                            curfew_weekday=curfew_weekday,
                            curfew_weekend=curfew_weekend), ADMIN))


def make_room(dorm_id, room_number="W-101", beds=2) -> dict:
    return get_success_data(api_client.create_room(
        create_room_payload(dorm_id, room_number=room_number, beds=beds), ADMIN))


def make_parent(full_name=None, email=None) -> dict:
    tag = _uniq("parent")
    return get_success_data(api_client.create_parent(
        create_parent_payload(full_name=full_name or f"Pat {tag}",
                              email=email or f"{tag}@example.com"), ADMIN))


def make_guardian(max_wards=5, full_name=None, email=None, city="Boston") -> dict:
    """Create a guardian (status PENDING, PRD §3.2)."""
    tag = _uniq("guardian")
    return get_success_data(api_client.create_guardian(
        create_guardian_payload(full_name=full_name or f"Gua {tag}",
                                email=email or f"{tag}@example.com",
                                city=city, max_wards=max_wards), ADMIN))


def make_approved_guardian(max_wards=5) -> dict:
    guardian = make_guardian(max_wards=max_wards)
    return get_success_data(api_client.approve_guardian(guardian["id"], ADMIN))


def make_staff(staff_role, dorm_id=None, full_name=None) -> dict:
    tag = _uniq("staff")
    kwargs = {"full_name": full_name or f"{staff_role} {tag}"}
    if dorm_id is not None:
        kwargs["dorm_id"] = dorm_id
    return get_success_data(api_client.create_staff(
        create_staff_payload(staff_role, **kwargs), ADMIN))


def make_dorm_parent(dorm_id=None, full_name=None) -> dict:
    return make_staff("DORM_PARENT", dorm_id=dorm_id, full_name=full_name)


def make_nurse(full_name=None) -> dict:
    return make_staff("NURSE", full_name=full_name)


def make_dean(full_name=None) -> dict:
    return make_staff("DEAN", full_name=full_name)


def make_front_desk(full_name=None) -> dict:
    return make_staff("FRONT_DESK", full_name=full_name)


def make_student(parent_id, grade=10, gender="MALE", is_international=False,
                 guardian_id=None, sleep_schedule=3, cleanliness=3,
                 noise_tolerance=3, guests_comfort=3, legal_name=None) -> dict:
    payload = create_student_payload(
        parent_id, legal_name=legal_name or _uniq("Stu"), grade=grade, gender=gender,
        is_international=is_international, sleep_schedule=sleep_schedule,
        cleanliness=cleanliness, noise_tolerance=noise_tolerance,
        guests_comfort=guests_comfort)
    if guardian_id is not None:
        payload["guardian_id"] = guardian_id
    return get_success_data(api_client.create_student(payload, ADMIN))


def make_domestic_student(grade=10, gender="MALE", **questionnaire) -> dict:
    """A domestic student with a freshly created home parent. Returns student."""
    parent = make_parent()
    return make_student(parent["id"], grade=grade, gender=gender, **questionnaire)


def make_international_student(guardian_id=None, grade=11, gender="FEMALE",
                               **questionnaire) -> dict:
    """An international student; guardian must already be APPROVED (PRD §3.2)."""
    parent = make_parent()
    if guardian_id is None:
        guardian_id = make_approved_guardian()["id"]
    return make_student(parent["id"], grade=grade, gender=gender,
                        is_international=True, guardian_id=guardian_id,
                        **questionnaire)


def get_student(student_id) -> dict:
    return get_success_data(api_client.get_student(student_id, ADMIN))


# ─── Tier 2: housing hierarchy ───────────────────────────────────────────────

def propose_assignment(student_id, room_id, term_id, roommate_assignment_id=None) -> dict:
    """Propose a DormAssignment; reads the student's current version for OCC."""
    student = get_student(student_id)
    payload = create_dorm_assignment_payload(
        student_id, room_id, term_id, student["version"])
    if roommate_assignment_id is not None:
        payload["roommate_assignment_id"] = roommate_assignment_id
    return get_success_data(api_client.create_dorm_assignment(payload, ADMIN))


def confirm_assignment(assignment_id) -> dict:
    return get_success_data(api_client.confirm_dorm_assignment(assignment_id, ADMIN))


def setup_confirmed_residency(grade=12, gender="MALE", beds=2,
                              gender_policy="ANY", with_dorm_parent=True,
                              **questionnaire) -> dict:
    """Active term + dorm + room + one student CONFIRMED into the room.

    Returns a context dict: dorm, room, term, parent, student, assignment,
    and (when with_dorm_parent) dorm_parent scoped to the dorm.
    """
    dorm = make_dorm(gender_policy=gender_policy)
    room = make_room(dorm["id"], beds=beds)
    term = make_active_term()
    parent = make_parent()
    student = make_student(parent["id"], grade=grade, gender=gender, **questionnaire)
    assignment = propose_assignment(student["id"], room["id"], term["id"])
    confirm_assignment(assignment["id"])
    ctx = {
        "dorm": dorm, "room": room, "term": term, "parent": parent,
        "student": get_student(student["id"]), "assignment": assignment,
    }
    if with_dorm_parent:
        ctx["dorm_parent"] = make_dorm_parent(dorm["id"])
    return ctx


# ─── Tier 3: leave lifecycle shortcuts ───────────────────────────────────────

def file_leave(student_id, leave_type="WEEKEND_OVERNIGHT", destination="Boston",
               departs_at="2026-09-04T17:00:00Z",
               returns_at="2026-09-06T19:00:00Z") -> dict:
    """Student files a leave request for their own record (PRD §3.4)."""
    return get_success_data(api_client.create_leave_request(
        create_leave_request_payload(
            leave_type=leave_type, destination=destination,
            departs_at=departs_at, returns_at=returns_at),
        make_student_headers(student_id)))


def parent_approve_leave(leave_id, parent_id) -> dict:
    return get_success_data(api_client.parent_decision(
        leave_id, "APPROVE", make_parent_headers(parent_id)))


def guardian_approve_leave(leave_id, guardian_id) -> dict:
    return get_success_data(api_client.parent_decision(
        leave_id, "APPROVE", make_guardian_headers(guardian_id)))


def dorm_approve_leave(leave_id, dorm_parent_id) -> dict:
    return get_success_data(api_client.dorm_decision(
        leave_id, "APPROVE", make_dorm_parent_headers(dorm_parent_id)))


def setup_leave_parent_approved(ctx=None, **leave_kwargs) -> dict:
    """Confirmed residency + a leave that the family has approved."""
    ctx = ctx or setup_confirmed_residency()
    leave = file_leave(ctx["student"]["id"], **leave_kwargs)
    parent_approve_leave(leave["id"], ctx["parent"]["id"])
    ctx["leave"] = get_success_data(
        api_client.get_leave_request(leave["id"], ADMIN))
    return ctx


def setup_leave_approved(grade=12, leave_type="WEEKEND_OVERNIGHT",
                         destination="Boston",
                         departs_at="2026-09-04T17:00:00Z",
                         returns_at="2026-09-06T19:00:00Z", **kwargs) -> dict:
    """Full two-key approval: leave in APPROVED state (PRD §3.4)."""
    ctx = setup_confirmed_residency(grade=grade, **kwargs)
    leave = file_leave(ctx["student"]["id"], leave_type=leave_type,
                       destination=destination,
                       departs_at=departs_at, returns_at=returns_at)
    parent_approve_leave(leave["id"], ctx["parent"]["id"])
    dorm_approve_leave(leave["id"], ctx["dorm_parent"]["id"])
    ctx["leave"] = get_success_data(
        api_client.get_leave_request(leave["id"], ADMIN))
    return ctx


# ─── Tier 4: duty shifts, night checks, discipline ───────────────────────────

def make_duty_shift(dorm_id, staff_id, duty_date="2026-09-07",
                    shift_slot="WEEKDAY_NIGHT") -> dict:
    """Create a DutyShift; reads the dorm's current version for OCC (PRD §2.7)."""
    dorm = get_success_data(api_client.get_dorm(dorm_id, ADMIN))
    return get_success_data(api_client.create_duty_shift(
        create_duty_shift_payload(dorm_id, staff_id, dorm["version"],
                                  duty_date=duty_date, shift_slot=shift_slot), ADMIN))


def record_night_check(shift_id, student_id, dorm_parent_id,
                       check_kind="BED_CHECK", result="PRESENT") -> dict:
    return get_success_data(api_client.create_night_check(
        shift_id,
        create_night_check_payload(student_id, check_kind=check_kind, result=result),
        make_dorm_parent_headers(dorm_parent_id)))


def report_case(student_id, reporter_staff_id, category="MINOR",
                description="Incident", points_proposed=5,
                reporter_role="Dean") -> dict:
    """Report a discipline case; reporter's X-User-ID is stamped (PRD §3.7)."""
    if reporter_role == "Dean":
        headers = make_dean_headers(reporter_staff_id)
    else:
        headers = make_dorm_parent_headers(reporter_staff_id)
    return get_success_data(api_client.create_discipline_case(
        create_discipline_case_payload(
            student_id, category=category, description=description,
            points_proposed=points_proposed),
        headers))


def sanction_minor_case(case_id, reporter_dean_id, deciding_dean_id,
                        points_assessed, sanction_type="WARNING") -> dict:
    """MINOR path: begin-review by reporter, outcome by another dean (PRD §3.7)."""
    get_success_data(api_client.begin_review(case_id, make_dean_headers(reporter_dean_id)))
    return get_success_data(api_client.record_outcome(
        case_id, {"outcome": "SANCTIONED", "sanction_type": sanction_type,
                  "points_assessed": points_assessed},
        make_dean_headers(deciding_dean_id)))


def sanction_major_case(case_id, reporter_dean_id, hearing_officer_id,
                        points_assessed, sanction_type="PROBATION",
                        hearing_at="2026-09-10T15:00:00Z") -> dict:
    """MAJOR path: review + hearing + outcome by the named officer (PRD §3.7)."""
    get_success_data(api_client.begin_review(case_id, make_dean_headers(reporter_dean_id)))
    get_success_data(api_client.schedule_hearing(
        case_id, hearing_at, hearing_officer_id, make_dean_headers(reporter_dean_id)))
    return get_success_data(api_client.record_outcome(
        case_id, {"outcome": "SANCTIONED", "sanction_type": sanction_type,
                  "points_assessed": points_assessed},
        make_dean_headers(hearing_officer_id)))


def setup_student_with_sanction(points_assessed, grade=12, category="MINOR",
                                sanction_type="WARNING") -> dict:
    """Student plus one sanctioned case at exactly `points_assessed` points.

    Returns {"student", "parent", "case", "reporter", "decider"}.
    """
    parent = make_parent()
    student = make_student(parent["id"], grade=grade)
    reporter = make_dean("Dean Reporter")
    decider = make_dean("Dean Decider")
    case = report_case(student["id"], reporter["id"], category=category,
                       points_proposed=points_assessed)
    if category == "MAJOR":
        sanction_major_case(case["id"], reporter["id"], decider["id"],
                            points_assessed, sanction_type=sanction_type)
    else:
        sanction_minor_case(case["id"], reporter["id"], decider["id"],
                            points_assessed, sanction_type=sanction_type)
    return {
        "student": get_student(student["id"]),
        "parent": parent,
        "case": get_success_data(api_client.get_discipline_case(case["id"], ADMIN)),
        "reporter": reporter,
        "decider": decider,
    }


# ─── Tier 5: health center, breaks, storage ──────────────────────────────────

def make_medication_order(student_id, nurse_id, medication_name="Ibuprofen",
                          dose_mg=200, slot="MORNING", doses_total=10,
                          refill_threshold=None, is_controlled=False,
                          prescriber_name="Dr A") -> dict:
    kwargs = dict(medication_name=medication_name, dose_mg=dose_mg, slot=slot,
                  doses_total=doses_total, is_controlled=is_controlled,
                  prescriber_name=prescriber_name)
    if refill_threshold is not None:
        kwargs["refill_threshold"] = refill_threshold
    return get_success_data(api_client.create_medication_order(
        create_medication_order_payload(student_id, **kwargs),
        make_nurse_headers(nurse_id)))


def record_administration(order_id, nurse_id, scheduled_date,
                          outcome="ADMINISTERED", witness_staff_id=None,
                          notes=None) -> dict:
    kwargs = {}
    if witness_staff_id is not None:
        kwargs["witness_staff_id"] = witness_staff_id
    if notes is not None:
        kwargs["notes"] = notes
    return get_success_data(api_client.create_administration(
        order_id, create_administration_payload(scheduled_date, outcome, **kwargs),
        make_nurse_headers(nurse_id)))


def make_break_period(name="THANKSGIVING_2026", kind="THANKSGIVING",
                      starts_on="2026-11-24", ends_on="2026-11-29",
                      housing_available=True) -> dict:
    return get_success_data(api_client.create_break_period(
        create_break_period_payload(name=name, kind=kind, starts_on=starts_on,
                                    ends_on=ends_on,
                                    housing_available=housing_available), ADMIN))


def make_storage_unit(label=None, capacity_cuft=100) -> dict:
    return get_success_data(api_client.create_storage_unit(
        create_storage_unit_payload(label=label or _uniq("UNIT"),
                                    capacity_cuft=capacity_cuft), ADMIN))


def make_storage_reservation(unit_id, break_period_id, student_id,
                             volume_cuft=1, weeks=1, items_description="Box") -> dict:
    """Student reserves storage for their own record (PRD §3.8)."""
    return get_success_data(api_client.create_storage_reservation(
        create_storage_reservation_payload(
            unit_id, break_period_id, volume_cuft=volume_cuft, weeks=weeks,
            items_description=items_description),
        make_student_headers(student_id)))


def make_break_housing_request(student_id, break_period_id,
                               reason="Cannot fly home") -> dict:
    return get_success_data(api_client.create_break_housing_request(
        create_break_housing_request_payload(break_period_id, reason=reason),
        make_student_headers(student_id)))


def setup_international_with_break_storage(num_reservations=0, volume_cuft=1,
                                           weeks=1, unit_capacity=100) -> dict:
    """International student (APPROVED guardian) + break + storage unit.

    Optionally creates `num_reservations` storage reservations for the break.
    Returns {"student", "parent", "guardian", "break_period", "unit",
    "reservations", "dean"}.
    """
    guardian = make_approved_guardian(max_wards=5)
    parent = make_parent()
    student = make_student(parent["id"], grade=10, gender="FEMALE",
                           is_international=True, guardian_id=guardian["id"])
    break_period = make_break_period()
    unit = make_storage_unit(capacity_cuft=unit_capacity)
    reservations = [
        make_storage_reservation(unit["id"], break_period["id"], student["id"],
                                 volume_cuft=volume_cuft, weeks=weeks)
        for _ in range(num_reservations)
    ]
    return {
        "student": student, "parent": parent, "guardian": guardian,
        "break_period": break_period, "unit": unit,
        "reservations": reservations, "dean": make_dean("Dean One"),
    }
