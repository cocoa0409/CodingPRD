"""Composite setup helpers: multi-step API sequences shared by tests.

Every helper builds its preconditions from scratch against an empty database
using only PRD-declared endpoints. All helpers use get_success_data() so a
setup failure surfaces as a clear "Setup failed" assertion.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_absence_payload,
    create_assignment_payload,
    create_building_payload,
    create_change_order_payload,
    create_coverage_plan_payload,
    create_evaluation_payload,
    create_formula_payload,
    create_para_payload,
    create_plan_payload,
    create_qualification_payload,
    create_student_payload,
    create_timesheet_payload,
)
from .test_users import TEST_USERS, make_para_headers

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]
BLDG_ADMIN = TEST_USERS["building_admin_headers"]
TEACHER = TEST_USERS["teacher_headers"]
ANY = TEST_USERS["any_headers"]


def _ok(resp, label: str):
    data = get_success_data(resp)
    assert resp.status_code < 300, f"Setup failed ({label}): HTTP {resp.status_code} {resp.text}"
    return data


# ---------------------------------------------------------------------------
# Tier 1: state progression — plan
# ---------------------------------------------------------------------------

def create_plan(**overrides):
    """Create a staffing plan in DRAFT. Returns the plan dict."""
    return _ok(api_client.create_plan(create_plan_payload(**overrides), ADMIN), "create_plan")


def create_draft_plan_with_building(building_overrides=None, **plan_overrides):
    """Plan DRAFT + one building. Returns (plan, building)."""
    plan = create_plan(**plan_overrides)
    building = _ok(
        api_client.create_building(
            create_building_payload(plan["id"], **(building_overrides or {})), ADMIN
        ),
        "create_building",
    )
    return plan, building


def create_active_plan(**plan_overrides):
    """Plan DRAFT -> ACTIVE with one building. Returns (plan, building, plan_version)."""
    plan, building = create_draft_plan_with_building(**plan_overrides)
    activated = _ok(api_client.activate_plan(plan["id"], ADMIN), "activate_plan")
    return activated, building, activated["version"]


def get_plan_version(plan_id):
    return _ok(api_client.get_plan(plan_id, ANY), "get_plan")["version"]


# ---------------------------------------------------------------------------
# Tier 2: roster + students
# ---------------------------------------------------------------------------

def create_para(plan_id, building_id, **overrides):
    """Create a paraprofessional (initially ACTIVE). Returns the para dict."""
    return _ok(
        api_client.create_para(create_para_payload(plan_id, building_id, **overrides), ADMIN),
        "create_para",
    )


def add_qualification(para_id, qualification, completed_on, **overrides):
    return _ok(
        api_client.add_qualification(
            para_id, create_qualification_payload(qualification, completed_on, **overrides), ADMIN
        ),
        "add_qualification",
    )


def create_student(plan_id, building_id, **overrides):
    """Register a student (initially REGISTERED). Returns the student dict."""
    return _ok(
        api_client.create_student(create_student_payload(plan_id, building_id, **overrides), COORD),
        "create_student",
    )


def create_active_student(plan_id, building_id, **overrides):
    """Student walked REGISTERED -> ACTIVE_IEP."""
    student = create_student(plan_id, building_id, **overrides)
    return _ok(api_client.activate_iep(student["id"], COORD), "activate_iep")


# ---------------------------------------------------------------------------
# Tier 3: assignment lifecycle shortcuts
# ---------------------------------------------------------------------------

def propose_assignment(plan_id, student_id, para_id, building_id, plan_version=None, **overrides):
    """Create an assignment (lands PROPOSED / PROVISIONALLY_FUNDED)."""
    if plan_version is None:
        plan_version = get_plan_version(plan_id)
    return _ok(
        api_client.create_assignment(
            create_assignment_payload(
                plan_id, student_id, para_id, building_id, plan_version, **overrides
            ),
            COORD,
        ),
        "create_assignment",
    )


def create_verified_assignment(plan_id, student_id, para_id, building_id, plan_version=None, **overrides):
    """Create assignment then walk PROPOSED -> QUALIFICATION_VERIFIED."""
    assignment = propose_assignment(plan_id, student_id, para_id, building_id, plan_version, **overrides)
    return _ok(api_client.verify_qualifications(assignment["id"], COORD), "verify_qualifications")


def create_active_assignment(plan_id, student_id, para_id, building_id, plan_version=None, **overrides):
    """Create assignment then walk PROPOSED -> QUALIFICATION_VERIFIED -> ACTIVE."""
    assignment = create_verified_assignment(
        plan_id, student_id, para_id, building_id, plan_version, **overrides
    )
    return _ok(api_client.activate_assignment(assignment["id"], COORD), "activate_assignment")


# ---------------------------------------------------------------------------
# Tier 4: coverage / absence / backfill scenarios
# ---------------------------------------------------------------------------

def create_published_coverage_plan(plan_id, building_id, coverage_date):
    """CoveragePlan DRAFT -> PUBLISHED. Returns the published coverage plan dict."""
    cp = _ok(
        api_client.create_coverage_plan(
            create_coverage_plan_payload(plan_id, building_id, coverage_date), COORD
        ),
        "create_coverage_plan",
    )
    return _ok(api_client.publish_coverage_plan(cp["id"], COORD), "publish_coverage_plan")


def report_absence(assignment_id, absence_date, expected_coverage_plan_version,
                   reason="illness", reporter_headers=None):
    """Report an absence (Teacher by default). Returns the AbsenceReport dict."""
    return _ok(
        api_client.create_absence(
            create_absence_payload(
                assignment_id, absence_date, expected_coverage_plan_version, reason
            ),
            reporter_headers or TEACHER,
        ),
        "create_absence",
    )


def setup_absence_scenario(coverage_date="2026-05-06", absence_date="2026-05-06",
                           set_clock_iso=None, extra_paras=0, **assignment_overrides):
    """Plan ACTIVE + building + P1 + student + A1 ACTIVE (Mon-Fri 480-780) +
    published coverage plan + REPORTED absence.

    Returns dict with plan, building, p1, s1, a1, cp, absence.
    """
    if set_clock_iso is not None:
        _ok(api_client.set_clock({"to_iso8601": set_clock_iso}, ADMIN), "set_clock")
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1, full_name="Pat Para")
    extras = [
        create_para(plan_id, b1, full_name=f"Sub {i}", hire_date=f"2025-09-{i:02d}")
        for i in range(1, extra_paras + 1)
    ]
    s1 = create_active_student(
        plan_id, b1, iep_service_level="ONE_TO_ONE", iep_minutes_per_week=1500
    )
    a1 = create_active_assignment(plan_id, s1["id"], p1["id"], b1, plan_v, **assignment_overrides)
    cp = create_published_coverage_plan(plan_id, b1, coverage_date)
    absence = report_absence(a1["id"], absence_date, cp["version"])
    return {
        "plan": plan, "building": building, "p1": p1, "extras": extras,
        "s1": s1, "a1": a1, "cp": cp, "absence": absence,
    }


def setup_offered_backfill(coverage_date="2026-05-06", absence_date="2026-05-06",
                           set_clock_iso=None, substitute_overrides=None):
    """Absence scenario + selector run: one OFFERED backfill for substitute P2.

    Returns dict with the scenario plus 'p2', 'bf' (the offered backfill).
    """
    scenario = setup_absence_scenario(
        coverage_date=coverage_date, absence_date=absence_date,
        set_clock_iso=set_clock_iso, extra_paras=1,
    )
    p2 = scenario["extras"][0]
    _ok(api_client.run_backfill_offers(scenario["absence"]["id"], COORD), "backfill_offers")
    backfills = _ok(
        api_client.list_backfills(ANY, params={"absence_id": scenario["absence"]["id"]}),
        "list_backfills",
    )
    assert isinstance(backfills, list) and len(backfills) == 1, (
        f"Setup failed (expected one OFFERED backfill): {backfills}"
    )
    scenario["p2"] = p2
    scenario["bf"] = backfills[0]
    return scenario


def setup_accepted_backfill(**kwargs):
    """Offered backfill accepted by its substitute. Scenario dict plus 'bf' ACCEPTED."""
    scenario = setup_offered_backfill(**kwargs)
    accepted = _ok(
        api_client.accept_backfill(scenario["bf"]["id"], make_para_headers(scenario["p2"]["id"])),
        "accept_backfill",
    )
    scenario["bf"] = accepted
    return scenario


# ---------------------------------------------------------------------------
# Tier 5: timesheet / evaluation helpers
# ---------------------------------------------------------------------------

def log_timesheet(assignment_id, para_id, work_date, start_minute, end_minute):
    """Para logs a DRAFT timesheet against their own assignment."""
    return _ok(
        api_client.create_timesheet(
            create_timesheet_payload(assignment_id, work_date, start_minute, end_minute),
            make_para_headers(para_id),
        ),
        "create_timesheet",
    )


def submit_timesheet(timesheet_id, para_id):
    return _ok(
        api_client.submit_timesheet(timesheet_id, make_para_headers(para_id)),
        "submit_timesheet",
    )


def approve_timesheet(timesheet_id, admin_headers=None):
    return _ok(
        api_client.approve_timesheet(timesheet_id, admin_headers or BLDG_ADMIN),
        "approve_timesheet",
    )


def log_and_approve_timesheet(assignment_id, para_id, work_date, start_minute, end_minute):
    """DRAFT -> SUBMITTED -> APPROVED timesheet. Returns the approved entry."""
    entry = log_timesheet(assignment_id, para_id, work_date, start_minute, end_minute)
    submit_timesheet(entry["id"], para_id)
    return approve_timesheet(entry["id"])


def setup_plan_with_active_assignment(**assignment_overrides):
    """Plan ACTIVE + building + para + ACTIVE_IEP student + ACTIVE assignment
    (Mon-Fri 480-780 by default). Returns dict(plan, building, p1, s1, a1)."""
    plan, building, plan_v = create_active_plan()
    plan_id, b1 = plan["id"], building["id"]
    p1 = create_para(plan_id, b1)
    s1 = create_active_student(plan_id, b1)
    a1 = create_active_assignment(plan_id, s1["id"], p1["id"], b1, plan_v, **assignment_overrides)
    return {"plan": plan, "building": building, "p1": p1, "s1": s1, "a1": a1}


def create_evaluation(plan_id, para_id, author_headers=None, **overrides):
    """Teacher authors an evaluation (DRAFT). created_by_user_id := X-User-ID."""
    headers = author_headers or TEACHER
    return _ok(
        api_client.create_evaluation(create_evaluation_payload(plan_id, para_id, **overrides), headers),
        "create_evaluation",
    )


def setup_countersigned_evaluation(author_id="teacher-1", countersigner_id="admin-9"):
    """Plan ACTIVE + building + para + evaluation walked DRAFT -> SUBMITTED ->
    COUNTERSIGNED by a different user. Returns dict(plan, building, p1, ev)."""
    from .test_users import make_building_admin_headers, make_teacher_headers

    plan, building, _ = create_active_plan()
    p1 = create_para(plan["id"], building["id"])
    ev = create_evaluation(plan["id"], p1["id"], author_headers=make_teacher_headers(author_id))
    _ok(api_client.submit_evaluation(ev["id"], make_teacher_headers(author_id)), "submit_evaluation")
    ev = _ok(
        api_client.countersign_evaluation(ev["id"], make_building_admin_headers(countersigner_id)),
        "countersign_evaluation",
    )
    return {"plan": plan, "building": building, "p1": p1, "ev": ev}


# ---------------------------------------------------------------------------
# Tier 6: formulas / allocations
# ---------------------------------------------------------------------------

def create_published_formula(plan_id, **overrides):
    """AllocationFormula DRAFT -> PUBLISHED. Returns the published formula dict."""
    formula = _ok(
        api_client.create_formula(create_formula_payload(plan_id, **overrides), ADMIN),
        "create_formula",
    )
    return _ok(api_client.publish_formula(formula["id"], ADMIN), "publish_formula")


def compute_allocations(formula_id, period_label):
    """Run the provisional allocation computation. Returns the raw response's data list."""
    return _ok(
        api_client.compute_allocations(
            {"formula_id": formula_id, "period_label": period_label}, ADMIN
        ),
        "compute_allocations",
    )
