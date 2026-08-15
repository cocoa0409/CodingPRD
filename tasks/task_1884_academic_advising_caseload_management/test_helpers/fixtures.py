"""Composite setup helpers for multi-step test prerequisites.

All helpers build preconditions from scratch using only PRD-declared endpoints
(the harness restarts the server before every test, so each test starts against
an empty database). Setup calls use get_success_data() so a failure surfaces as
a clear "Setup step failed" error rather than a confusing assertion failure.
"""
import itertools

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    auto_assign_payload,
    create_advisor_payload,
    create_appointment_payload,
    create_assignment_payload,
    create_degree_plan_payload,
    create_drop_in_ticket_payload,
    create_hold_payload,
    create_intervention_payload,
    create_note_payload,
    create_referral_payload,
    create_student_payload,
    outreach_payload,
)
from .test_users import TEST_USERS

DIRECTOR = TEST_USERS["director_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]
FACULTY = TEST_USERS["faculty_headers"]

_email_counter = itertools.count(1)


def _unique_email(prefix: str) -> str:
    return f"{prefix}{next(_email_counter)}@example.edu"


# ─── Tier 1: single-entity creation ──────────────────────────────────────────

def set_logical_clock(to_iso8601: str) -> dict:
    """Advance the server-side logical clock (PRD §2.4). Returns clock echo."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, DIRECTOR)
    )


def create_advisor(
    full_name: str = "Advisor",
    major_codes=("CS",),
    max_caseload: int = 5,
    email: str = None,
) -> dict:
    payload = create_advisor_payload(
        full_name=full_name,
        email=email or _unique_email("adv"),
        major_codes=list(major_codes),
        max_caseload=max_caseload,
    )
    return get_success_data(api_client.create_advisor(payload, DIRECTOR))


def create_student(
    full_name: str = "Student",
    major_code: str = "CS",
    cohort_year: int = 2026,
    current_term_code: str = "FA26",
    gpa: float = 3.0,
    advising_required_flag=None,
    email: str = None,
) -> dict:
    overrides = {}
    if advising_required_flag is not None:
        overrides["advising_required_flag"] = advising_required_flag
    payload = create_student_payload(
        full_name=full_name,
        email=email or _unique_email("stu"),
        major_code=major_code,
        cohort_year=cohort_year,
        current_term_code=current_term_code,
        gpa=gpa,
        **overrides,
    )
    return get_success_data(api_client.create_student(payload, DIRECTOR))


def get_student(student_id: str) -> dict:
    return get_success_data(api_client.get_student(student_id, DIRECTOR))


def get_advisor(advisor_id: str) -> dict:
    return get_success_data(api_client.get_advisor(advisor_id, DIRECTOR))


# ─── Tier 2: assignments ─────────────────────────────────────────────────────

def create_manual_assignment(student_id: str, advisor_id: str) -> dict:
    """Manual assignment with a freshly-read student version (OCC guard, PRD §2.9)."""
    version = get_student(student_id)["version"]
    payload = create_assignment_payload(student_id, advisor_id, version)
    return get_success_data(api_client.create_assignment(payload, DIRECTOR))


def auto_assign_student(student_id: str, ranking_mode: str = None) -> dict:
    overrides = {}
    if ranking_mode is not None:
        overrides["ranking_mode"] = ranking_mode
    return get_success_data(
        api_client.auto_assign(auto_assign_payload(student_id, **overrides), DIRECTOR)
    )


def setup_assigned_student(gpa: float = 3.0, major_code: str = "CS", flag=None):
    """Student (ENROLLED) + ACTIVE advisor serving the major + ACTIVE manual
    assignment. Returns (student, advisor, assignment)."""
    advisor = create_advisor(major_codes=(major_code,))
    student = create_student(major_code=major_code, gpa=gpa, advising_required_flag=flag)
    assignment = create_manual_assignment(student["id"], advisor["id"])
    return get_student(student["id"]), advisor, assignment


def setup_student_with_two_advisors(gpa: float = 3.0, major_code: str = "CS", flag=None):
    """Student assigned to advisor A; advisor B exists, serves the same major,
    and is NOT assigned. Returns (student, advisor_a, advisor_b)."""
    advisor_a = create_advisor(full_name="Advisor A", major_codes=(major_code,))
    advisor_b = create_advisor(full_name="Advisor B", major_codes=(major_code,))
    student = create_student(major_code=major_code, gpa=gpa, advising_required_flag=flag)
    create_manual_assignment(student["id"], advisor_a["id"])
    return get_student(student["id"]), advisor_a, advisor_b


# ─── Tier 3: appointments ────────────────────────────────────────────────────

def book_appointment(
    student_id: str,
    advisor_id: str,
    start: str = "2026-08-01T10:00:00Z",
    end: str = "2026-08-01T10:30:00Z",
    term_code: str = "FA26",
) -> dict:
    payload = create_appointment_payload(
        student_id,
        advisor_id,
        term_code=term_code,
        scheduled_start_at=start,
        scheduled_end_at=end,
    )
    return get_success_data(api_client.create_appointment(payload, FRONT_DESK))


def setup_student_advisor_appointment(
    start: str = "2026-08-01T10:00:00Z",
    end: str = "2026-08-01T10:30:00Z",
    gpa: float = 3.0,
    flag=None,
    term_code: str = "FA26",
):
    """ENROLLED student + ACTIVE advisor + one SCHEDULED appointment.
    Returns (student, advisor, appointment)."""
    advisor = create_advisor()
    student = create_student(gpa=gpa, advising_required_flag=flag)
    appt = book_appointment(student["id"], advisor["id"], start, end, term_code)
    return student, advisor, appt


def check_in_and_complete(appointment_id: str, clock_in_window: str) -> dict:
    """Set the logical clock inside the check-in window, check in at the front
    desk, then complete as the director. Returns the COMPLETED appointment."""
    set_logical_clock(clock_in_window)
    get_success_data(api_client.check_in_appointment(appointment_id, FRONT_DESK))
    return get_success_data(api_client.complete_appointment(appointment_id, DIRECTOR))


def mark_no_show_via_sweep() -> dict:
    """Run the close-of-day sweep (clock must already be past start+10min)."""
    return get_success_data(api_client.daily_close(DIRECTOR))


# ─── Tier 4: referrals, interventions, holds, plans, notes ───────────────────

def create_referral(
    student_id: str,
    severity: str = "HIGH",
    source: str = "FACULTY",
    reason: str = "concern",
) -> dict:
    payload = create_referral_payload(
        student_id, source=source, severity=severity, reason=reason
    )
    return get_success_data(api_client.create_referral(payload, FACULTY))


def create_intervention(
    student_id: str,
    intervention_type: str = "ACADEMIC_COACHING",
    referral_id: str = None,
) -> dict:
    overrides = {}
    if referral_id is not None:
        overrides["referral_id"] = referral_id
    payload = create_intervention_payload(
        student_id, intervention_type=intervention_type, **overrides
    )
    return get_success_data(api_client.create_intervention(payload, DIRECTOR))


def log_outreach(referral_id: str, outcome: str, headers=None) -> dict:
    return get_success_data(
        api_client.outreach_referral(
            referral_id, outreach_payload(outcome), headers or DIRECTOR
        )
    )


def place_hold(
    student_id: str, hold_type: str = "ADVISING", requires_approved_plan=None
) -> dict:
    overrides = {}
    if requires_approved_plan is not None:
        overrides["requires_approved_plan"] = requires_approved_plan
    return get_success_data(
        api_client.create_hold(
            student_id, create_hold_payload(hold_type=hold_type, **overrides), DIRECTOR
        )
    )


def create_draft_plan(
    student_id: str,
    required_credits: int = 10,
    terms=None,
    catalog_year: int = 2024,
) -> dict:
    # PRD §3.8 names `terms` a required input: only override the factory's
    # default term list when the caller supplies one — passing terms=None here
    # would put a JSON null into a required field.
    overrides = {"catalog_year": catalog_year, "required_credits": required_credits}
    if terms is not None:
        overrides["terms"] = terms
    payload = create_degree_plan_payload(**overrides)
    return get_success_data(api_client.create_degree_plan(student_id, payload, DIRECTOR))


def create_submitted_plan(student_id: str, required_credits: int = 10, terms=None) -> dict:
    plan = create_draft_plan(student_id, required_credits, terms)
    return get_success_data(
        api_client.submit_degree_plan(student_id, plan["id"], DIRECTOR)
    )


def create_approved_plan(student_id: str, required_credits: int = 10, terms=None) -> dict:
    plan = create_submitted_plan(student_id, required_credits, terms)
    return get_success_data(
        api_client.approve_degree_plan(student_id, plan["id"], DIRECTOR)
    )


def author_note(student_id: str, visibility: str, body: str, headers) -> dict:
    return get_success_data(
        api_client.create_note(
            student_id,
            create_note_payload(visibility=visibility, body=body),
            headers,
        )
    )


def join_queue(student_id: str, reason: str = "walk-in") -> dict:
    return get_success_data(
        api_client.create_drop_in_ticket(
            create_drop_in_ticket_payload(student_id, reason=reason), FRONT_DESK
        )
    )


# ─── Tier 5: composite scenario builders ─────────────────────────────────────

def setup_divergent_caseload_pool():
    """Two ACTIVE advisors serving CS with divergent load profiles, plus two
    unassigned LOW-risk candidate students.

    Advisor A: two LOW-risk advisees -> assigned_active_count 2, weighted_load 2.
    Advisor B: one HIGH-risk advisee (gpa 1.9 base 40 + HIGH referral 20 +
               ACTIVE hold 8 + OPEN intervention 10 = 78) -> count 1, load 3.
    Candidates s4 and s5 are LOW-risk (gpa 3.5) so auto-assignment choice is
    observable per ranking mode. Returns dict of the created rows.
    """
    advisor_a = create_advisor(full_name="Advisor A", email="a@x.edu")
    advisor_b = create_advisor(full_name="Advisor B", email="b@x.edu")

    s1 = create_student(full_name="S1", email="s1@x.edu")
    create_manual_assignment(s1["id"], advisor_a["id"])
    s2 = create_student(full_name="S2", email="s2@x.edu")
    create_manual_assignment(s2["id"], advisor_a["id"])

    s3 = create_student(full_name="S3", email="s3@x.edu", gpa=1.9)
    create_referral(s3["id"], severity="HIGH", reason="failing midterm")
    place_hold(s3["id"], hold_type="ADVISING")
    create_intervention(s3["id"], intervention_type="ACADEMIC_COACHING")
    create_manual_assignment(s3["id"], advisor_b["id"])

    s4 = create_student(full_name="S4", email="s4@x.edu", gpa=3.5)
    s5 = create_student(full_name="S5", email="s5@x.edu", gpa=3.5)
    return {
        "advisor_a": advisor_a,
        "advisor_b": advisor_b,
        "s3": s3,
        "s4": s4,
        "s5": s5,
    }


def setup_retention_cohort_2025():
    """Four cohort-2025 students exercising both retention variants (PRD §3.9):
    r1 terms [FA25, SP26] ENROLLED; r2 terms [FA25] ON_LEAVE; r3 terms [FA25]
    INACTIVE; r4 terms [SP26] ENROLLED (entered in SP26)."""
    r1 = create_student(
        full_name="R1", email="r1@x.edu", cohort_year=2025, current_term_code="FA25"
    )
    get_success_data(
        api_client.update_student(r1["id"], {"current_term_code": "SP26"}, DIRECTOR)
    )
    r2 = create_student(
        full_name="R2", email="r2@x.edu", cohort_year=2025, current_term_code="FA25"
    )
    get_success_data(
        api_client.update_student(r2["id"], {"care_status": "ON_LEAVE"}, DIRECTOR)
    )
    r3 = create_student(
        full_name="R3", email="r3@x.edu", cohort_year=2025, current_term_code="FA25"
    )
    get_success_data(
        api_client.update_student(r3["id"], {"care_status": "INACTIVE"}, DIRECTOR)
    )
    r4 = create_student(
        full_name="R4", email="r4@x.edu", cohort_year=2025, current_term_code="SP26"
    )
    return {"r1": r1, "r2": r2, "r3": r3, "r4": r4}


def setup_student_at_score_98():
    """gpa 1.9 student (base 40) + one OPEN HIGH referral (+20) + two swept
    NO_SHOW appointments (+20) + one OPEN intervention (+10) + one ACTIVE hold
    (+8) -> at_risk_score 98, tier HIGH. Returns dict of created rows."""
    student = create_student(full_name="C1", email="c1@x.edu", gpa=1.9)
    advisor = create_advisor(full_name="Advisor C", email="c@x.edu")
    referral = create_referral(student["id"], severity="HIGH", reason="stopped attending")
    appt1 = book_appointment(
        student["id"], advisor["id"], "2026-08-01T10:00:00Z", "2026-08-01T10:30:00Z"
    )
    appt2 = book_appointment(
        student["id"], advisor["id"], "2026-08-01T11:00:00Z", "2026-08-01T11:30:00Z"
    )
    set_logical_clock("2026-08-01T10:11:00Z")
    mark_no_show_via_sweep()
    set_logical_clock("2026-08-01T11:11:00Z")
    mark_no_show_via_sweep()
    intervention = create_intervention(student["id"], intervention_type="TUTORING_REFERRAL")
    hold = place_hold(student["id"], hold_type="FINANCIAL")
    return {
        "student": student,
        "advisor": advisor,
        "referral": referral,
        "appointments": (appt1, appt2),
        "intervention": intervention,
        "hold": hold,
    }


def setup_escalation_candidate():
    """Student gpa 1.5 (base 40) with one OPEN HIGH referral (+20) -> score 60,
    tier MEDIUM, clearance CLEARED, requirement NOT_REQUIRED; escalation adds an
    OPEN intervention (+10) landing exactly on the HIGH threshold of 70."""
    student = create_student(full_name="T1", email="t1@x.edu", gpa=1.5)
    referral = create_referral(student["id"], severity="HIGH", reason="three absences")
    return student, referral


def list_interventions_for(headers, **params) -> list:
    data, _meta = validate_paginated(api_client.list_interventions(headers, params=params))
    return data
