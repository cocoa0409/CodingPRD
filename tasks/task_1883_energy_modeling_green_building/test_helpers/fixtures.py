"""Composite setup helpers for multi-step test prerequisites.

The test runner restarts the API server before every test, so every fixture
builds its preconditions from scratch using only PRD-declared endpoints.
Setup calls use get_success_data() so a failed precondition surfaces as a
clear "setup failed" error rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_commissioning_task_payload,
    create_cost_premium_analysis_payload,
    create_credit_attempt_payload,
    create_credit_library_entry_payload,
    create_energy_model_payload,
    create_incentive_program_payload,
    create_performance_report_payload,
    create_project_incentive_payload,
    create_project_payload,
    create_review_comment_payload,
    create_team_member_payload,
)
from .test_users import (
    TEST_USERS,
    make_commissioning_agent_headers,
    make_documentation_specialist_headers,
    make_energy_modeler_headers,
    make_project_administrator_headers,
)

ADMIN = TEST_USERS["program_admin_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]
ANY = TEST_USERS["any_headers"]


# ─── Clock (PRD §2.10) ────────────────────────────────

def set_clock(to_iso8601: str):
    """Advance the server-side logical clock."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


# ─── Tier 1: single-entity creation / transitions ─────

def create_team_member(**overrides):
    return get_success_data(
        api_client.create_team_member(create_team_member_payload(**overrides), ADMIN)
    )


def create_members():
    """The four consultant-side team members used across the engagement:
    a MANAGEMENT administrator, a DOCUMENTATION specialist, a MODELING
    modeler, and an independent COMMISSIONING agent."""
    return {
        "admin": create_team_member(
            full_name="Adam Admin", email="adam@x.com", specialty="MANAGEMENT"),
        "spec": create_team_member(
            full_name="Dana Docs", email="dana@x.com", specialty="DOCUMENTATION"),
        "modeler": create_team_member(
            full_name="Molly Modeler", email="molly@x.com", specialty="MODELING"),
        "cx": create_team_member(
            full_name="Carl Cx", email="carl@x.com", specialty="COMMISSIONING",
            is_independent=True),
    }


def create_credit_entry(**overrides):
    return get_success_data(
        api_client.create_credit_library_entry(
            create_credit_library_entry_payload(**overrides), ADMIN)
    )


def create_project(admin_id, **overrides):
    return get_success_data(
        api_client.create_project(
            create_project_payload(**overrides),
            make_project_administrator_headers(admin_id))
    )


def get_project(project_id):
    return get_success_data(api_client.get_project(project_id, ANY))


def get_attempt(attempt_id):
    return get_success_data(api_client.get_credit_attempt(attempt_id, ANY))


def create_energy_model(project_id, modeler_id, model_type="BASELINE",
                        modeled=12000000, confirmed=None,
                        includes_unconfirmed=False, standard="ASHRAE_90_1_2019"):
    """Create a DRAFT model; OCC-guarded, so the project version is re-read
    immediately before the create (PRD §2.5)."""
    version = get_project(project_id)["version"]
    payload = create_energy_model_payload(
        project_id, version,
        model_type=model_type,
        modeling_standard=standard,
        annual_energy_cost_modeled_cents=modeled,
        annual_energy_cost_confirmed_only_cents=confirmed if confirmed is not None else modeled,
        includes_unconfirmed_measures=includes_unconfirmed,
    )
    return get_success_data(
        api_client.create_energy_model(payload, make_energy_modeler_headers(modeler_id))
    )


def lock_model(model_id, modeler_id):
    return get_success_data(
        api_client.lock_energy_model(model_id, make_energy_modeler_headers(modeler_id))
    )


def create_locked_models(project_id, modeler_id, baseline_cost=12000000,
                         proposed_modeled=11400000, proposed_confirmed=11400000,
                         includes_unconfirmed=False):
    """LOCKED BASELINE + LOCKED PROPOSED on the project. Returns (baseline, proposed)."""
    baseline = create_energy_model(
        project_id, modeler_id, "BASELINE", modeled=baseline_cost, confirmed=baseline_cost)
    proposed = create_energy_model(
        project_id, modeler_id, "PROPOSED", modeled=proposed_modeled,
        confirmed=proposed_confirmed, includes_unconfirmed=includes_unconfirmed)
    baseline = lock_model(baseline["id"], modeler_id)
    proposed = lock_model(proposed["id"], modeler_id)
    return baseline, proposed


def create_attempt(project_id, entry_id, owner_id, admin_id, phase="DESIGN"):
    return get_success_data(
        api_client.create_credit_attempt(
            create_credit_attempt_payload(project_id, entry_id, owner_id, phase=phase),
            make_project_administrator_headers(admin_id))
    )


def assign_owner(attempt_id, owner_id, admin_id):
    return get_success_data(
        api_client.assign_owner(
            attempt_id, owner_id, make_project_administrator_headers(admin_id))
    )


def mark_ready(attempt_id, owner_id):
    return get_success_data(
        api_client.mark_ready(attempt_id, make_documentation_specialist_headers(owner_id))
    )


def drive_attempt_ready(attempt_id, owner_id, admin_id):
    """SELECTED -> DOCUMENTATION_IN_PROGRESS -> READY_FOR_SUBMITTAL."""
    assign_owner(attempt_id, owner_id, admin_id)
    return mark_ready(attempt_id, owner_id)


def lock_strategy(project_id, admin_id):
    """Lock the credit strategy; OCC-guarded, so the project version is re-read
    immediately before the call (PRD §2.5)."""
    version = get_project(project_id)["version"]
    return get_success_data(
        api_client.lock_strategy(
            project_id, version, make_project_administrator_headers(admin_id))
    )


def submit_phase(project_id, phase, admin_id):
    return get_success_data(
        api_client.submit_phase(
            project_id, phase, make_project_administrator_headers(admin_id))
    )


def withdraw_phase(project_id, phase, admin_id):
    return get_success_data(
        api_client.withdraw_phase(
            project_id, phase, make_project_administrator_headers(admin_id))
    )


def begin_review(attempt_id):
    return get_success_data(api_client.begin_review(attempt_id, REVIEWER))


def award_attempt(attempt_id, raw=None):
    return get_success_data(
        api_client.award_attempt(attempt_id, REVIEWER, raw_points_earned=raw)
    )


def deny_attempt(attempt_id, reason="credit requirements not demonstrated"):
    return get_success_data(api_client.deny_attempt(attempt_id, REVIEWER, reason=reason))


def post_comment(attempt_id, severity="CLARIFICATION", comment_text="please clarify"):
    return get_success_data(
        api_client.create_review_comment(
            create_review_comment_payload(
                attempt_id, severity=severity, comment_text=comment_text),
            REVIEWER)
    )


def create_cx_task(project_id, agent_id, admin_id, **overrides):
    return get_success_data(
        api_client.create_commissioning_task(
            create_commissioning_task_payload(project_id, agent_id, **overrides),
            make_project_administrator_headers(admin_id))
    )


def start_cx_task(task_id, agent_id):
    return get_success_data(
        api_client.start_commissioning_task(
            task_id, make_commissioning_agent_headers(agent_id))
    )


def complete_cx_task(task_id, agent_id, outcome="PASSED", result_notes=None):
    return get_success_data(
        api_client.complete_commissioning_task(
            task_id, outcome, make_commissioning_agent_headers(agent_id),
            result_notes=result_notes)
    )


def pass_prerequisite_cx_task(project_id, agent_id, admin_id, **overrides):
    """A prerequisite-linked commissioning task driven SCHEDULED -> PASSED."""
    overrides.setdefault("is_prerequisite_linked", True)
    task = create_cx_task(project_id, agent_id, admin_id, **overrides)
    start_cx_task(task["id"], agent_id)
    return complete_cx_task(task["id"], agent_id, outcome="PASSED")


def create_incentive_program(**overrides):
    return get_success_data(
        api_client.create_incentive_program(
            create_incentive_program_payload(**overrides), ADMIN)
    )


def apply_incentive(project_id, program_id, admin_id):
    return get_success_data(
        api_client.create_project_incentive(
            create_project_incentive_payload(project_id, program_id),
            make_project_administrator_headers(admin_id))
    )


def approve_incentive(project_incentive_id):
    return get_success_data(api_client.approve_project_incentive(project_incentive_id, ADMIN))


def create_analysis(project_id, admin_id, incremental_cost_cents=50000000):
    return get_success_data(
        api_client.create_cost_premium_analysis(
            create_cost_premium_analysis_payload(
                project_id,
                incremental_construction_cost_cents=incremental_cost_cents),
            make_project_administrator_headers(admin_id))
    )


def create_report(project_id, admin_id, **overrides):
    return get_success_data(
        api_client.create_performance_report(
            create_performance_report_payload(project_id, **overrides),
            make_project_administrator_headers(admin_id))
    )


def submit_report(report_id, admin_id):
    return get_success_data(
        api_client.submit_performance_report(
            report_id, make_project_administrator_headers(admin_id))
    )


def accept_report(report_id):
    return get_success_data(api_client.verify_performance_report(report_id, "ACCEPT", REVIEWER))


# ─── Tier 2: strategy assembly ────────────────────────

def _entry_kwargs(spec):
    return dict(
        credit_code=spec["code"],
        title=spec.get("title", f"Credit {spec['code']}"),
        category=spec.get("category", "ENERGY_ATMOSPHERE"),
        points_possible=spec["points"],
        is_prerequisite=spec.get("is_prerequisite", False),
        phase_eligibility=spec.get("phase_eligibility", "DESIGN"),
        requires_energy_model=spec.get("requires_energy_model", False),
    )


def setup_project_with_strategy(credit_specs, project_overrides=None, members=None):
    """Project + catalog entries + one attempt per spec, with the strategy locked.

    credit_specs: list of dicts with keys code, points, and optional
    is_prerequisite / phase_eligibility / requires_energy_model / phase
    (phase defaults to DESIGN).
    Returns dict(members, project, entries, attempts).
    """
    members = members or create_members()
    admin_id = members["admin"]["id"]
    spec_id = members["spec"]["id"]
    entries = {s["code"]: create_credit_entry(**_entry_kwargs(s)) for s in credit_specs}
    project = create_project(admin_id, **(project_overrides or {}))
    attempts = {}
    for s in credit_specs:
        attempts[s["code"]] = create_attempt(
            project["id"], entries[s["code"]]["id"], spec_id, admin_id,
            phase=s.get("phase", "DESIGN"))
    project = lock_strategy(project["id"], admin_id)
    return {"members": members, "project": project, "entries": entries,
            "attempts": attempts}


def setup_submitted_design_package(credit_specs, project_overrides=None,
                                   ready_codes=None, members=None):
    """Strategy locked; the named attempts (default: every DESIGN-phase spec)
    driven to READY_FOR_SUBMITTAL and the DESIGN package submitted."""
    ctx = setup_project_with_strategy(credit_specs, project_overrides, members)
    admin_id = ctx["members"]["admin"]["id"]
    spec_id = ctx["members"]["spec"]["id"]
    if ready_codes is None:
        ready_codes = [s["code"] for s in credit_specs if s.get("phase", "DESIGN") == "DESIGN"]
    for code in ready_codes:
        ctx["attempts"][code] = drive_attempt_ready(
            ctx["attempts"][code]["id"], spec_id, admin_id)
    ctx["project"] = submit_phase(ctx["project"]["id"], "DESIGN", admin_id)
    return ctx


def setup_attempt_under_review(credit_specs, project_overrides=None,
                               review_code=None, ready_codes=None, members=None):
    """DESIGN package submitted; the named attempt (default: first DESIGN spec)
    moved SUBMITTED -> UNDER_REVIEW by the reviewer. `ready_codes` limits which
    attempts are driven ready and included in the package."""
    ctx = setup_submitted_design_package(
        credit_specs, project_overrides, ready_codes=ready_codes, members=members)
    if review_code is None:
        review_code = next(
            s["code"] for s in credit_specs if s.get("phase", "DESIGN") == "DESIGN")
    ctx["attempts"][review_code] = begin_review(ctx["attempts"][review_code]["id"])
    ctx["review_code"] = review_code
    return ctx


# ─── Tier 3: model-pinning scenarios ──────────────────

def setup_model_pinned_ready_attempt(project_overrides=None):
    """PRESCRIPTIVE project with LOCKED BASELINE + LOCKED PROPOSED models and a
    requires-energy-model attempt pinned to the proposed model at
    READY_FOR_SUBMITTAL. Strategy is never locked (not required for mark-ready).
    Returns dict(members, project, entries, attempt, baseline, proposed)."""
    members = create_members()
    admin_id = members["admin"]["id"]
    spec_id = members["spec"]["id"]
    modeler_id = members["modeler"]["id"]
    entry = create_credit_entry(
        credit_code="EAc1", title="Optimize Energy Performance",
        category="ENERGY_ATMOSPHERE", points_possible=10,
        is_prerequisite=False, phase_eligibility="DESIGN", requires_energy_model=True)
    project = create_project(admin_id, **(project_overrides or {}))
    baseline, proposed = create_locked_models(project["id"], modeler_id)
    attempt = create_attempt(project["id"], entry["id"], spec_id, admin_id, phase="DESIGN")
    attempt = drive_attempt_ready(attempt["id"], spec_id, admin_id)
    return {"members": members, "project": get_project(project["id"]),
            "entry": entry, "attempt": attempt,
            "baseline": baseline, "proposed": proposed}


# ─── Tier 4/5: full certification spine ───────────────

def setup_certified_project(design_credits=None, construction_credits=None,
                            project_overrides=None, with_models=False,
                            baseline_cost=12000000, proposed_modeled=11400000,
                            proposed_confirmed=11400000, includes_unconfirmed=False,
                            with_commissioning=True, certify=True,
                            certify_clock="2027-01-01T00:00:00Z"):
    """Full lifecycle: roster, catalog, project, optional locked models, credit
    strategy locked, DESIGN package reviewed to completion, prerequisite
    commissioning PASSED, CONSTRUCTION package reviewed to completion, and —
    when certify is true — the CERTIFY decision issued at certify_clock.

    Credit specs: dicts with code, points, and optional is_prerequisite /
    phase_eligibility / requires_energy_model / category plus either
    award=<raw points> or deny=True for the review outcome.
    """
    if design_credits is None:
        design_credits = [{
            "code": "EAp1", "points": 40, "is_prerequisite": True,
            "phase_eligibility": "BOTH", "award": 40,
        }]
    if construction_credits is None:
        construction_credits = [{
            "code": "MRc1", "points": 10, "category": "MATERIALS",
            "phase_eligibility": "CONSTRUCTION", "award": 0,
        }]
    specs = ([{**s, "phase": "DESIGN"} for s in design_credits]
             + [{**s, "phase": "CONSTRUCTION",
                 "phase_eligibility": s.get("phase_eligibility", "CONSTRUCTION")}
                for s in construction_credits])

    members = create_members()
    admin_id = members["admin"]["id"]
    spec_id = members["spec"]["id"]
    modeler_id = members["modeler"]["id"]
    cx_id = members["cx"]["id"]

    entries = {s["code"]: create_credit_entry(**_entry_kwargs(s)) for s in specs}
    project = create_project(admin_id, **(project_overrides or {}))
    pid = project["id"]

    baseline = proposed = None
    if with_models:
        baseline, proposed = create_locked_models(
            pid, modeler_id, baseline_cost=baseline_cost,
            proposed_modeled=proposed_modeled, proposed_confirmed=proposed_confirmed,
            includes_unconfirmed=includes_unconfirmed)

    attempts = {}
    for s in specs:
        attempts[s["code"]] = create_attempt(
            pid, entries[s["code"]]["id"], spec_id, admin_id, phase=s["phase"])
    project = lock_strategy(pid, admin_id)

    for s in design_credits:
        attempts[s["code"]] = drive_attempt_ready(attempts[s["code"]]["id"], spec_id, admin_id)
    project = submit_phase(pid, "DESIGN", admin_id)
    for s in design_credits:
        a = begin_review(attempts[s["code"]]["id"])
        if s.get("deny"):
            a = deny_attempt(a["id"])
        else:
            a = award_attempt(a["id"], raw=s.get("award"))
        attempts[s["code"]] = a

    task = None
    if with_commissioning:
        task = pass_prerequisite_cx_task(pid, cx_id, admin_id)

    for s in construction_credits:
        attempts[s["code"]] = drive_attempt_ready(attempts[s["code"]]["id"], spec_id, admin_id)
    project = submit_phase(pid, "CONSTRUCTION", admin_id)
    for s in construction_credits:
        a = begin_review(attempts[s["code"]]["id"])
        if s.get("deny"):
            a = deny_attempt(a["id"])
        else:
            a = award_attempt(a["id"], raw=s.get("award"))
        attempts[s["code"]] = a

    project = get_project(pid)
    if certify:
        if certify_clock:
            set_clock(certify_clock)
        project = get_success_data(api_client.issue_decision(pid, "CERTIFY", REVIEWER))

    return {"members": members, "entries": entries, "project": project,
            "attempts": attempts, "baseline": baseline, "proposed": proposed,
            "task": task}


def setup_certified_project_with_report(actual=12000000,
                                        period_start="2027-01-01T00:00:00Z",
                                        period_end="2027-12-31T00:00:00Z",
                                        submit=True, accept=True, **spine_kwargs):
    """A CERTIFIED project (locked models included) plus one performance report,
    optionally submitted and accepted."""
    spine_kwargs.setdefault("with_models", True)
    ctx = setup_certified_project(**spine_kwargs)
    admin_id = ctx["members"]["admin"]["id"]
    report = create_report(
        ctx["project"]["id"], admin_id,
        period_start=period_start, period_end=period_end,
        actual_annual_energy_cost_cents=actual)
    if submit:
        report = submit_report(report["id"], admin_id)
    if accept:
        report = accept_report(report["id"])
    ctx["report"] = report
    ctx["project"] = get_project(ctx["project"]["id"])
    return ctx
