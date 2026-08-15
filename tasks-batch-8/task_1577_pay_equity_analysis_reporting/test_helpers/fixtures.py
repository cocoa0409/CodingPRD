"""Composite setup helpers for multi-step test prerequisites.

Setup calls use get_success_data() (lenient) so a broken precondition raises a
clear "Setup step failed" error instead of a confusing assertion failure.

The canonical deep-lifecycle chains built here:
  setup_analyzed_study       study DRAFT -> members -> group -> assign -> advance
                             -> lock -> model run -> finalize (group ANALYZED)
  setup_privileged_final_study  + submit-legal-review + legal APPROVE
  setup_remediation_open     + open-remediation + plan + TARGETED finding
  setup_monitoring_study     + adjustments approved + clock sweep -> MONITORING
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .factories import (
    create_adjustment_payload,
    create_filing_payload,
    create_group_payload,
    create_jurisdiction_rule_payload,
    create_model_run_payload,
    create_monitoring_cycle_payload,
    create_pipeline_analysis_payload,
    create_plan_payload,
    create_posting_payload,
    create_snapshot_payload,
    create_study_payload,
)
from .test_users import (
    TEST_USERS,
    make_comp_analyst_headers,
    make_remediation_approver_headers,
)

ANALYST = TEST_USERS["comp_analyst_headers"]
COUNSEL = TEST_USERS["legal_counsel_headers"]
APPROVER = TEST_USERS["remediation_approver_headers"]
PEOPLE_OPS = TEST_USERS["people_ops_admin_headers"]
REPORTER = TEST_USERS["compliance_reporter_headers"]
PLATFORM = TEST_USERS["platform_admin_headers"]

DEFAULT_PROPOSER_ID = "user-analyst-1"
DEFAULT_APPROVER_ID = "user-approver-1"


# ─── Member spec shorthand ───────────────────────────────────────────────────

def member_spec(ref, gender_class="MALE", base_salary_cents=10000000, job_level=5,
                job_family="ENG", location_code="CA", fte_factor=1.0,
                age_band="UNDER_40", ethnicity_class="WHITE", hire_date="2020-01-01"):
    return {
        "employee_ref": ref,
        "gender_class": gender_class,
        "ethnicity_class": ethnicity_class,
        "age_band": age_band,
        "job_family": job_family,
        "job_level": job_level,
        "location_code": location_code,
        "fte_factor": fte_factor,
        "base_salary_cents": base_salary_cents,
        "bonus_cents": 0,
        "hire_date": hire_date,
    }


def six_fin_member_specs():
    """FIN/NY level 5: MALE 11000000/10000000/9000000, FEMALE 9500000/9000000/8500000.

    Under COHORT_MEDIAN this membership yields adjusted_gap_pct 10.0000 with
    p_value 0.0323 for GENDER:FEMALE (actionable under default thresholds).
    """
    return [
        member_spec("M1", "MALE", 11000000, 5, "FIN", "NY"),
        member_spec("M2", "MALE", 10000000, 5, "FIN", "NY"),
        member_spec("M3", "MALE", 9000000, 5, "FIN", "NY"),
        member_spec("F1", "FEMALE", 9500000, 5, "FIN", "NY"),
        member_spec("F2", "FEMALE", 9000000, 5, "FIN", "NY"),
        member_spec("F3", "FEMALE", 8500000, 5, "FIN", "NY"),
    ]


def two_eng_member_specs():
    """ENG/CA level 5: MALE 10000000, FEMALE 9000000.

    Under COHORT_MEDIAN this yields adjusted_gap_pct 10.0000 with
    p_value 0.0909 for GENDER:FEMALE — actionable only when the study's
    significance_threshold is raised (e.g. to 0.1).
    """
    return [
        member_spec("M1", "MALE", 10000000, 5, "ENG", "CA"),
        member_spec("F1", "FEMALE", 9000000, 5, "ENG", "CA"),
    ]


def seven_eng_member_specs():
    """ENG/CA levels 4-6: 4 MALE level 6 (12/11/10/9M), 3 FEMALE level 4 (10/9.5/9M).

    COHORT_MEDIAN yields gap 9.5238 / p 0.0338; REGRESSION_OLS yields
    gap 3.0612 / p 0.0982 on the identical membership.
    """
    return [
        member_spec("M1", "MALE", 12000000, 6, "ENG", "CA"),
        member_spec("M2", "MALE", 11000000, 6, "ENG", "CA"),
        member_spec("M3", "MALE", 10000000, 6, "ENG", "CA"),
        member_spec("M4", "MALE", 9000000, 6, "ENG", "CA"),
        member_spec("F1", "FEMALE", 10000000, 4, "ENG", "CA"),
        member_spec("F2", "FEMALE", 9500000, 4, "ENG", "CA"),
        member_spec("F3", "FEMALE", 9000000, 4, "ENG", "CA"),
    ]


def four_two_dim_member_specs():
    """ENG/CA level 5: MALE/UNDER_40 10M, MALE/FORTY_PLUS 11M,
    FEMALE/UNDER_40 9M, FEMALE/FORTY_PLUS 9.5M (drives GENDER + AGE_BAND)."""
    return [
        member_spec("M1", "MALE", 10000000, 5, "ENG", "CA", age_band="UNDER_40",
                    hire_date="2020-01-01"),
        member_spec("M2", "MALE", 11000000, 5, "ENG", "CA", age_band="FORTY_PLUS",
                    hire_date="2015-01-01"),
        member_spec("F1", "FEMALE", 9000000, 5, "ENG", "CA", age_band="UNDER_40",
                    hire_date="2020-01-01"),
        member_spec("F2", "FEMALE", 9500000, 5, "ENG", "CA", age_band="FORTY_PLUS",
                    hire_date="2015-01-01"),
    ]


# ─── Primitive happy-path helpers (each raises AssertionError on failure) ────

def create_study(name="Study", analysis_period_start="2024-01-01",
                 analysis_period_end="2024-12-31", protected_classes=("GENDER",),
                 significance_threshold=None, actionable_gap_pct=None,
                 min_group_size=None, monitor_cadence_days=None):
    """Create a study in DRAFT. Returns the study."""
    overrides = {}
    if significance_threshold is not None:
        overrides["significance_threshold"] = significance_threshold
    if actionable_gap_pct is not None:
        overrides["actionable_gap_pct"] = actionable_gap_pct
    if min_group_size is not None:
        overrides["min_group_size"] = min_group_size
    if monitor_cadence_days is not None:
        overrides["monitor_cadence_days"] = monitor_cadence_days
    payload = create_study_payload(
        name=name,
        analysis_period_start=analysis_period_start,
        analysis_period_end=analysis_period_end,
        protected_classes=list(protected_classes),
        **overrides,
    )
    return get_success_data(api_client.create_study(payload, ANALYST))


def add_snapshot(study_id, spec):
    """Add one employee snapshot to a DRAFT study. Returns the snapshot."""
    payload = create_snapshot_payload(study_id, **spec)
    return get_success_data(api_client.create_snapshot(payload, PEOPLE_OPS))


def add_snapshots(study_id, specs):
    return [add_snapshot(study_id, spec) for spec in specs]


def create_group(study_id, name="G1", job_family="ENG", min_job_level=5,
                 max_job_level=5, location_code="CA"):
    """Create a comparator group in DRAFT. Returns the group."""
    payload = create_group_payload(
        study_id, name=name, job_family=job_family,
        min_job_level=min_job_level, max_job_level=max_job_level,
        location_code=location_code,
    )
    return get_success_data(api_client.create_group(payload, ANALYST))


def assign_snapshot(snapshot_id, group_id):
    """PATCH a snapshot into a group. Returns the updated snapshot."""
    return get_success_data(
        api_client.patch_snapshot(snapshot_id, {"comparator_group_id": group_id}, PEOPLE_OPS)
    )


def unassign_snapshot(snapshot_id):
    """PATCH a snapshot's comparator_group_id to null. Returns the snapshot."""
    return get_success_data(
        api_client.patch_snapshot(snapshot_id, {"comparator_group_id": None}, PEOPLE_OPS)
    )


def get_group(group_id):
    return get_success_data(api_client.get_group(group_id, ANALYST))


def get_study(study_id):
    return get_success_data(api_client.get_study(study_id, ANALYST))


def get_plan(plan_id):
    return get_success_data(api_client.get_plan(plan_id, ANALYST))


def get_finding(finding_id):
    return get_success_data(api_client.get_finding(finding_id, ANALYST))


def get_adjustment(adjustment_id):
    return get_success_data(api_client.get_adjustment(adjustment_id, ANALYST))


def advance_study(study_id):
    """DRAFT -> MODELING. Returns the study."""
    return get_success_data(api_client.advance_study(study_id, ANALYST))


def lock_group(group_id):
    """DRAFT -> LOCKED. Returns the locked group (fresh version)."""
    return get_success_data(api_client.lock_group(group_id, ANALYST))


def create_run(group_id, methodology="COHORT_MEDIAN", expected_group_version=None):
    """Create a PROVISIONAL run. When expected_group_version is None the group's
    current version is re-read first (fresh-token happy path)."""
    if expected_group_version is None:
        expected_group_version = get_group(group_id)["version"]
    payload = create_model_run_payload(
        group_id, expected_group_version, methodology=methodology
    )
    return get_success_data(api_client.create_model_run(payload, ANALYST))


def finalize_run(run_id):
    """PROVISIONAL -> FINAL. Returns the finalized run."""
    return get_success_data(api_client.finalize_run(run_id, ANALYST))


def submit_legal_review(study_id):
    """MODELING -> UNDER_LEGAL_REVIEW. Returns the study."""
    return get_success_data(api_client.submit_legal_review(study_id, ANALYST))


def legal_approve(study_id):
    """UNDER_LEGAL_REVIEW -> PRIVILEGED_FINAL. Returns the study."""
    return get_success_data(
        api_client.legal_decision(study_id, {"decision": "APPROVE"}, COUNSEL)
    )


def legal_request_changes(study_id, rationale="Rework required"):
    """UNDER_LEGAL_REVIEW -> DRAFT. Returns the study."""
    return get_success_data(
        api_client.legal_decision(
            study_id, {"decision": "REQUEST_CHANGES", "rationale": rationale}, COUNSEL
        )
    )


def open_remediation(study_id):
    """PRIVILEGED_FINAL -> REMEDIATION_OPEN. Returns the study."""
    return get_success_data(api_client.open_remediation(study_id, COUNSEL))


def list_study_findings(study_id):
    data, _meta = validate_paginated(api_client.list_findings(ANALYST, {"study_id": study_id}))
    return data


def list_run_findings(run_id):
    data, _meta = validate_paginated(
        api_client.list_findings(ANALYST, {"model_run_id": run_id})
    )
    return data


def disposition_finding(finding_id, disposition, rationale=None):
    payload = {"disposition": disposition}
    if rationale is not None:
        payload["disposition_rationale"] = rationale
    return get_success_data(api_client.disposition_finding(finding_id, payload, ANALYST))


def create_plan(study_id, total_budget_cents=2700000, allocation_strategy=None):
    """Create a DRAFT remediation plan. Returns the plan."""
    overrides = {}
    if allocation_strategy is not None:
        overrides["allocation_strategy"] = allocation_strategy
    payload = create_plan_payload(
        study_id, total_budget_cents=total_budget_cents, **overrides
    )
    return get_success_data(api_client.create_plan(payload, ANALYST))


def propose_adjustment(plan_id, finding_id, snapshot_id, proposed_increase_cents,
                       effective_date="2026-09-01", proposer_user_id=DEFAULT_PROPOSER_ID):
    """Create a PROPOSED adjustment. Returns the adjustment."""
    payload = create_adjustment_payload(
        plan_id, finding_id, snapshot_id,
        proposed_increase_cents=proposed_increase_cents,
        effective_date=effective_date,
    )
    return get_success_data(
        api_client.create_adjustment(
            payload, make_comp_analyst_headers(proposer_user_id)
        )
    )


def submit_plan(plan_id):
    """DRAFT -> SUBMITTED. Returns the plan."""
    return get_success_data(api_client.submit_plan(plan_id, ANALYST))


def decide_plan(plan_id, decision, rationale=None):
    """Committee decision on a SUBMITTED plan. Returns the plan."""
    payload = {"decision": decision}
    if rationale is not None:
        payload["rationale"] = rationale
    return get_success_data(api_client.decide_plan(plan_id, payload, APPROVER))


def approve_adjustment(adjustment_id, plan_id, approver_user_id=DEFAULT_APPROVER_ID):
    """Approve a PROPOSED adjustment, re-reading the plan version for the OCC
    token. Returns the decided adjustment."""
    plan = get_plan(plan_id)
    return get_success_data(
        api_client.decide_adjustment(
            adjustment_id,
            {"decision": "APPROVE", "expected_plan_version": plan["version"]},
            make_remediation_approver_headers(approver_user_id),
        )
    )


def sweep_clock(to_iso8601):
    """Set the logical clock, running the scheduled-transition sweep."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, PLATFORM)
    )


def create_jurisdiction(jurisdiction_code="CA", **overrides):
    payload = create_jurisdiction_rule_payload(
        jurisdiction_code=jurisdiction_code, **overrides
    )
    return get_success_data(api_client.create_jurisdiction_rule(payload, PEOPLE_OPS))


def create_posting(jurisdiction_rule_id, job_posting_ref="POST-1", **overrides):
    payload = create_posting_payload(
        jurisdiction_rule_id, job_posting_ref=job_posting_ref, **overrides
    )
    return get_success_data(api_client.create_posting(payload, REPORTER))


def create_filing(study_id, **overrides):
    payload = create_filing_payload(study_id, **overrides)
    return get_success_data(api_client.create_filing(payload, REPORTER))


def create_pipeline_analysis(study_id, **overrides):
    payload = create_pipeline_analysis_payload(study_id, **overrides)
    return get_success_data(api_client.create_pipeline_analysis(payload, ANALYST))


def create_cycle(study_id, **overrides):
    payload = create_monitoring_cycle_payload(study_id, **overrides)
    return get_success_data(api_client.create_monitoring_cycle(payload, ANALYST))


# ─── Tier 1/2: analyzed-study composite ──────────────────────────────────────

def setup_provisional_run_scenario(name="Study", analysis_period_start="2024-01-01",
                                   analysis_period_end="2024-12-31",
                                   protected_classes=("GENDER",), member_specs=None,
                                   group_name="G1", job_family=None, min_job_level=5,
                                   max_job_level=5, location_code=None,
                                   min_group_size=None, significance_threshold=None,
                                   actionable_gap_pct=None, methodology="COHORT_MEDIAN"):
    """Study DRAFT -> snapshots -> group -> assign -> advance -> lock ->
    create run. Returns a context dict; study is MODELING, group is LOCKED,
    run is PROVISIONAL (not yet finalized)."""
    if member_specs is None:
        member_specs = six_fin_member_specs()
    if job_family is None:
        job_family = member_specs[0]["job_family"]
    if location_code is None:
        location_code = member_specs[0]["location_code"]
    if min_group_size is None:
        min_group_size = len(member_specs)

    study = create_study(
        name=name,
        analysis_period_start=analysis_period_start,
        analysis_period_end=analysis_period_end,
        protected_classes=protected_classes,
        significance_threshold=significance_threshold,
        actionable_gap_pct=actionable_gap_pct,
        min_group_size=min_group_size,
    )
    members = add_snapshots(study["id"], member_specs)
    group = create_group(
        study["id"], name=group_name, job_family=job_family,
        min_job_level=min_job_level, max_job_level=max_job_level,
        location_code=location_code,
    )
    for member in members:
        assign_snapshot(member["id"], group["id"])
    advance_study(study["id"])
    lock_group(group["id"])
    run = create_run(group["id"], methodology=methodology)
    return {
        "study": get_study(study["id"]),
        "group": get_group(group["id"]),
        "run": run,
        "members": members,
        "findings": [],
    }


def setup_analyzed_study(**kwargs):
    """setup_provisional_run_scenario + finalize. Study is MODELING, group is
    ANALYZED, run is FINAL, findings are generated (FLAGGED)."""
    ctx = setup_provisional_run_scenario(**kwargs)
    ctx["run"] = finalize_run(ctx["run"]["id"])
    ctx["group"] = get_group(ctx["group"]["id"])
    ctx["findings"] = list_run_findings(ctx["run"]["id"])
    ctx["study"] = get_study(ctx["study"]["id"])
    return ctx


def setup_privileged_final_study(**kwargs):
    """setup_analyzed_study + submit-legal-review + legal APPROVE.
    Study is PRIVILEGED_FINAL with privileged_model_run_ids pinned."""
    ctx = setup_analyzed_study(**kwargs)
    submit_legal_review(ctx["study"]["id"])
    study = legal_approve(ctx["study"]["id"])
    ctx["study"] = study
    return ctx


def setup_remediation_open(budget=2700000, allocation_strategy=None,
                           target_finding=True, **kwargs):
    """setup_privileged_final_study + open-remediation + plan; optionally the
    study's first finding is dispositioned TARGETED. Study is REMEDIATION_OPEN."""
    ctx = setup_privileged_final_study(**kwargs)
    open_remediation(ctx["study"]["id"])
    plan = create_plan(
        ctx["study"]["id"], total_budget_cents=budget,
        allocation_strategy=allocation_strategy,
    )
    ctx["plan"] = plan
    ctx["study"] = get_study(ctx["study"]["id"])
    finding = ctx["findings"][0]
    if target_finding:
        finding = disposition_finding(finding["id"], "TARGETED")
    ctx["finding"] = finding
    return ctx


def add_proposed_adjustments(ctx, adjustment_specs, proposer_user_id=DEFAULT_PROPOSER_ID,
                             effective_date="2026-09-01"):
    """Propose one adjustment per (member_index, cents) spec against the
    context's TARGETED finding. Returns the created adjustments."""
    adjustments = []
    for member_index, cents in adjustment_specs:
        adjustments.append(
            propose_adjustment(
                ctx["plan"]["id"], ctx["finding"]["id"],
                ctx["members"][member_index]["id"], cents,
                effective_date=effective_date,
                proposer_user_id=proposer_user_id,
            )
        )
    ctx["adjustments"] = adjustments
    return adjustments


def submit_and_approve_plan(ctx):
    """Plan DRAFT -> SUBMITTED -> APPROVED."""
    submit_plan(ctx["plan"]["id"])
    ctx["plan"] = decide_plan(ctx["plan"]["id"], "APPROVE")
    return ctx["plan"]


def approve_all_adjustments(ctx, approver_user_id=DEFAULT_APPROVER_ID):
    """Approve every adjustment in ctx['adjustments'] (re-reading the plan
    version before each decision). Returns the decided adjustments."""
    decided = []
    for adjustment in ctx["adjustments"]:
        decided.append(
            approve_adjustment(adjustment["id"], ctx["plan"]["id"], approver_user_id)
        )
    ctx["adjustments"] = decided
    ctx["plan"] = get_plan(ctx["plan"]["id"])
    return decided


def setup_monitoring_study(adjustment_specs=((3, 950000), (4, 900000), (5, 850000)),
                           effective_date="2026-09-01",
                           clock_to="2026-09-01T00:00:00Z", **kwargs):
    """Full remediation cascade: remediation-open study + adjustments proposed
    and approved + clock swept to the effective date. The adjustments flip
    EFFECTIVE, the finding resolves, the plan completes, and the study
    auto-transitions to MONITORING. Returns the context dict."""
    ctx = setup_remediation_open(**kwargs)
    add_proposed_adjustments(ctx, adjustment_specs, effective_date=effective_date)
    submit_and_approve_plan(ctx)
    approve_all_adjustments(ctx)
    sweep_clock(clock_to)
    ctx["study"] = get_study(ctx["study"]["id"])
    ctx["plan"] = get_plan(ctx["plan"]["id"])
    ctx["finding"] = get_finding(ctx["finding"]["id"])
    ctx["adjustments"] = [get_adjustment(a["id"]) for a in ctx["adjustments"]]
    return ctx
