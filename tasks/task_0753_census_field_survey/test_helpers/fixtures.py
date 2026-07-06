"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "setup failed" errors, not confusing assertion failures. The test harness
restarts the server (empty database) before every test, so every helper builds its
preconditions from scratch using only PRD-declared endpoints.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_project_payload,
    create_area_payload,
    create_enumerator_payload,
    create_case_payload,
    create_assignment_payload,
    create_attempt_payload,
    create_response_payload,
    create_reinterview_payload,
    finalize_payload,
    create_pay_period_payload,
    create_pay_line_payload,
)
from .test_users import TEST_USERS, make_enumerator_headers

ADMIN = TEST_USERS["survey_admin_headers"]
SUPERVISOR = TEST_USERS["field_supervisor_headers"]
QC = TEST_USERS["qc_reviewer_headers"]


# ─── Building blocks ──────────────────────────────────────────────────────────

def create_project(**overrides) -> dict:
    """Create a SurveyProject (PLANNING)."""
    return get_success_data(api_client.create_project(create_project_payload(**overrides), ADMIN))


def create_open_project(**overrides) -> dict:
    """Create a project and open it to IN_FIELD."""
    proj = create_project(**overrides)
    get_success_data(api_client.open_project(proj["id"], ADMIN))
    return get_success_data(api_client.get_project(proj["id"], ADMIN))


def create_draft_area(project_id: str, budget_cents: int = 1_000_000, area_code: str = "A1") -> dict:
    """Create an AssignmentArea (DRAFT)."""
    return get_success_data(api_client.create_area(
        project_id, create_area_payload(area_code=area_code, budget_cents=budget_cents), ADMIN))


def create_open_area(project_id: str, budget_cents: int = 1_000_000, area_code: str = "A1") -> dict:
    """Create an area and open it to IN_FIELD (requires the parent project IN_FIELD)."""
    area = create_draft_area(project_id, budget_cents=budget_cents, area_code=area_code)
    get_success_data(api_client.open_area(area["id"], ADMIN))
    return get_success_data(api_client.get_area(area["id"], ADMIN))


def create_applicant_enumerator(project_id: str, full_name: str = "E1",
                                languages=("EN",), hourly_rate_cents: int = 3000) -> dict:
    """Create an Enumerator (APPLICANT)."""
    return get_success_data(api_client.create_enumerator(
        project_id,
        create_enumerator_payload(full_name=full_name, languages=list(languages),
                                  hourly_rate_cents=hourly_rate_cents),
        ADMIN))


def create_hired_enumerator(project_id: str, **kw) -> dict:
    """Create an enumerator and hire it (HIRED)."""
    en = create_applicant_enumerator(project_id, **kw)
    get_success_data(api_client.hire_enumerator(en["id"], ADMIN))
    return get_success_data(api_client.get_enumerator(en["id"], ADMIN))


def create_active_enumerator(project_id: str, **kw) -> dict:
    """Create an enumerator and drive it through HIRED to ACTIVE."""
    en = create_applicant_enumerator(project_id, **kw)
    get_success_data(api_client.hire_enumerator(en["id"], ADMIN))
    get_success_data(api_client.activate_enumerator(en["id"], ADMIN))
    return get_success_data(api_client.get_enumerator(en["id"], ADMIN))


def add_case(area_id: str, address: str = "1 A St", respondent_language: str = "EN") -> dict:
    """Add a Case to an area's roster (UNASSIGNED)."""
    return get_success_data(api_client.create_case(
        area_id, create_case_payload(address=address, respondent_language=respondent_language), ADMIN))


def assign_case(case_id: str, enumerator_id: str, expected_case_version: int) -> dict:
    """Assign / reassign a case to an enumerator (FieldSupervisor)."""
    return get_success_data(api_client.create_assignment(
        case_id, create_assignment_payload(enumerator_id, expected_case_version), SUPERVISOR))


def log_attempt(case_id: str, enumerator_id: str, **payload) -> dict:
    """Log a contact attempt acting as the entity-backed Enumerator."""
    return get_success_data(api_client.create_attempt(
        case_id, create_attempt_payload(**payload), make_enumerator_headers(enumerator_id)))


def capture_response(case_id: str, enumerator_id: str, **payload) -> dict:
    """Capture a survey response acting as the entity-backed Enumerator."""
    return get_success_data(api_client.create_response(
        case_id, create_response_payload(**payload), make_enumerator_headers(enumerator_id)))


# ─── Tier 2/3: Composite scenarios ────────────────────────────────────────────

def setup_assigned_case(budget_cents: int = 1_000_000, hourly_rate_cents: int = 3000,
                        max_attempts: int = 6, fraud_score_threshold: int = 60,
                        supported_languages=("EN",), enum_languages=("EN",)) -> dict:
    """Open project + open area + ACTIVE E1 + one case assigned to E1.

    Returns dict(project, area, enumerator, case, assignment). `case` is re-read
    after the assignment so its version reflects the bump.
    """
    proj = create_open_project(
        supported_languages=list(supported_languages),
        default_language=supported_languages[0],
        fraud_score_threshold=fraud_score_threshold,
        max_attempts=max_attempts,
    )
    area = create_open_area(proj["id"], budget_cents=budget_cents)
    en1 = create_active_enumerator(proj["id"], languages=list(enum_languages),
                                   hourly_rate_cents=hourly_rate_cents)
    case = add_case(area["id"], respondent_language=supported_languages[0])
    asg = assign_case(case["id"], en1["id"], case["version"])
    case = get_success_data(api_client.get_case(case["id"], ADMIN))
    return {"project": proj, "area": area, "enumerator": en1, "case": case, "assignment": asg}


def setup_case_with_contact_made(**kw) -> dict:
    """setup_assigned_case + one LOGGED CONTACT_MADE attempt (case IN_PROGRESS)."""
    ctx = setup_assigned_case(**kw)
    att = log_attempt(
        ctx["case"]["id"], ctx["enumerator"]["id"],
        mode="IN_PERSON", window_start="2026-03-01T10:00:00Z",
        window_end="2026-03-01T10:30:00Z", disposition="CONTACT_MADE", mileage_miles=0)
    ctx["attempt"] = att
    return ctx


def setup_captured_response(second_enumerator: bool = False, response_overrides=None, **kw) -> dict:
    """Through Response CAPTURED (default clean response, fraud_score 0), case COMPLETE.

    If second_enumerator=True, also creates an ACTIVE E2 (for reviewer scenarios),
    stored under key 'enumerator2'.
    """
    ctx = setup_case_with_contact_made(**kw)
    resp_payload = dict(mode="IN_PERSON", language_used="EN", duration_minutes=20,
                        flagged_answer_count=0, gps_variance_meters=0)
    if response_overrides:
        resp_payload.update(response_overrides)
    resp = capture_response(ctx["case"]["id"], ctx["enumerator"]["id"], **resp_payload)
    ctx["response"] = resp
    if second_enumerator:
        ctx["enumerator2"] = create_active_enumerator(ctx["project"]["id"], full_name="E2")
    return ctx


def setup_reinterview_in_review(reason: str = "RANDOM_SAMPLE", **kw) -> dict:
    """Single-case area COMPLETE (E1 captured) + reinterview by ACTIVE E2 in IN_REVIEW."""
    ctx = setup_captured_response(second_enumerator=True, **kw)
    ri = get_success_data(api_client.create_reinterview(
        ctx["response"]["id"],
        create_reinterview_payload(reviewer_enumerator_id=ctx["enumerator2"]["id"], reason=reason),
        QC))
    get_success_data(api_client.start_reinterview(ri["id"], QC))
    ctx["reinterview"] = ri
    return ctx


def finalize_reinterview(reinterview_id: str, outcome: str) -> dict:
    """Finalize a reinterview with the given outcome (QCReviewer)."""
    return get_success_data(api_client.finalize_reinterview(
        reinterview_id, finalize_payload(outcome), QC))


def setup_two_assigned_cases(budget_cents: int = 1_000_000, hourly_rate_cents: int = 3000) -> dict:
    """Open project + open area + ACTIVE E1 + two cases (A, B) both assigned to E1."""
    proj = create_open_project()
    area = create_open_area(proj["id"], budget_cents=budget_cents)
    en1 = create_active_enumerator(proj["id"], hourly_rate_cents=hourly_rate_cents)
    case_a = add_case(area["id"], address="A St")
    case_b = add_case(area["id"], address="B St")
    asg_a = assign_case(case_a["id"], en1["id"], case_a["version"])
    asg_b = assign_case(case_b["id"], en1["id"], case_b["version"])
    case_a = get_success_data(api_client.get_case(case_a["id"], ADMIN))
    case_b = get_success_data(api_client.get_case(case_b["id"], ADMIN))
    return {"project": proj, "area": area, "enumerator": en1,
            "case_a": case_a, "case_b": case_b,
            "assignment_a": asg_a, "assignment_b": asg_b}


# ─── Tier 5: Payroll ──────────────────────────────────────────────────────────

def setup_open_pay_period(overtime_threshold_cents=None) -> dict:
    """Project + one enumerator + an OPEN pay period.

    Returns dict(project, enumerator, pay_period). The pay period's overtime
    threshold is left to the server default when overtime_threshold_cents is None.
    """
    proj = create_project()
    en = create_applicant_enumerator(proj["id"])
    pp_overrides = {}
    if overtime_threshold_cents is not None:
        pp_overrides["overtime_threshold_cents"] = overtime_threshold_cents
    pp = get_success_data(api_client.create_pay_period(
        proj["id"], create_pay_period_payload(label="2026-W09", **pp_overrides), ADMIN))
    return {"project": proj, "enumerator": en, "pay_period": pp}


def add_pay_line(pay_period_id: str, enumerator_id: str, line_type: str, amount_cents: int) -> dict:
    """Add a pay line to an OPEN pay period (SurveyAdmin)."""
    return get_success_data(api_client.create_pay_line(
        pay_period_id, create_pay_line_payload(enumerator_id, line_type, amount_cents), ADMIN))
