"""Composite setup helpers.

Multi-step setup sequences so tests focus on assertions. All helpers build
their preconditions from scratch using only PRD-declared endpoints, and use
get_success_data() internally so setup failures surface as clear errors.

Identity threading: HRBusinessPartner / TalentManager / Manager / Employee are
entity-backed roles, so every helper that creates an acting employee returns
(or accepts) headers built with that employee's real id.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_employee_payload, create_critical_role_payload,
    create_successor_payload, create_development_plan_payload,
    create_posting_payload, create_calibration_session_payload,
    create_calibration_entry_payload, create_hipo_cycle_payload,
    create_retention_assessment_payload, create_diversity_snapshot_payload,
)
from .test_users import (
    TEST_USERS, make_hrbp_headers, make_talent_manager_headers,
    make_manager_headers, make_employee_headers,
)

ADMIN = TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Tier 1: people
# ---------------------------------------------------------------------------

def setup_employee(**overrides):
    """Create one employee. Returns the employee dict."""
    return get_success_data(api_client.create_employee(create_employee_payload(**overrides), ADMIN))


def setup_hrbp(**overrides):
    """Create the acting HR business partner employee. Returns (employee, headers)."""
    overrides.setdefault("department", "HR")
    overrides.setdefault("job_level", 7)
    overrides.setdefault("performance_rating", "STRONG")
    emp = setup_employee(**overrides)
    return emp, make_hrbp_headers(emp["id"])


def setup_talent_manager(**overrides):
    """Create the acting talent-management facilitator. Returns (employee, headers)."""
    overrides.setdefault("department", "HR")
    overrides.setdefault("job_level", 7)
    overrides.setdefault("performance_rating", "STRONG")
    emp = setup_employee(**overrides)
    return emp, make_talent_manager_headers(emp["id"])


def setup_manager(**overrides):
    """Create a people manager. Returns (employee, headers)."""
    overrides.setdefault("job_level", 7)
    overrides.setdefault("performance_rating", "STRONG")
    emp = setup_employee(**overrides)
    return emp, make_manager_headers(emp["id"])


def setup_report(manager_id, **overrides):
    """Create an employee reporting to the given manager. Returns the employee."""
    overrides["current_manager_id"] = manager_id
    return setup_employee(**overrides)


# ---------------------------------------------------------------------------
# Tier 1: logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Advance the logical clock (HRAdmin-only test-driving capability)."""
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN))


# ---------------------------------------------------------------------------
# Tier 1/2: critical roles and slates
# ---------------------------------------------------------------------------

def get_role_version(role_id, headers) -> int:
    """Read the role's current OCC version."""
    return get_success_data(api_client.get_critical_role(role_id, headers))["version"]


def setup_role(hrbp_headers, **overrides):
    """Create a PROPOSED critical role. Returns the role dict."""
    return get_success_data(
        api_client.create_critical_role(create_critical_role_payload(**overrides), hrbp_headers)
    )


def setup_active_role(hrbp_headers, incumbent_id, **overrides):
    """Create a role and activate it with the given incumbent. Returns ACTIVE role."""
    role = setup_role(hrbp_headers, **overrides)
    return get_success_data(
        api_client.activate_critical_role(
            role["id"], {"incumbent_employee_id": incumbent_id}, hrbp_headers,
        )
    )


def add_successor_entry(role_id, employee_id, hrbp_headers,
                        readiness_rating="READY_1_2", slate_position=None,
                        supersede_entry_id=None):
    """Add a DRAFT successor entry, threading the role's current OCC version.
    Returns the created entry."""
    payload = create_successor_payload(
        employee_id,
        expected_critical_role_version=get_role_version(role_id, hrbp_headers),
        readiness_rating=readiness_rating,
    )
    if slate_position is not None:
        payload["slate_position"] = slate_position
    if supersede_entry_id is not None:
        payload["supersede_entry_id"] = supersede_entry_id
    return get_success_data(api_client.create_successor(role_id, payload, hrbp_headers))


def activate_entry(entry_id, hrbp_headers):
    """Drive a successor entry DRAFT -> ACTIVE. Returns the updated entry."""
    return get_success_data(
        api_client.patch_successor(entry_id, {"status": "ACTIVE"}, hrbp_headers)
    )


def add_active_successor(role_id, employee_id, hrbp_headers,
                         readiness_rating="READY_NOW", slate_position=None):
    """Add an entry and activate it. Returns the ACTIVE entry."""
    entry = add_successor_entry(
        role_id, employee_id, hrbp_headers,
        readiness_rating=readiness_rating, slate_position=slate_position,
    )
    return activate_entry(entry["id"], hrbp_headers)


def create_and_activate_plan(entry_id, hrbp_headers,
                             target_readiness="READY_NOW", completion_pct=0):
    """Create the entry's development plan and activate it at the given
    completion percentage. Returns the ACTIVE plan."""
    plan = get_success_data(api_client.create_development_plan(
        entry_id, create_development_plan_payload(target_readiness=target_readiness),
        hrbp_headers,
    ))
    return get_success_data(api_client.patch_development_plan(
        plan["id"], {"status": "ACTIVE", "completion_pct": completion_pct}, hrbp_headers,
    ))


def setup_active_role_with_entry(method="WEIGHTED", tier="TIER_2", department="ENG",
                                 successor_rating="STRONG", readiness="READY_NOW",
                                 slate_position=1, plan_pct=None,
                                 plan_target="READY_NOW", role_title=None,
                                 criticality_tier=None, **employee_overrides):
    """ACTIVE role + one ACTIVE successor entry (optionally with an ACTIVE plan).
    Returns dict(role, entry, plan, hrbp, hrbp_headers, incumbent, successor)."""
    hrbp, hrbp_headers = setup_hrbp()
    incumbent = setup_employee(department=department, job_level=8,
                               performance_rating="STRONG", hire_date="2019-03-01")
    successor = setup_employee(department=department, performance_rating=successor_rating,
                               **employee_overrides)
    role_kwargs = {"department": department,
                   "criticality_tier": criticality_tier or tier,
                   "assessment_method": method}
    if role_title is not None:
        role_kwargs["role_title"] = role_title
    role = setup_active_role(hrbp_headers, incumbent["id"], **role_kwargs)
    entry = add_active_successor(role["id"], successor["id"], hrbp_headers,
                                 readiness_rating=readiness, slate_position=slate_position)
    plan = None
    if plan_pct is not None:
        plan = create_and_activate_plan(entry["id"], hrbp_headers,
                                        target_readiness=plan_target,
                                        completion_pct=plan_pct)
        entry = get_success_data(api_client.get_successor(entry["id"], hrbp_headers))
    return {
        "role": role, "entry": entry, "plan": plan,
        "hrbp": hrbp, "hrbp_headers": hrbp_headers,
        "incumbent": incumbent, "successor": successor,
    }


# ---------------------------------------------------------------------------
# Tier 2/3: vacancies, postings, applications
# ---------------------------------------------------------------------------

def terminate_and_get_vacancy(role_id, incumbent_id, headers):
    """Terminate the role's incumbent and return the auto-created OPEN vacancy."""
    get_success_data(api_client.terminate_employee(incumbent_id, ADMIN))
    vacancies = get_success_data(
        api_client.list_vacancies(headers, params={"critical_role_id": role_id})
    )
    assert len(vacancies) == 1, (
        f"Expected exactly one vacancy for role {role_id}, got {len(vacancies)}"
    )
    return vacancies[0]


def setup_vacancy_scenario(department="ENG", tier="TIER_2", method="WEIGHTED",
                           with_ready_successor=False, successor_readiness="READY_NOW"):
    """ACTIVE role -> incumbent terminated -> OPEN vacancy.
    Optionally keeps one ACTIVE successor on the slate.
    Returns dict(role, vacancy, hrbp, hrbp_headers, incumbent, successor, entry)."""
    hrbp, hrbp_headers = setup_hrbp()
    incumbent = setup_employee(department=department, job_level=8,
                               performance_rating="STRONG", hire_date="2019-03-01")
    successor = None
    entry = None
    role = setup_active_role(hrbp_headers, incumbent["id"], department=department,
                             criticality_tier=tier, assessment_method=method)
    if with_ready_successor:
        successor = setup_employee(department=department, performance_rating="STRONG",
                                   hire_date="2022-07-01")
        entry = add_active_successor(role["id"], successor["id"], hrbp_headers,
                                     readiness_rating=successor_readiness,
                                     slate_position=1)
    vacancy = terminate_and_get_vacancy(role["id"], incumbent["id"], hrbp_headers)
    return {
        "role": role, "vacancy": vacancy,
        "hrbp": hrbp, "hrbp_headers": hrbp_headers,
        "incumbent": incumbent, "successor": successor, "entry": entry,
    }


def setup_open_posting(vacancy_id, hrbp_headers, **overrides):
    """Create a posting under the vacancy and publish it. Returns the OPEN posting."""
    posting = get_success_data(api_client.create_posting(
        vacancy_id, create_posting_payload(**overrides), hrbp_headers,
    ))
    return get_success_data(api_client.publish_posting(posting["id"], hrbp_headers))


def setup_application(posting_id, applicant):
    """Apply to the posting as the given applicant. Returns the application."""
    return get_success_data(
        api_client.create_application(posting_id, make_employee_headers(applicant["id"]))
    )


def consent_application(application_id, manager_id):
    """Reporting manager grants consent. Returns the updated application."""
    return get_success_data(
        api_client.consent_application(application_id, make_manager_headers(manager_id))
    )


def advance_application(application_id, target_state, hrbp_headers):
    """HRBP advances the application to the named target state."""
    return get_success_data(
        api_client.advance_application(application_id, {"target_state": target_state}, hrbp_headers)
    )


def setup_consented_application(posting_id, applicant, manager_id):
    """Application moved to CONSENT_GRANTED via manager consent."""
    application = setup_application(posting_id, applicant)
    return consent_application(application["id"], manager_id)


def setup_interviewing_application(posting_id, applicant, manager_id, hrbp_headers):
    """Application advanced to INTERVIEWING."""
    application = setup_consented_application(posting_id, applicant, manager_id)
    return advance_application(application["id"], "INTERVIEWING", hrbp_headers)


def setup_posting_scenario(department="ENG", min_tenure_months=12, min_job_level=None):
    """OPEN vacancy + OPEN posting. Returns dict(vacancy, posting, role, hrbp, hrbp_headers)."""
    ctx = setup_vacancy_scenario(department=department)
    posting_kwargs = {"min_tenure_months": min_tenure_months}
    if min_job_level is not None:
        posting_kwargs["min_job_level"] = min_job_level
    posting = setup_open_posting(ctx["vacancy"]["id"], ctx["hrbp_headers"], **posting_kwargs)
    ctx["posting"] = posting
    return ctx


# ---------------------------------------------------------------------------
# Tier 2/3: calibration
# ---------------------------------------------------------------------------

def setup_session(tm_headers, **overrides):
    """Create a SCHEDULED calibration session. Returns the session."""
    return get_success_data(
        api_client.create_calibration_session(
            create_calibration_session_payload(**overrides), tm_headers,
        )
    )


def setup_in_progress_session(tm_headers, **overrides):
    """Create and start a calibration session. Returns the IN_PROGRESS session."""
    session = setup_session(tm_headers, **overrides)
    return get_success_data(api_client.start_calibration_session(session["id"], tm_headers))


def propose_entry(session_id, manager_id, employee_id, proposed_rating="SOLID"):
    """Manager proposes a rating for their report. Returns the PROPOSED entry."""
    return get_success_data(api_client.create_calibration_entry(
        session_id,
        create_calibration_entry_payload(employee_id, proposed_rating=proposed_rating),
        make_manager_headers(manager_id),
    ))


def ratify_entry(entry_id, tm_headers, final_rating):
    """TalentManager ratifies an entry. Returns the RATIFIED entry."""
    return get_success_data(
        api_client.ratify_calibration_entry(entry_id, {"final_rating": final_rating}, tm_headers)
    )


def apply_rating_via_calibration(tm_headers, manager_id, employee_id, final_rating,
                                 session_name, scheduled_start="2026-06-08T09:00:00Z",
                                 scheduled_end="2026-06-08T12:00:00Z",
                                 department_scope="ENG"):
    """Full calibration loop that writes `final_rating` onto the employee:
    session -> start -> propose -> ratify -> finalize. Returns the session."""
    session = setup_in_progress_session(
        tm_headers, name=session_name, department_scope=department_scope,
        scheduled_start=scheduled_start, scheduled_end=scheduled_end,
    )
    entry = propose_entry(session["id"], manager_id, employee_id,
                          proposed_rating=final_rating)
    ratify_entry(entry["id"], tm_headers, final_rating)
    return get_success_data(api_client.finalize_calibration_session(session["id"], tm_headers))


# ---------------------------------------------------------------------------
# Tier 2/3: HiPo program
# ---------------------------------------------------------------------------

def setup_hipo_cycle(capacity=5, **overrides):
    """Create an OPEN HiPo program cycle. Returns the cycle."""
    return get_success_data(
        api_client.create_hipo_cycle(create_hipo_cycle_payload(capacity=capacity, **overrides), ADMIN)
    )


def nominate(cycle_id, manager_id, employee_id):
    """Manager nominates a direct report. Returns the NOMINATED nomination."""
    return get_success_data(api_client.create_nomination(
        cycle_id, {"employee_id": employee_id}, make_manager_headers(manager_id),
    ))


def endorse_nomination(nomination_id, hrbp_headers):
    """HRBP endorses a nomination. Returns the ENDORSED nomination."""
    return get_success_data(api_client.endorse_nomination(nomination_id, hrbp_headers))


def enroll_nomination(nomination_id, tm_headers):
    """TalentManager enrolls an endorsed nomination. Returns the ACTIVE nomination."""
    return get_success_data(api_client.enroll_nomination(nomination_id, tm_headers))


def setup_enrolled_nomination(capacity=5, **employee_overrides):
    """Cycle + nominee enrolled to ACTIVE membership.
    Returns dict(cycle, nomination, member, manager, manager_headers,
    hrbp, hrbp_headers, tm, tm_headers)."""
    hrbp, hrbp_headers = setup_hrbp()
    tm, tm_headers = setup_talent_manager()
    manager, manager_headers = setup_manager()
    member = setup_report(manager["id"], performance_rating="STRONG",
                          **employee_overrides)
    cycle = setup_hipo_cycle(capacity=capacity)
    nomination = nominate(cycle["id"], manager["id"], member["id"])
    endorse_nomination(nomination["id"], hrbp_headers)
    nomination = enroll_nomination(nomination["id"], tm_headers)
    return {
        "cycle": cycle, "nomination": nomination, "member": member,
        "manager": manager, "manager_headers": manager_headers,
        "hrbp": hrbp, "hrbp_headers": hrbp_headers,
        "tm": tm, "tm_headers": tm_headers,
    }


# ---------------------------------------------------------------------------
# Tier 3: retention assessments
# ---------------------------------------------------------------------------

def setup_retention_assessment(employee_id, hrbp_headers, method="POINT_IN_TIME"):
    """Create a manual retention assessment. Returns the OPEN assessment."""
    return get_success_data(api_client.create_retention_assessment(
        employee_id, create_retention_assessment_payload(assessment_method=method),
        hrbp_headers,
    ))


def plan_action(assessment_id, hrbp_headers,
                action_type="STAY_INTERVIEW", action_deadline="2026-06-01T00:00:00Z"):
    """Commit a retention action. Returns the ACTION_PLANNED assessment."""
    return get_success_data(api_client.plan_action_retention_assessment(
        assessment_id,
        {"action_type": action_type, "action_deadline": action_deadline},
        hrbp_headers,
    ))


# ---------------------------------------------------------------------------
# Tier 3: diversity snapshots
# ---------------------------------------------------------------------------

def capture_department_snapshot(department):
    """Capture a DEPARTMENT-scope diversity snapshot. Returns the snapshot."""
    return get_success_data(api_client.create_diversity_snapshot(
        create_diversity_snapshot_payload(scope_type="DEPARTMENT", scope_ref=department),
        ADMIN,
    ))


def capture_cycle_snapshot(cycle_id):
    """Capture a HIPO_CYCLE-scope diversity snapshot. Returns the snapshot."""
    return get_success_data(api_client.create_diversity_snapshot(
        create_diversity_snapshot_payload(scope_type="HIPO_CYCLE", scope_ref=cycle_id),
        ADMIN,
    ))
