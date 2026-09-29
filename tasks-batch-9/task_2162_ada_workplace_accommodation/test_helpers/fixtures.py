"""Composite setup helpers.

Every test starts against an empty database, so each helper here builds its
preconditions from scratch through the PRD's own endpoints.  Setup calls use
the lenient validator so a broken precondition surfaces as "Setup step failed"
rather than as a confusing assertion inside the test under study.

A scenario is a plain dict carrying the rows the walk created:

    profile, functions, employee, manager, case, options, trial, denial,
    appeal, absence  plus the header dicts bound to the entity-backed actors.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK, TEST_DEFAULTS
from .factories import (
    create_absence_record_payload,
    create_accommodation_request_payload,
    create_effectiveness_review_payload,
    create_employee_payload,
    create_essential_function_payload,
    create_function_analysis_payload,
    create_job_profile_payload,
    create_medical_disclosure_payload,
    create_option_payload,
    create_trial_period_payload,
    next_suffix,
    publish_profile_payload,
)
from .test_users import (
    TEST_USERS,
    make_employee_headers,
    make_manager_headers,
)

COORD = TEST_USERS["coordinator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]
FINANCE = TEST_USERS["finance_headers"]
MEDICAL = TEST_USERS["medical_officer_headers"]
APPEAL = TEST_USERS["appeal_officer_headers"]


# --------------------------------------------------------------------------
# Operational primitives
# --------------------------------------------------------------------------
def set_clock(to_iso8601: str = DEFAULT_CLOCK) -> dict:
    """Pin the logical clock. Nothing in this service reads wall-clock time."""
    return get_success_data(
        api_client.set_current_utc({"to_iso8601": to_iso8601}, AUDITOR)
    )


def run_sweep() -> dict:
    """Run the daily sweep and return its counter block."""
    return get_success_data(api_client.daily_sweep(AUDITOR))


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------
def read_case(request_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_accommodation_request(request_id, headers or COORD)
    )


def read_option(option_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.get_accommodation_option(option_id, headers or FINANCE)
    )


def read_profile(profile_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_job_profile(profile_id, headers or FINANCE))


def read_employee(employee_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_employee(employee_id, headers or COORD))


def read_trial(trial_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_trial_period(trial_id, headers or COORD))


def read_denial(denial_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_denial_record(denial_id, headers or COORD))


def read_appeal(appeal_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_appeal(appeal_id, headers or COORD))


def read_absence(absence_id: str, headers=None) -> dict:
    return get_success_data(api_client.get_absence_record(absence_id, headers or COORD))


def case_version(request_id: str) -> int:
    """The concurrency token an OCC-guarded case write must carry."""
    return read_case(request_id)["version"]


def option_version(option_id: str) -> int:
    """The concurrency token an undue-hardship assessment must carry."""
    return read_option(option_id)["version"]


# --------------------------------------------------------------------------
# Job architecture
# --------------------------------------------------------------------------
def create_profile(**overrides) -> dict:
    return get_success_data(
        api_client.create_job_profile(create_job_profile_payload(**overrides), COORD)
    )


def add_function(profile_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_essential_function(
            profile_id, create_essential_function_payload(**overrides), COORD
        )
    )


def publish_profile(profile_id: str, label: str = None) -> dict:
    return get_success_data(
        api_client.publish_job_profile(
            profile_id,
            publish_profile_payload(
                **({"profile_version_label": label} if label else {})
            ),
            COORD,
        )
    )


def create_employee(profile_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_employee(
            create_employee_payload(profile_id, **overrides), COORD
        )
    )


DEFAULT_FUNCTIONS = ({"criticality_weight": 5},)


def setup_workforce(
    functions=DEFAULT_FUNCTIONS,
    department_code: str = "OPS",
    manager_department_code: str = None,
    department_annual_budget_cents: int = None,
    employer_annual_budget_cents: int = None,
    profile_version_label: str = None,
    publish: bool = True,
    with_manager: bool = True,
) -> dict:
    """A published job profile, its duties, one employee and one people manager.

    ``functions`` is a sequence of override dicts, one per duty to author.
    """
    profile_overrides = {"department_code": department_code}
    if department_annual_budget_cents is not None:
        profile_overrides["department_annual_budget_cents"] = department_annual_budget_cents
    if employer_annual_budget_cents is not None:
        profile_overrides["employer_annual_budget_cents"] = employer_annual_budget_cents

    profile = create_profile(**profile_overrides)
    created = [add_function(profile["id"], **dict(spec)) for spec in functions]
    if publish:
        profile = publish_profile(profile["id"], profile_version_label)

    employee = create_employee(profile["id"], department_code=department_code)
    manager = None
    if with_manager:
        manager = create_employee(
            profile["id"],
            department_code=manager_department_code or department_code,
            is_people_manager=True,
            job_title="Operations Manager",
            full_name="Lee Park",
        )

    ctx = {
        "profile": profile,
        "functions": created,
        "employee": employee,
        "manager": manager,
        "employee_headers": make_employee_headers(employee["id"]),
        "manager_headers": make_manager_headers(manager["id"]) if manager else None,
        "options": [],
        "assessments": [],
    }
    return ctx


def essential_function_ids(ctx) -> list:
    """The ids of the duties that are simultaneously is_essential and ACTIVE."""
    return [f["id"] for f in ctx["functions"] if f.get("is_essential", True)]


# --------------------------------------------------------------------------
# Case intake and the stage dimension
# --------------------------------------------------------------------------
def open_case(ctx, as_role: str = "Employee", **overrides) -> dict:
    """Open an accommodation case for ctx's employee and remember it."""
    headers = ctx["employee_headers"] if as_role == "Employee" else COORD
    case = get_success_data(
        api_client.create_accommodation_request(
            create_accommodation_request_payload(ctx["employee"]["id"], **overrides),
            headers,
        )
    )
    ctx["case"] = case
    return case


def advance_case(ctx, target_stage: str, headers=None) -> dict:
    case = get_success_data(
        api_client.advance_accommodation_request(
            ctx["case"]["id"], {"target_stage": target_stage}, headers or COORD
        )
    )
    ctx["case"] = case
    return case


def record_analysis(ctx, function_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_function_analysis(
            ctx["case"]["id"],
            create_function_analysis_payload(function_id, **overrides),
            ctx["manager_headers"],
        )
    )


def record_all_analyses(ctx) -> list:
    """One RECORDED analysis for every live essential duty on the pinned profile."""
    analyses = [record_analysis(ctx, fid) for fid in essential_function_ids(ctx)]
    ctx["analyses"] = analyses
    return analyses


def propose_option(ctx, covers="all", headers=None, **overrides) -> dict:
    if covers == "all":
        coverage = essential_function_ids(ctx)
    elif covers in (None, "none"):
        coverage = []
    else:
        coverage = [c["id"] if isinstance(c, dict) else c for c in covers]
    option = get_success_data(
        api_client.create_accommodation_option(
            ctx["case"]["id"],
            create_option_payload(coverage, **overrides),
            headers or COORD,
        )
    )
    ctx["options"].append(option)
    return option


def assess_option(ctx, option, basis: str = "SITE_LOCAL") -> dict:
    """Run the undue-hardship assessment, reading the option's fresh version."""
    option_id = option["id"] if isinstance(option, dict) else option
    assessment = get_success_data(
        api_client.create_hardship_assessment(
            option_id,
            {
                "assessment_basis": basis,
                "expected_option_version": option_version(option_id),
            },
            FINANCE,
        )
    )
    ctx["assessments"].append(assessment)
    return assessment


def decide_case(ctx, **payload) -> dict:
    case = get_success_data(
        api_client.decide_accommodation_request(ctx["case"]["id"], payload, COORD)
    )
    ctx["case"] = case
    return case


# --------------------------------------------------------------------------
# Documentation rounds
# --------------------------------------------------------------------------
def issue_doc_round(ctx, scope=None, due_date: str = "2026-08-17T00:00:00Z", **overrides) -> dict:
    """Issue one documentation round, reading the case's fresh version first."""
    payload = {
        "scope_fields_requested": list(scope or ["functional_limitations"]),
        "due_date": due_date,
        "is_second_opinion": False,
        "expected_request_version": case_version(ctx["case"]["id"]),
    }
    payload.update(overrides)
    round_row = get_success_data(
        api_client.create_medical_doc_request(ctx["case"]["id"], payload, COORD)
    )
    ctx.setdefault("doc_rounds", []).append(round_row)
    ctx["case"] = read_case(ctx["case"]["id"])
    return round_row


def respond_to_round(ctx, doc_round, summary: str = "Occupational health letter uploaded") -> dict:
    round_id = doc_round["id"] if isinstance(doc_round, dict) else doc_round
    return get_success_data(
        api_client.respond_medical_doc_request(
            round_id, {"response_summary": summary}, ctx["employee_headers"]
        )
    )


def adjudicate_round(doc_round, verdict: str = "SUFFICIENT", note: str = None) -> dict:
    round_id = doc_round["id"] if isinstance(doc_round, dict) else doc_round
    payload = {"verdict": verdict}
    if note is not None:
        payload["adjudication_note"] = note
    return get_success_data(
        api_client.adjudicate_medical_doc_request(round_id, payload, MEDICAL)
    )


# --------------------------------------------------------------------------
# Stage-walk shortcuts
# --------------------------------------------------------------------------
def setup_case_at_function_analysis(ctx=None, **workforce_kwargs) -> dict:
    """Obvious-disability case advanced INTAKE -> FUNCTION_ANALYSIS."""
    ctx = ctx or setup_workforce(**workforce_kwargs)
    open_case(ctx, disability_obvious=True)
    advance_case(ctx, "FUNCTION_ANALYSIS")
    return ctx


def setup_case_at_option_exploration(ctx=None, **workforce_kwargs) -> dict:
    """Every live essential duty analysed, then FUNCTION_ANALYSIS -> OPTION_EXPLORATION."""
    ctx = setup_case_at_function_analysis(ctx, **workforce_kwargs)
    record_all_analyses(ctx)
    advance_case(ctx, "OPTION_EXPLORATION")
    return ctx


def setup_case_at_hardship_review(option_specs=None, ctx=None, **workforce_kwargs) -> dict:
    """Options proposed, then OPTION_EXPLORATION -> HARDSHIP_REVIEW.

    ``option_specs`` is a sequence of dicts; each may carry a ``covers`` key
    plus any option field override.
    """
    ctx = setup_case_at_option_exploration(ctx, **workforce_kwargs)
    for spec in option_specs or [{}]:
        spec = dict(spec)
        covers = spec.pop("covers", "all")
        propose_option(ctx, covers=covers, **spec)
    advance_case(ctx, "HARDSHIP_REVIEW")
    return ctx


def setup_case_at_decision_pending(
    option_specs=None, bases=None, ctx=None, **workforce_kwargs
) -> dict:
    """Every option assessed, then HARDSHIP_REVIEW -> DECISION_PENDING."""
    ctx = setup_case_at_hardship_review(option_specs, ctx, **workforce_kwargs)
    bases = list(bases or ["SITE_LOCAL"] * len(ctx["options"]))
    for option, basis in zip(ctx["options"], bases):
        assess_option(ctx, option, basis)
    advance_case(ctx, "DECISION_PENDING")
    return ctx


def setup_granted_case(
    decision: str = "GRANT_PERMANENT", option_specs=None, bases=None, ctx=None, **workforce_kwargs
) -> dict:
    """Walk a case all the way to a grant on its first (cleared) option."""
    ctx = setup_case_at_decision_pending(option_specs, bases, ctx, **workforce_kwargs)
    decide_case(
        ctx, decision=decision, selected_option_id=ctx["options"][0]["id"]
    )
    return ctx


def setup_case_at_trial_setup(option_specs=None, ctx=None, **workforce_kwargs) -> dict:
    """A GRANT_WITH_TRIAL case sitting in TRIAL_SETUP with its option SELECTED."""
    return setup_granted_case(
        "GRANT_WITH_TRIAL", option_specs, None, ctx, **workforce_kwargs
    )


def setup_denied_case(
    denial_basis: str = "NOT_QUALIFIED",
    rationale_text: str = "No accommodation on the table clears the essential duties.",
    alternative_option_id: str = None,
    option_specs=None,
    bases=None,
    ctx=None,
    **workforce_kwargs,
) -> dict:
    """A case denied out of DECISION_PENDING; ctx['denial'] holds the record."""
    ctx = setup_case_at_decision_pending(option_specs, bases, ctx, **workforce_kwargs)
    payload = {
        "decision": "DENY",
        "denial_basis": denial_basis,
        "rationale_text": rationale_text,
    }
    if alternative_option_id:
        payload["alternative_option_id"] = alternative_option_id
    decide_case(ctx, **payload)
    ctx["denial"] = _latest_denial(ctx["case"]["id"])
    return ctx


def setup_case_denied_out_of_doc_pending(ctx=None, **workforce_kwargs) -> dict:
    """Two documentation rounds burned without a sufficient response, then DENY.

    Round one is issued at 2026-08-03T09:00:00Z with a 2026-08-17T00:00:00Z
    window; the clock is then moved to exactly that endpoint so the second
    round does not collide, and the denial is recorded on 2026-08-17.
    """
    set_clock("2026-08-03T09:00:00Z")
    ctx = ctx or setup_workforce(**workforce_kwargs)
    open_case(ctx, disability_obvious=False)
    issue_doc_round(ctx, ["functional_limitations"], "2026-08-17T00:00:00Z")
    set_clock("2026-08-17T00:00:00Z")
    issue_doc_round(ctx, ["work_restrictions"], "2026-08-31T00:00:00Z")
    decide_case(
        ctx,
        decision="DENY",
        denial_basis="INSUFFICIENT_DOCUMENTATION",
        rationale_text="Neither documentation round produced a sufficient response.",
    )
    ctx["denial"] = _latest_denial(ctx["case"]["id"])
    return ctx


def _latest_denial(request_id: str) -> dict:
    body = api_client.list_denial_records(COORD, {"request_id": request_id})
    rows = get_success_data(body)
    assert rows, f"Setup step failed: no denial record on case {request_id}"
    return rows[-1]


# --------------------------------------------------------------------------
# Appeals
# --------------------------------------------------------------------------
def file_appeal(ctx, grounds_text: str = "The employer-wide budget was never considered.") -> dict:
    appeal = get_success_data(
        api_client.create_appeal(
            ctx["denial"]["id"], {"grounds_text": grounds_text}, ctx["employee_headers"]
        )
    )
    ctx["appeal"] = appeal
    return appeal


def start_appeal_review(ctx, officer_headers=None) -> dict:
    appeal = get_success_data(
        api_client.transition_appeal(
            ctx["appeal"]["id"], {"action": "START_REVIEW"}, officer_headers or APPEAL
        )
    )
    ctx["appeal"] = appeal
    return appeal


def setup_appeal_under_review(ctx=None, **kwargs) -> dict:
    """A denied case whose appeal APPEAL-1 has taken under review."""
    ctx = ctx if ctx and "denial" in ctx else setup_denied_case(ctx=ctx, **kwargs)
    file_appeal(ctx)
    start_appeal_review(ctx)
    return ctx


# --------------------------------------------------------------------------
# Trials
# --------------------------------------------------------------------------
def schedule_trial(ctx, **overrides) -> dict:
    payload = create_trial_period_payload(
        ctx["case"]["id"], ctx["case"]["selected_option_id"], **overrides
    )
    trial = get_success_data(api_client.create_trial_period(payload, COORD))
    ctx["trial"] = trial
    ctx["case"] = read_case(ctx["case"]["id"])
    return trial


def record_review(ctx, employee_rating: int, manager_rating: int, objective_metric_pct: int) -> dict:
    review = get_success_data(
        api_client.create_effectiveness_review(
            ctx["trial"]["id"],
            create_effectiveness_review_payload(
                employee_rating=employee_rating,
                manager_rating=manager_rating,
                objective_metric_pct=objective_metric_pct,
            ),
            ctx["manager_headers"],
        )
    )
    ctx.setdefault("reviews", []).append(review)
    return review


def setup_active_trial(
    scoring_mode: str = "LATEST_WEIGHTED",
    start_date: str = "2026-09-01",
    end_date: str = "2026-11-30",
    ctx=None,
    **workforce_kwargs,
) -> dict:
    """A granted-with-trial case whose trial the sweep has moved to ACTIVE."""
    set_clock("2026-08-03T09:00:00Z")
    ctx = setup_case_at_trial_setup(ctx=ctx, **workforce_kwargs)
    schedule_trial(ctx, start_date=start_date, end_date=end_date, scoring_mode=scoring_mode)
    set_clock(f"{start_date}T08:00:00Z")
    run_sweep()
    ctx["trial"] = read_trial(ctx["trial"]["id"])
    return ctx


THREE_IMPROVING_REVIEWS = ((4, 4, 40), (6, 6, 60), (9, 9, 90))
REVIEW_DATES = ("2026-09-15T08:00:00Z", "2026-10-15T08:00:00Z", "2026-11-15T08:00:00Z")


def setup_trial_with_reviews(
    reviews=THREE_IMPROVING_REVIEWS,
    review_dates=REVIEW_DATES,
    scoring_mode: str = "LATEST_WEIGHTED",
    ctx=None,
    **workforce_kwargs,
) -> dict:
    """An ACTIVE trial fed the given check-ins, one per supplied review date."""
    ctx = setup_active_trial(scoring_mode=scoring_mode, ctx=ctx, **workforce_kwargs)
    for spec, at in zip(reviews, review_dates):
        set_clock(at)
        record_review(ctx, *spec)
    ctx["trial"] = read_trial(ctx["trial"]["id"])
    return ctx


def resolve_trial(ctx, outcome: str) -> dict:
    trial = get_success_data(
        api_client.resolve_trial_period(ctx["trial"]["id"], {"outcome": outcome}, COORD)
    )
    ctx["trial"] = trial
    ctx["case"] = read_case(ctx["case"]["id"])
    return trial


# --------------------------------------------------------------------------
# Absence records
# --------------------------------------------------------------------------
def create_absence(ctx, **overrides) -> dict:
    absence = get_success_data(
        api_client.create_absence_record(
            create_absence_record_payload(ctx["employee"]["id"], **overrides), COORD
        )
    )
    ctx.setdefault("absences", []).append(absence)
    ctx["absence"] = absence
    return absence


def move_absence(absence, to_status: str) -> dict:
    absence_id = absence["id"] if isinstance(absence, dict) else absence
    return get_success_data(
        api_client.transition_absence_record(absence_id, {"to_status": to_status}, COORD)
    )


def link_absence_to_case(ctx, absence) -> dict:
    absence_id = absence["id"] if isinstance(absence, dict) else absence
    case = get_success_data(
        api_client.update_accommodation_request(
            ctx["case"]["id"], {"absence_record_id": absence_id}, COORD
        )
    )
    ctx["case"] = case
    return case


# --------------------------------------------------------------------------
# Disclosure log
# --------------------------------------------------------------------------
def log_disclosure(ctx, headers=None, **overrides) -> dict:
    row = get_success_data(
        api_client.create_medical_disclosure(
            ctx["case"]["id"], create_medical_disclosure_payload(**overrides), headers or COORD
        )
    )
    ctx.setdefault("disclosures", []).append(row)
    ctx["case"] = read_case(ctx["case"]["id"])
    return row


def seal_case(ctx, count: int = 1) -> list:
    """Append `count` unauthorized disclosures; each costs 30 integrity points."""
    rows = []
    for _ in range(count):
        rows.append(
            log_disclosure(
                ctx,
                headers=AUDITOR,
                disclosed_to_role="EXTERNAL",
                disclosed_to_user_id=f"VENDOR-{next_suffix()}",
                disclosure_purpose="OTHER",
                fields_disclosed=["work_restrictions"],
            )
        )
    return rows


def unseal_case(ctx) -> dict:
    case = get_success_data(
        api_client.set_confidentiality(
            ctx["case"]["id"], {"to_posture": "RESTRICTED"}, AUDITOR
        )
    )
    ctx["case"] = case
    return case


# --------------------------------------------------------------------------
# Renewal
# --------------------------------------------------------------------------
def setup_case_at_renewal_due(
    granted_on: str = "2026-08-03T09:00:00Z",
    review_due_on: str = "2027-08-03T00:00:00Z",
    ctx=None,
    **workforce_kwargs,
) -> dict:
    """A permanently granted case the sweep has promoted to RENEWAL_DUE."""
    set_clock(granted_on)
    ctx = setup_granted_case("GRANT_PERMANENT", ctx=ctx, **workforce_kwargs)
    set_clock(review_due_on)
    run_sweep()
    ctx["case"] = read_case(ctx["case"]["id"])
    return ctx


def renewal_review(ctx, outcome: str, expected_request_version: int = None) -> dict:
    payload = {
        "outcome": outcome,
        "expected_request_version": (
            expected_request_version
            if expected_request_version is not None
            else case_version(ctx["case"]["id"])
        ),
    }
    case = get_success_data(
        api_client.renewal_review(ctx["case"]["id"], payload, COORD)
    )
    ctx["case"] = case
    return case


# --------------------------------------------------------------------------
# Named scenario constants reused across the suite
# --------------------------------------------------------------------------
# one_time 100003 with recurring 4315 nets exactly 150636 cents.
SPLIT_ROUNDING_OPTION = {
    "one_time_cost_cents": 100_003,
    "recurring_monthly_cost_cents": 4_315,
    "implementation_days": 30,
}
# On a 2_000_000 department budget this scores exactly 70.00 and is UNDUE.
UNDUE_OPTION = {
    "one_time_cost_cents": TEST_DEFAULTS["UNDUE_ONE_TIME_CENTS"],
    "recurring_monthly_cost_cents": 0,
    "implementation_days": 60,
}
# On a 2_000_000 department budget this scores 69.99 and is BORDERLINE.
BORDERLINE_OPTION = {
    "one_time_cost_cents": 121_984,
    "recurring_monthly_cost_cents": 0,
    "implementation_days": 60,
}
# On a 1_500_000 department budget this scores 28.15 and is NOT_UNDUE.
CHEAP_OPTION = {
    "one_time_cost_cents": TEST_DEFAULTS["CHEAP_ONE_TIME_CENTS"],
    "recurring_monthly_cost_cents": 0,
    "implementation_days": 10,
}

__all__ = [name for name in dir() if not name.startswith("_")]
