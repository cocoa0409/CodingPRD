"""Composite setup helpers for multi-step test prerequisites.

Every helper takes the ApiClient as its first argument and builds its
preconditions from scratch (the server starts against an empty database before
each test). Setup calls use get_success_data() so setup failures surface as
clear "Setup failed" errors rather than confusing assertion failures.

Setup is performed as Administrator, whose permission set is a superset of every
other role and whose X-User-ID is opaque (never compared to an entity id), so no
ownership threading is needed for setup. Tests that assert role-specific behavior
supply their own role headers on the trigger call.
"""
from datetime import date, timedelta

from prd_bench_local_runner.testing import get_success_data
from . import factories as f
from .test_users import TEST_USERS
from .constants import LOW_THRESHOLDS

ADMIN = TEST_USERS["administrator_headers"]


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------
def consecutive_dates(count, start="2026-09-01"):
    """Return `count` consecutive ISO dates starting at `start`."""
    base = date.fromisoformat(start)
    return [(base + timedelta(days=i)).isoformat() for i in range(count)]


# ---------------------------------------------------------------------------
# Tier 1: base entity creation
# ---------------------------------------------------------------------------
def make_school(api, low_thresholds=False, **overrides):
    """Create a School. With low_thresholds=True the four escalation thresholds
    become 1/2/3/4 so a handful of UNEXCUSED records walk every tier."""
    payload = dict(LOW_THRESHOLDS) if low_thresholds else {}
    payload.update(overrides)
    return get_success_data(api.create_school(f.create_school_payload(**payload), ADMIN))


def make_staff(api, school_id, role_type="CASE_MANAGER", full_name="Test Staff", **overrides):
    return get_success_data(
        api.create_staff(
            f.create_staff_payload(school_id, full_name=full_name, role_type=role_type, **overrides),
            ADMIN,
        )
    )


def make_student(api, school_id, grade_level=9, full_name="Test Student", **overrides):
    return get_success_data(
        api.create_student(
            f.create_student_payload(school_id, full_name=full_name, grade_level=grade_level, **overrides),
            ADMIN,
        )
    )


def make_case(api, student_id):
    return get_success_data(api.create_case(f.create_case_payload(student_id), ADMIN))


def record_attendance(api, student_id, attendance_date, status):
    return get_success_data(
        api.create_attendance_record(
            student_id, f.create_attendance_record_payload(attendance_date, status), ADMIN
        )
    )


def add_unexcused_run(api, student_id, count, start="2026-09-01"):
    """Record `count` UNEXCUSED days on consecutive dates. Returns record dicts."""
    recs = []
    for d in consecutive_dates(count, start):
        recs.append(record_attendance(api, student_id, d, "UNEXCUSED"))
    return recs


def get_case(api, case_id):
    return get_success_data(api.get_case(case_id, ADMIN))


def get_student(api, student_id):
    return get_success_data(api.get_student(student_id, ADMIN))


def get_staff(api, staff_id):
    return get_success_data(api.get_staff(staff_id, ADMIN))


# ---------------------------------------------------------------------------
# Tier 2/3: composite scenarios
# ---------------------------------------------------------------------------
def make_school_student_case(api, low_thresholds=False, grade_level=9, **school_overrides):
    """School + student + a manually opened NONE-tier OPEN case.
    Returns (school, student, case)."""
    school = make_school(api, low_thresholds=low_thresholds, **school_overrides)
    student = make_student(api, school["id"], grade_level=grade_level)
    case = make_case(api, student["id"])
    return school, student, case


def make_assigned_case(api, low_thresholds=False, grade_level=9, **school_overrides):
    """School + CASE_MANAGER staff + student + OPEN case assigned to that staff.
    Returns (school, staff, student, case)."""
    school = make_school(api, low_thresholds=low_thresholds, **school_overrides)
    staff = make_staff(api, school["id"], role_type="CASE_MANAGER", full_name="Case Mgr")
    student = make_student(api, school["id"], grade_level=grade_level)
    case = make_case(api, student["id"])
    get_success_data(api.assign_case(case["id"], {"staff_id": staff["id"]}, ADMIN))
    return school, staff, student, case


def schedule_conference(api, case_id, start="2026-09-10T10:00:00Z", end="2026-09-10T11:00:00Z"):
    return get_success_data(
        api.create_conference(case_id, f.create_conference_payload(start, end), ADMIN)
    )


def hold_conference(api, case_id, conference_id, outcome="Met with family"):
    return get_success_data(
        api.transition_conference(
            case_id, conference_id, {"to_status": "HELD", "outcome": outcome}, ADMIN
        )
    )


def make_case_with_held_conference(api, low_thresholds=False, grade_level=9, **school_overrides):
    """Assigned case whose conference has been marked HELD (unlocks OPEN->MONITORING
    and contract activation). Returns (school, staff, student, case, conference)."""
    school, staff, student, case = make_assigned_case(
        api, low_thresholds=low_thresholds, grade_level=grade_level, **school_overrides
    )
    conf = schedule_conference(api, case["id"])
    hold_conference(api, case["id"], conf["id"])
    return school, staff, student, case, conf


def create_contract(api, case_id, goals, start="2026-09-01", end="2026-12-01"):
    """Read the case's current version, then create a PROPOSED contract with `goals`."""
    case = get_case(api, case_id)
    return get_success_data(
        api.create_contract(
            case_id, f.create_contract_payload(start, end, goals, case["version"]), ADMIN
        )
    )


def make_case_with_active_contract(api, goals=None):
    """Assigned case + HELD conference + ACTIVE contract.
    Returns (school, staff, student, case, conference, contract)."""
    school, staff, student, case, conf = make_case_with_held_conference(api)
    goals = goals or [f.make_goal(description="Plan goal", weight=1, target_value=1, met_value=0)]
    contract = create_contract(api, case["id"], goals)
    contract = get_success_data(
        api.transition_contract(case["id"], contract["id"], {"to_status": "ACTIVE"}, ADMIN)
    )
    return school, staff, student, case, conf, contract


def drive_case_to_court_referred(api, with_officer=True, start="2026-09-01"):
    """Low-threshold school; a manually opened case driven to COURT_REFERRED via 4
    UNEXCUSED records. Returns (school, officer_or_none, student, case)."""
    school = make_school(api, low_thresholds=True)
    officer = make_staff(api, school["id"], role_type="OFFICER", full_name="Officer") if with_officer else None
    student = make_student(api, school["id"], grade_level=9)
    case = make_case(api, student["id"])
    add_unexcused_run(api, student["id"], 4, start=start)
    return school, officer, student, case


def make_scheduled_citation(api, case_id, officer_id, courtroom_id="CR-1",
                            start="2026-10-01T09:00:00Z", end="2026-10-01T10:00:00Z"):
    from .test_users import make_court_officer_headers
    return get_success_data(
        api.create_court_citation(
            case_id,
            f.create_court_citation_payload(courtroom_id, start, end),
            make_court_officer_headers(officer_id),
        )
    )
