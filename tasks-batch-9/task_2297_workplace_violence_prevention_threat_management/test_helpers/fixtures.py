"""Composite setup builders.

The harness restarts the server and empties the database before every test, so
each builder drives the API from an empty database up to the state its name
describes and returns a context dictionary holding the rows it created together
with role headers already bound to the right employee identifiers.

Layering, from the outside in:

* ``setup_clock`` / ``setup_worksite`` / ``setup_work_area`` / ``setup_employee``
  -- single writes.
* ``setup_worksite_with_area`` / ``setup_programme`` -- the reference-data tree.
* ``setup_draft_plan`` ... ``setup_monitoring_case`` -- lifecycle shortcuts, each
  built on the one above it.
* ``setup_qualified_escort``, ``setup_training_cohort``,
  ``setup_five_pair_training_cohort``, ``setup_drilled_plan`` -- accumulation
  builders that push a counter or a percentage to a chosen value.
* ``setup_monitoring_case_with_escort``, ``setup_amended_log_case`` -- terminal
  shortcuts for revocation, closure and amendment work.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from .api_client import ApiClient
from .constants import CLOCK_INITIAL
from . import factories as f
from .test_users import (
    PROGRAM_ADMIN_HEADERS,
    make_employee_headers,
    make_hr_partner_headers,
    make_safety_officer_headers,
    make_security_coordinator_headers,
    make_site_manager_headers,
    make_threat_team_lead_headers,
    make_threat_team_member_headers,
)

Context = Dict[str, Any]


# --------------------------------------------------------------------------
# Tier 1: single writes
# --------------------------------------------------------------------------


def setup_clock(api: ApiClient, current_utc: str = CLOCK_INITIAL) -> str:
    """Pin the logical clock and return the value it now reads."""
    data = get_success_data(api.set_clock(f.build_clock(current_utc), PROGRAM_ADMIN_HEADERS))
    return data["current_utc"]


def setup_worksite(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api.create_worksite(f.build_worksite(**overrides), PROGRAM_ADMIN_HEADERS))


def setup_work_area(api: ApiClient, worksite_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_work_area(f.build_work_area(worksite_id, **overrides), PROGRAM_ADMIN_HEADERS)
    )


def setup_employee(
    api: ApiClient, worksite_id: str, work_area_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    return get_success_data(
        api.create_employee(
            f.build_employee(worksite_id, work_area_id, **overrides), PROGRAM_ADMIN_HEADERS
        )
    )


# --------------------------------------------------------------------------
# Tier 2: the reference-data tree
# --------------------------------------------------------------------------


def setup_worksite_with_area(api: ApiClient, clock: str = CLOCK_INITIAL) -> Context:
    """Clock pinned, one worksite, one public night-shift cash-handling area."""
    ctx: Context = {"clock": setup_clock(api, clock)}
    ctx["worksite"] = setup_worksite(api)
    ctx["work_area"] = setup_work_area(api, ctx["worksite"]["id"])
    return ctx


#: The eleven named workers of the standard programme, in creation order.
PROGRAMME_STAFF = (
    ("so", "Sofia Ortiz", None),
    ("sm", "Marcus Reed", None),
    ("lead", "Dana Kim", "HR"),
    ("sec", "Ivan Petrov", "SECURITY"),
    ("ops", "Grace Liu", "OPERATIONS"),
    ("clin", "Nora Bell", "CLINICAL"),
    ("legal", "Omar Haddad", "LEGAL"),
    ("hr", "Priya Nair", None),
    ("coord", "Luis Vega", None),
    ("rep", "Ana Torres", None),
    ("subj", "Karl Frey", None),
)


def _bind_headers(ctx: Context) -> Context:
    ctx["headers"] = {
        "safety_officer": make_safety_officer_headers(ctx["so"]["id"]),
        "site_manager": make_site_manager_headers(ctx["sm"]["id"]),
        "threat_team_lead": make_threat_team_lead_headers(ctx["lead"]["id"]),
        "hr_partner": make_hr_partner_headers(ctx["hr"]["id"]),
        "security_coordinator": make_security_coordinator_headers(ctx["coord"]["id"]),
        "employee": make_employee_headers(ctx["rep"]["id"]),
        "subject": make_employee_headers(ctx["subj"]["id"]),
        "member_sec": make_threat_team_member_headers(ctx["sec"]["id"]),
        "member_ops": make_threat_team_member_headers(ctx["ops"]["id"]),
        "member_clin": make_threat_team_member_headers(ctx["clin"]["id"]),
        "member_legal": make_threat_team_member_headers(ctx["legal"]["id"]),
    }
    return ctx


def setup_programme(api: ApiClient, clock: str = CLOCK_INITIAL) -> Context:
    """The worksite, its front desk and the eleven workers every role needs."""
    ctx = setup_worksite_with_area(api, clock)
    worksite_id = ctx["worksite"]["id"]
    area_id = ctx["work_area"]["id"]
    for key, full_name, discipline in PROGRAMME_STAFF:
        overrides: Dict[str, Any] = {"full_name": full_name}
        if discipline:
            overrides["team_discipline"] = discipline
        ctx[key] = setup_employee(api, worksite_id, area_id, **overrides)
    return _bind_headers(ctx)


# --------------------------------------------------------------------------
# Tier 3: plan lifecycle
# --------------------------------------------------------------------------


def read_plan(api: ApiClient, ctx: Context, plan_id: Optional[str] = None) -> Dict[str, Any]:
    """Re-read the plan so a caller sees its current version and metrics."""
    return get_success_data(
        api.get_prevention_plan(plan_id or ctx["plan"]["id"], ctx["headers"]["safety_officer"])
    )


def read_case(api: ApiClient, ctx: Context, case_id: Optional[str] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_threat_case(case_id or ctx["case"]["id"], ctx["headers"]["threat_team_lead"])
    )


def read_report(api: ApiClient, ctx: Context, report_id: Optional[str] = None) -> Dict[str, Any]:
    return get_success_data(
        api.get_incident_report(report_id or ctx["report"]["id"], ctx["headers"]["safety_officer"])
    )


def read_employee(api: ApiClient, employee_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_employee(employee_id, PROGRAM_ADMIN_HEADERS))


def read_work_area(api: ApiClient, work_area_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_work_area(work_area_id, PROGRAM_ADMIN_HEADERS))


def read_worksite(api: ApiClient, worksite_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_worksite(worksite_id, PROGRAM_ADMIN_HEADERS))


def setup_draft_plan(api: ApiClient, ctx: Optional[Context] = None, **overrides: Any) -> Context:
    """A DRAFT plan on the standard programme."""
    ctx = ctx if ctx is not None else setup_programme(api)
    ctx["plan"] = get_success_data(
        api.create_prevention_plan(
            f.build_prevention_plan(ctx["worksite"]["id"], **overrides),
            ctx["headers"]["safety_officer"],
        )
    )
    return ctx


def add_hazard_assessment(
    api: ApiClient, ctx: Context, work_area_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """Screen one area under the plan, reading the plan version guard first."""
    plan = read_plan(api, ctx)
    payload = f.build_hazard_assessment(
        plan["id"], work_area_id or ctx["work_area"]["id"], plan["version"], **overrides
    )
    return get_success_data(api.create_hazard_assessment(payload, ctx["headers"]["safety_officer"]))


def setup_screened_plan(api: ApiClient, ctx: Optional[Context] = None, **overrides: Any) -> Context:
    """A DRAFT plan whose only work area carries a SCREENING assessment of 64.00."""
    ctx = ctx if ctx is not None else setup_draft_plan(api)
    ctx["hazard_assessment"] = add_hazard_assessment(api, ctx, **overrides)
    return ctx


def setup_submitted_plan(api: ApiClient, ctx: Optional[Context] = None) -> Context:
    """The plan stamped with its submitter and sitting IN_REVIEW."""
    ctx = ctx if ctx is not None else setup_screened_plan(api)
    ctx["plan"] = get_success_data(
        api.submit_prevention_plan(
            ctx["plan"]["id"], f.build_plan_submission(), ctx["headers"]["safety_officer"]
        )
    )
    return ctx


def setup_active_plan(api: ApiClient, ctx: Optional[Context] = None) -> Context:
    """The plan ACTIVE with posture OPEN, activated by someone other than its submitter."""
    ctx = ctx if ctx is not None else setup_submitted_plan(api)
    ctx["plan"] = get_success_data(
        api.activate_prevention_plan(
            ctx["plan"]["id"], f.build_plan_activation(), ctx["headers"]["site_manager"]
        )
    )
    return ctx


# --------------------------------------------------------------------------
# Tier 3: report and case lifecycle
# --------------------------------------------------------------------------


def setup_filed_report(api: ApiClient, ctx: Optional[Context] = None, **overrides: Any) -> Context:
    """A weaponed first-aid coworker report naming the reporter and the subject."""
    ctx = ctx if ctx is not None else setup_active_plan(api)
    payload = f.build_incident_report(
        ctx["worksite"]["id"],
        ctx["work_area"]["id"],
        ctx["rep"]["id"],
        subject_employee_id=ctx["subj"]["id"],
        **overrides,
    )
    ctx["report"] = get_success_data(api.create_incident_report(payload, ctx["headers"]["employee"]))
    return ctx


def setup_escalated_report(api: ApiClient, ctx: Optional[Context] = None) -> Context:
    ctx = ctx if ctx is not None else setup_filed_report(api)
    ctx["report"] = get_success_data(
        api.triage_incident_report(
            ctx["report"]["id"], f.build_triage("ESCALATE"), ctx["headers"]["safety_officer"]
        )
    )
    return ctx


def setup_open_case(api: ApiClient, ctx: Optional[Context] = None) -> Context:
    """An OPEN case led by Dana Kim on the escalated report."""
    ctx = ctx if ctx is not None else setup_escalated_report(api)
    ctx["case"] = get_success_data(
        api.create_threat_case(
            f.build_threat_case(ctx["report"]["id"], ctx["lead"]["id"]),
            ctx["headers"]["threat_team_lead"],
        )
    )
    return ctx


def add_team_seat(
    api: ApiClient, ctx: Context, member_key: str, discipline: str, role_on_team: str = "VOTING_MEMBER"
) -> Dict[str, Any]:
    return get_success_data(
        api.create_team_assignment(
            ctx["case"]["id"],
            f.build_team_assignment(ctx[member_key]["id"], discipline, role_on_team),
            ctx["headers"]["threat_team_lead"],
        )
    )


#: The five seats of the standard roster, in seating order.
STANDARD_ROSTER = (
    ("hr", "lead", "HR", "LEAD"),
    ("sec", "sec", "SECURITY", "VOTING_MEMBER"),
    ("ops", "ops", "OPERATIONS", "VOTING_MEMBER"),
    ("clin", "clin", "CLINICAL", "VOTING_MEMBER"),
    ("legal", "legal", "LEGAL", "VOTING_MEMBER"),
)


def setup_case_with_core_seats(api: ApiClient, ctx: Optional[Context] = None) -> Context:
    """HR, SECURITY and OPERATIONS seated -- the three always-required disciplines."""
    ctx = ctx if ctx is not None else setup_open_case(api)
    ctx.setdefault("seats", {})
    for seat_key, member_key, discipline, role in STANDARD_ROSTER[:3]:
        ctx["seats"][seat_key] = add_team_seat(api, ctx, member_key, discipline, role)
    return ctx


def setup_fully_seated_case(api: ApiClient, ctx: Optional[Context] = None) -> Context:
    """All five disciplines seated, so quorum is met for a weaponed injury case."""
    ctx = ctx if ctx is not None else setup_case_with_core_seats(api)
    ctx.setdefault("seats", {})
    for seat_key, member_key, discipline, role in STANDARD_ROSTER[3:]:
        ctx["seats"][seat_key] = add_team_seat(api, ctx, member_key, discipline, role)
    return ctx


def setup_convened_case(api: ApiClient, ctx: Optional[Context] = None) -> Context:
    """The case ASSESSING in round 1 with its interim score computed."""
    ctx = ctx if ctx is not None else setup_fully_seated_case(api)
    ctx["case"] = get_success_data(
        api.convene_threat_case(
            ctx["case"]["id"], f.build_convene(), ctx["headers"]["threat_team_lead"]
        )
    )
    return ctx


#: The five ballots of the standard round, in casting order.
STANDARD_BALLOTS = (
    ("member_ops", "ELEVATED", "Shift overlap keeps the two employees in contact."),
    ("member_sec", "IMMINENT", "Weapon on site and no badge control at the front desk."),
    ("threat_team_lead", "ELEVATED", "Pattern of escalating verbal conflict on file."),
    ("member_clin", "MONITOR", "No clinical indicators of imminent harm."),
    ("member_legal", "IMMINENT", "Conduct is chargeable; restraining order is viable."),
)


def cast_standard_ballots(api: ApiClient, ctx: Context, count: int = 5) -> Context:
    """Cast the first ``count`` ballots of the standard round.

    Casting a ballot writes the caller's own seat, so each response is recorded
    under ``ctx["ballot_seats"]`` and the case itself is re-read afterwards.
    """
    ctx.setdefault("ballot_seats", {})
    for header_key, value, rationale in STANDARD_BALLOTS[:count]:
        ctx["ballot_seats"][header_key] = get_success_data(
            api.cast_ballot(
                ctx["case"]["id"], f.build_ballot(value, rationale), ctx["headers"][header_key]
            )
        )
    if count > 0:
        ctx["case"] = read_case(api, ctx)
    return ctx


def setup_deliberating_case(api: ApiClient, ctx: Optional[Context] = None) -> Context:
    """Every voting seat has balloted, so the case has auto-advanced to DELIBERATION."""
    ctx = ctx if ctx is not None else setup_convened_case(api)
    return cast_standard_ballots(api, ctx, 5)


def setup_monitoring_case(api: ApiClient, ctx: Optional[Context] = None) -> Context:
    """The ELEVATED_RISK decision recorded, with the four-link cascade run."""
    ctx = ctx if ctx is not None else setup_deliberating_case(api)
    ctx["case"] = get_success_data(
        api.decide_threat_case(
            ctx["case"]["id"], f.build_decision("ELEVATED_RISK"), ctx["headers"]["threat_team_lead"]
        )
    )
    return ctx


def drive_case_to_monitoring(api: ApiClient, ctx: Context) -> Context:
    """Open, seat, convene, ballot and decide a case on an already-escalated report."""
    ctx = setup_open_case(api, ctx)
    ctx = setup_case_with_core_seats(api, ctx)
    ctx = setup_fully_seated_case(api, ctx)
    ctx = setup_convened_case(api, ctx)
    ctx = cast_standard_ballots(api, ctx)
    return setup_monitoring_case(api, ctx)


def read_case_log_entries(api: ApiClient, ctx: Context) -> List[Dict[str, Any]]:
    """The log entries the case's decision produced."""
    return get_success_data(
        api.list_log_entries(ctx["headers"]["safety_officer"], {"case_id": ctx["case"]["id"]})
    )


def setup_amended_log_case(api: ApiClient, ctx: Optional[Context] = None) -> Context:
    """A monitoring case whose auto-appended entry has been amended to eight elements."""
    ctx = ctx if ctx is not None else setup_monitoring_case(api)
    entries = read_case_log_entries(api, ctx)
    ctx["log_entry"] = entries[0]
    ctx["log_amendment"] = get_success_data(
        api.amend_log_entry(
            ctx["log_entry"]["id"], f.build_log_amendment(), ctx["headers"]["safety_officer"]
        )
    )
    return ctx


# --------------------------------------------------------------------------
# Tier 4: training accumulation
# --------------------------------------------------------------------------


def setup_training_cohort(api: ApiClient, ctx: Optional[Context] = None, **module_overrides: Any) -> Context:
    """One ADMIN-scoped module plus an assignment for every ADMIN worker on site."""
    ctx = ctx if ctx is not None else setup_programme(api)
    ctx["module"] = get_success_data(
        api.create_training_module(f.build_training_module(**module_overrides), PROGRAM_ADMIN_HEADERS)
    )
    return ctx


def assign_training(
    api: ApiClient, ctx: Context, employee_id: str, module_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """Assign a module, reading the employee version guard immediately beforehand."""
    employee = get_success_data(api.get_employee(employee_id, ctx["headers"]["hr_partner"]))
    payload = f.build_training_assignment(
        employee_id, module_id or ctx["module"]["id"], employee["version"], **overrides
    )
    return get_success_data(api.create_training_assignment(payload, ctx["headers"]["hr_partner"]))


def complete_training(
    api: ApiClient, ctx: Context, assignment_id: str, employee_id: str, score: int = 92
) -> Dict[str, Any]:
    return get_success_data(
        api.complete_training_assignment(
            assignment_id, f.build_training_completion(score), make_employee_headers(employee_id)
        )
    )


def setup_qualified_escort(
    api: ApiClient, ctx: Optional[Context] = None, **module_overrides: Any
) -> Context:
    """A SECURITY worker holding a current completion of the escort-required module."""
    ctx = ctx if ctx is not None else setup_programme(api)
    ctx["escort_module"] = get_success_data(
        api.create_training_module(f.build_escort_module(**module_overrides), PROGRAM_ADMIN_HEADERS)
    )
    ctx["escort"] = setup_employee(
        api,
        ctx["worksite"]["id"],
        ctx["work_area"]["id"],
        full_name="Bea Solis",
        job_function="SECURITY",
    )
    ctx["escort_assignment"] = assign_training(
        api, ctx, ctx["escort"]["id"], ctx["escort_module"]["id"]
    )
    ctx["escort_assignment"] = complete_training(
        api, ctx, ctx["escort_assignment"]["id"], ctx["escort"]["id"], score=92
    )
    return ctx


def setup_monitoring_case_with_escort(api: ApiClient, **module_overrides: Any) -> Context:
    """A monitoring case on a plan whose worksite already holds a qualified escort."""
    ctx = setup_qualified_escort(api, None, **module_overrides)
    ctx = setup_draft_plan(api, ctx)
    ctx = setup_screened_plan(api, ctx)
    ctx = setup_submitted_plan(api, ctx)
    ctx = setup_active_plan(api, ctx)
    ctx = setup_filed_report(api, ctx)
    ctx = setup_escalated_report(api, ctx)
    return drive_case_to_monitoring(api, ctx)


def setup_five_pair_training_cohort(api: ApiClient, completed: int = 4) -> Context:
    """Five employee-and-module pairs of which ``completed`` are finished.

    Four of five pairs is exactly 80.00 percent and three of five is exactly
    60.00 percent. The three role holders are SECURITY workers, so the single
    ADMIN-scoped module pairs only with the five ADMIN workers.
    """
    ctx = setup_worksite_with_area(api)
    worksite_id = ctx["worksite"]["id"]
    area_id = ctx["work_area"]["id"]
    ctx["dual"] = setup_employee(
        api, worksite_id, area_id, full_name="Rhea Vance", job_function="SECURITY"
    )
    ctx["sm2"] = setup_employee(
        api, worksite_id, area_id, full_name="Marcus Reed", job_function="SECURITY"
    )
    ctx["hr2"] = setup_employee(
        api, worksite_id, area_id, full_name="Priya Nair", job_function="SECURITY"
    )
    ctx["headers"] = {
        "safety_officer": make_safety_officer_headers(ctx["dual"]["id"]),
        "site_manager": make_site_manager_headers(ctx["sm2"]["id"]),
        "site_manager_self": make_site_manager_headers(ctx["dual"]["id"]),
        "hr_partner": make_hr_partner_headers(ctx["hr2"]["id"]),
    }
    ctx["learners"] = []
    for name in ("Wendy Cole", "Xavier Poe", "Yara Nunes", "Zane Alder", "Vera Blum"):
        ctx["learners"].append(
            setup_employee(api, worksite_id, area_id, full_name=name, job_function="ADMIN")
        )
    ctx["module"] = get_success_data(
        api.create_training_module(f.build_training_module(), PROGRAM_ADMIN_HEADERS)
    )
    ctx["assignments"] = []
    for index, learner in enumerate(ctx["learners"]):
        assignment = assign_training(api, ctx, learner["id"], due_at="2026-08-20T00:00:00Z")
        if index < completed:
            assignment = complete_training(api, ctx, assignment["id"], learner["id"], score=88)
        ctx["assignments"].append(assignment)
    return ctx


# --------------------------------------------------------------------------
# Tier 4: case actions
# --------------------------------------------------------------------------


def read_case_action(api: ApiClient, ctx: Context, action_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.get_case_action(action_id, ctx["headers"]["security_coordinator"])
    )


def add_escort_action(
    api: ApiClient,
    ctx: Context,
    starts_at: str,
    ends_at: str,
    escort_id: Optional[str] = None,
    subject_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Book a SECURITY_ESCORT for the protected employee on the monitoring case."""
    payload = f.build_escort_action(
        ctx["case"]["id"],
        subject_id or ctx["rep"]["id"],
        escort_id or ctx["escort"]["id"],
        starts_at,
        ends_at,
        **overrides,
    )
    return get_success_data(
        api.create_case_action(payload, ctx["headers"]["security_coordinator"])
    )


def add_restriction_action(
    api: ApiClient,
    ctx: Context,
    starts_at: str,
    ends_at: str,
    subject_id: Optional[str] = None,
    work_area_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Bar one employee from one work area for a half-open interval."""
    payload = f.build_access_restriction(
        ctx["case"]["id"],
        subject_id or ctx["subj"]["id"],
        work_area_id or ctx["work_area"]["id"],
        starts_at,
        ends_at,
        **overrides,
    )
    return get_success_data(
        api.create_case_action(payload, ctx["headers"]["security_coordinator"])
    )


def add_post_incident_action(
    api: ApiClient,
    ctx: Context,
    action_type: str = "COUNSELING_REFERRAL",
    assigned_key: str = "hr",
    due_at: str = "2026-08-08T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a POST_INCIDENT action assigned to one of the programme's workers."""
    payload = f.build_post_incident_action(
        ctx["case"]["id"], action_type, ctx[assigned_key]["id"], due_at, **overrides
    )
    return get_success_data(api.create_case_action(payload, ctx["headers"]["hr_partner"]))


# --------------------------------------------------------------------------
# Tier 4: drill accumulation
# --------------------------------------------------------------------------


def setup_drilled_plan(api: ApiClient, ctx: Optional[Context] = None) -> Context:
    """An ACTIVE plan with two scheduled drills ready to execute."""
    ctx = ctx if ctx is not None else setup_active_plan(api)
    ctx["drill_one"] = get_success_data(
        api.create_drill(
            f.build_drill(ctx["plan"]["id"], scenario_type="ACTIVE_ASSAILANT"),
            ctx["headers"]["safety_officer"],
        )
    )
    ctx["drill_two"] = get_success_data(
        api.create_drill(
            f.build_drill(
                ctx["plan"]["id"], scenario_type="LOCKDOWN", scheduled_at="2026-08-01T13:00:00Z"
            ),
            ctx["headers"]["safety_officer"],
        )
    )
    return ctx


# --------------------------------------------------------------------------
# Operations
# --------------------------------------------------------------------------


def move_clock(api: ApiClient, current_utc: str) -> str:
    """Move the logical clock without touching any stored row."""
    return get_success_data(api.set_clock(f.build_clock(current_utc), PROGRAM_ADMIN_HEADERS))[
        "current_utc"
    ]


def run_daily_sweep(api: ApiClient) -> Dict[str, Any]:
    """Run the nightly compliance sweep and return its eight counters."""
    return get_success_data(api.daily_run(PROGRAM_ADMIN_HEADERS))
