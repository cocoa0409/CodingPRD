"""Student-derived computed fields, recomputed on read."""
from clock import parse_iso
from db import DATA


def get_student_or_none(student_id):
    return DATA.students.get(student_id)


def package_for_student(student):
    pkg_id = student.get("course_package_id")
    if pkg_id is None:
        return None
    return DATA.course_packages.get(pkg_id)


def minutes_remaining_provisional(student):
    pkg = package_for_student(student)
    if pkg is None:
        return None
    used = sum(
        p["scheduled_minutes"]
        for p in DATA.practice_appointments.values()
        if p["student_id"] == student["id"]
        and p["status"] in ("BOOKED", "IN_PROGRESS", "COMPLETED")
    )
    return pkg["total_minutes"] - used


def minutes_remaining_final(student):
    pkg = package_for_student(student)
    if pkg is None:
        return None
    used = sum(
        p["recorded_minutes"]
        for p in DATA.practice_appointments.values()
        if p["student_id"] == student["id"]
        and p["status"] == "COMPLETED"
        and p.get("gps_validated") is True
    )
    return pkg["total_minutes"] - used


def simulator_sessions_remaining(student):
    pkg = package_for_student(student)
    if pkg is None:
        return None
    used = sum(
        1
        for s in DATA.simulator_sessions.values()
        if s["student_id"] == student["id"]
        and s["status"] in ("BOOKED", "COMPLETED")
    )
    # PRD §3.6: after persistence "may decrement to zero or remain at zero" —
    # floored at 0, never negative.
    return max(0, pkg["included_simulator_sessions"] - used)


def exam_attempts_remaining(student):
    pkg = package_for_student(student)
    if pkg is None:
        return None
    used = sum(
        1
        for e in DATA.exam_appointments.values()
        if e["student_id"] == student["id"]
        and e["status"] in ("BOOKED", "PASSED", "FAILED", "NO_SHOW")
    )
    return pkg["included_exam_attempts"] - used


def has_passed_theory(student):
    return any(
        e for e in DATA.exam_appointments.values()
        if e["student_id"] == student["id"]
        and e["exam_type"] == "THEORY_TEST"
        and e["status"] == "PASSED"
    )


def has_passed_basic_practical(student):
    return any(
        e for e in DATA.exam_appointments.values()
        if e["student_id"] == student["id"]
        and e["exam_type"] == "BASIC_TEST"
        and e["status"] == "PASSED"
    )


def no_show_count_this_cycle(student):
    cycle_start = student.get("cycle_start_date")
    if cycle_start is None:
        return 0
    cycle_dt = parse_iso(cycle_start)
    if cycle_dt is None:
        return 0
    n = 0
    for p in DATA.practice_appointments.values():
        if p["student_id"] != student["id"]:
            continue
        if p["status"] != "NO_SHOW":
            continue
        sched = parse_iso(p["scheduled_start_at"])
        if sched is None:
            continue
        if sched >= cycle_dt:
            n += 1
    return n


def reschedule_count_this_cycle(student):
    cycle_start = student.get("cycle_start_date")
    if cycle_start is None:
        return 0
    cycle_dt = parse_iso(cycle_start)
    if cycle_dt is None:
        return 0
    n = 0
    for p in DATA.practice_appointments.values():
        if p["student_id"] != student["id"]:
            continue
        if p.get("reschedule_of_id") is None:
            continue
        created = parse_iso(p["created_at"])
        if created is None:
            continue
        if created >= cycle_dt:
            n += 1
    return n


def serialize_student(student):
    """Render a Student with all computed fields populated."""
    out = dict(student)
    out["minutes_remaining_provisional"] = minutes_remaining_provisional(student)
    out["minutes_remaining_final"] = minutes_remaining_final(student)
    out["simulator_sessions_remaining"] = simulator_sessions_remaining(student)
    out["exam_attempts_remaining"] = exam_attempts_remaining(student)
    out["has_passed_theory"] = has_passed_theory(student)
    out["has_passed_basic_practical"] = has_passed_basic_practical(student)
    out["no_show_count_this_cycle"] = no_show_count_this_cycle(student)
    out["reschedule_count_this_cycle"] = reschedule_count_this_cycle(student)
    return out
