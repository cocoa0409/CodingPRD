"""Growth plan OCC/supersede, plan fulfillment and audit-driven un-fulfillment,
and the audit reversal instrument."""
import pytest

from test_helpers import (
    TEST_USERS, add_meeting, complete_registration, list_transcript,
    make_admin, make_audit_case, make_building, make_course, make_growth_plan,
    make_instructor, make_section, make_teacher,
    prepare_completable_registration, publish_section, register_teacher,
    set_clock, setup_completed_course, validate_error, validate_success,
    make_auditor_headers, make_teacher_headers,
)
from test_helpers.factories import create_growth_plan_payload


def test_growth_plan_occ_stale_employee_rejected(api):
    """PRD §2.8: "Creating a growth plan carries `expected_employee_version`,
    which must equal the target teacher's current `Employee.version`. Because
    plan creation supersedes the teacher's existing non-terminal plan for the
    same school year and bumps the teacher's `version` as part of the cascade, a
    client whose last read of the employee is out of date is working from a stale
    view of the teacher's plan state; the create is then rejected with
    `ERR_STALE_EMPLOYEE_VERSION` (HTTP 412)." PRD §3.6: "the old plan moves to
    terminal `SUPERSEDED` with its `version` bumped, and the teacher's
    `Employee.version` itself increments by one".

    Design: Corner/cross_cutting_layers/growth_plan_occ_stale_employee_rejected
    """
    set_clock()
    building = make_building(name="GP Bldg", building_code="GP1")
    teacher = make_teacher(building["id"], email="tgp@x.com")
    v0 = teacher["version"]

    p1 = validate_success(api.create_growth_plan(
        create_growth_plan_payload(teacher["id"], v0, school_year="2026-2027",
                                   focus_areas=["math"], target_credits=2.0),
        make_teacher_headers(teacher["id"])), 201)
    after_first = validate_success(api.get_employee(
        teacher["id"], TEST_USERS["coordinator_headers"]), 200)
    assert after_first["version"] == v0 + 1, "plan create bumps Employee.version"

    # Replaying the pre-create version is a stale write — even for a different
    # school year.
    res = api.create_growth_plan(
        create_growth_plan_payload(teacher["id"], v0, school_year="2027-2028",
                                   focus_areas=["science"], target_credits=1.0),
        make_teacher_headers(teacher["id"]))
    validate_error(res, "ERR_STALE_EMPLOYEE_VERSION", expected_status=412)

    # A fresh view succeeds and supersedes the same-year predecessor.
    p3 = validate_success(api.create_growth_plan(
        create_growth_plan_payload(teacher["id"], after_first["version"],
                                   school_year="2026-2027",
                                   focus_areas=["stem"], target_credits=3.0),
        make_teacher_headers(teacher["id"])), 201)
    assert p3["status"] == "DRAFT"
    p1_after = validate_success(api.get_growth_plan(
        p1["id"], TEST_USERS["coordinator_headers"]), 200)
    assert p1_after["status"] == "SUPERSEDED"


def _fulfilled_plan_scenario():
    """Plan (target 1.6, SY 2026-2027, focus math) APPROVED for the teacher, then
    an aligned 24-hour completion fulfills it; returns all entities."""
    set_clock()
    building = make_building(name="PU Bldg", building_code="PU1")
    teacher = make_teacher(building["id"], email="tpu@x.com")
    admin = make_admin(building["id"], email="apu@x.com")
    plan = make_growth_plan(teacher, school_year="2026-2027", target_credits=1.6,
                            focus_areas=("math",), approve=True, admin=admin)
    instructor = make_instructor(building["id"], email="ipu@x.com")
    course = make_course(course_code="PU-24", title="Aligned Math",
                         delivery_mode="VIRTUAL", clock_hours=24, fee_cents=0)
    section = make_section(course["id"], instructor["id"], building["id"])
    meeting = add_meeting(section["id"])
    publish_section(section["id"])
    registration = register_teacher(teacher["id"], section["id"],
                                    growth_plan_id=plan["id"],
                                    aligned_focus_area="math")
    prepare_completable_registration(registration["id"], instructor["id"],
                                     [meeting], survey="waive")
    completed = complete_registration(registration["id"])
    entries, _meta = list_transcript(teacher["id"])
    case = make_audit_case(teacher["id"], fiscal_year=2026, auditor_id="aud-1")
    return building, teacher, plan, completed, entries, case


def test_plan_unfulfill_on_audit_reversal_flow(api):
    """PRD §3.6: "when a recomputation pushes the sum to at least
    `target_credits` (the comparison is inclusive), the plan flips to
    `FULFILLED`; when an audit reversal drags the sum back below target, a
    `FULFILLED` plan falls back to `APPROVED`." PRD §3.11: "Reversal marks the
    original entry `REVERSED`, stamps its `reversed_by_entry_id` with the new
    entry's id, and bumps its `version`; it then mints a compensating
    `AUDIT_REVERSAL` entry whose `clock_hours`, `district_credit`, and
    `state_ceu` are the negation of the original's values". PRD §3.11: "The case
    itself counts the reversal: `findings_count` increments, an `OPEN` case moves
    to `FINDINGS_RAISED`".

    Design: Corner/cross_cutting_layers/plan_unfulfill_on_audit_reversal
    """
    _b, teacher, plan, _completed, entries, case = _fulfilled_plan_scenario()
    fulfilled = validate_success(api.get_growth_plan(
        plan["id"], TEST_USERS["coordinator_headers"]), 200)
    assert fulfilled["status"] == "FULFILLED", "1.6 >= 1.6 — inclusive boundary"
    assert fulfilled["aligned_credits"] == pytest.approx(1.6)

    entry = entries[0]
    reversal = validate_success(api.reverse_entry(
        case["id"], {"transcript_entry_id": entry["id"],
                     "reason": "duplicate credit"},
        make_auditor_headers("aud-1")), 200)
    assert reversal["source_type"] == "AUDIT_REVERSAL"
    assert reversal["clock_hours"] == pytest.approx(-24)
    assert reversal["district_credit"] == pytest.approx(-1.6), "negated original"

    original = validate_success(api.get_transcript_entry(
        entry["id"], TEST_USERS["coordinator_headers"]), 200)
    assert original["status"] == "REVERSED"
    assert original["reversed_by_entry_id"] == reversal["id"]

    plan_after = validate_success(api.get_growth_plan(
        plan["id"], TEST_USERS["coordinator_headers"]), 200)
    assert plan_after["status"] == "APPROVED", "FULFILLED -> APPROVED un-fulfill"

    case_after = validate_success(api.get_audit_case(
        case["id"], TEST_USERS["coordinator_headers"]), 200)
    assert case_after["findings_count"] == 1
    assert case_after["status"] == "FINDINGS_RAISED"


def test_audit_entry_mismatch_rejected(api):
    """PRD §3.11: "An auditor may reverse a transcript entry — naming the
    `transcript_entry_id` and a `reason` — while the case stands in `OPEN` or
    `FINDINGS_RAISED`, provided the entry belongs to the case's employee and
    fiscal year (else `ERR_AUDIT_ENTRY_MISMATCH`)".

    Design: Corner/validations/audit_entry_mismatch_rejected
    """
    sc = setup_completed_course(clock_hours=15, fee_cents=0,
                                course_overrides={"course_code": "AM-15"})
    # Awarded 2026-08-16 — fiscal year 2026 (PRD §2.4: month July or later).
    case = make_audit_case(sc.teacher["id"], fiscal_year=2025, auditor_id="aud-1")
    entries, _meta = list_transcript(sc.teacher["id"])
    res = api.reverse_entry(case["id"],
                            {"transcript_entry_id": entries[0]["id"],
                             "reason": "wrong year probe"},
                            make_auditor_headers("aud-1"))
    validate_error(res, "ERR_AUDIT_ENTRY_MISMATCH", expected_status=400)


def test_audit_reverse_entry_twice_rejected(api):
    """PRD §3.11: "provided the entry belongs to the case's employee and fiscal
    year (else `ERR_AUDIT_ENTRY_MISMATCH`) and is still `AWARDED` (a second
    reversal of the same entry is `ERR_ENTRY_ALREADY_REVERSED`)". PRD §3.11: "it
    then mints a compensating `AUDIT_REVERSAL` entry whose `clock_hours`,
    `district_credit`, and `state_ceu` are the negation of the original's
    values". PRD §3.11: "The employee's `lane_credit_balance` is recomputed".

    Design: Corner/errors/audit_reverse_entry_twice_rejected
    """
    sc = setup_completed_course(clock_hours=15, fee_cents=0,
                                course_overrides={"course_code": "RT-15"})
    case = make_audit_case(sc.teacher["id"], fiscal_year=2026, auditor_id="aud-1")
    entries, _meta = list_transcript(sc.teacher["id"])
    entry_id = entries[0]["id"]

    reversal = validate_success(api.reverse_entry(
        case["id"], {"transcript_entry_id": entry_id, "reason": "duplicate credit"},
        make_auditor_headers("aud-1")), 200)
    assert reversal["clock_hours"] == pytest.approx(-15)
    assert reversal["district_credit"] == pytest.approx(-1.0)

    res = api.reverse_entry(case["id"],
                            {"transcript_entry_id": entry_id, "reason": "again"},
                            make_auditor_headers("aud-1"))
    validate_error(res, "ERR_ENTRY_ALREADY_REVERSED", expected_status=400)


def test_teacher_cannot_open_audit_case(api):
    """PRD §4: POST /pd/audit-cases is authorized for Auditor only. PRD §2.1:
    "If the headers are well-formed but the role is not permitted on the
    targeted endpoint — including the entity-backed kind check described below —
    the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/teacher_cannot_open_audit_case
    """
    building = make_building(name="AU Bldg", building_code="AU1")
    teacher = make_teacher(building["id"], email="tau@x.com")
    res = api.create_audit_case(
        {"employee_id": teacher["id"], "fiscal_year": 2026},
        make_teacher_headers(teacher["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)
