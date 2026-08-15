"""Composite setup helpers.

Every helper builds preconditions from scratch through PRD-declared endpoints
(the harness restarts the server before each test, so nothing is shared).
Setup calls use get_success_data() so a setup failure surfaces a clear
"Setup failed" message rather than a confusing assertion error.

Identity threading: BusinessOwner is entity-backed, so every ownership-gated
call uses make_business_owner_headers(owner["id"]).
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    DEFAULT_DUE_DATE,
    DEFAULT_PLAN_TARGET,
    DEFAULT_POLICY_EFFECTIVE,
)
from .factories import (
    create_assessment_payload,
    create_business_owner_payload,
    create_change_payload,
    create_control_payload,
    create_mapping_payload,
    create_obligation_payload,
    create_plan_payload,
    create_policy_update_payload,
    submit_assessment_payload,
)
from .test_users import (
    ADMIN_1,
    MANAGER_1,
    OFFICER_A,
    OFFICER_B,
    SECRETARY_1,
    make_admin_headers,
    make_business_owner_headers,
    make_manager_headers,
    make_officer_headers,
    make_secretary_headers,
)


def _fail(step: str, response):
    raise AssertionError(f"Setup failed at {step}: {response.status_code} {response.text}")


def create_business_owner(**overrides) -> dict:
    """Register a business owner. Returns the owner entity."""
    resp = api_client.create_business_owner(
        create_business_owner_payload(**overrides), make_officer_headers(OFFICER_A)
    )
    if resp.status_code != 201:
        _fail("create_business_owner", resp)
    return get_success_data(resp)


def create_change(creator=OFFICER_A, **overrides) -> dict:
    """Ingest a regulatory change (PENDING_TRIAGE). Returns the change."""
    resp = api_client.create_regulatory_change(
        create_change_payload(**overrides), make_officer_headers(creator)
    )
    if resp.status_code != 201:
        _fail("create_change", resp)
    return get_success_data(resp)


def triage_change(change_id, verdict="APPLICABLE", rationale="Covers our business", actor=OFFICER_B) -> dict:
    """Triage a pending change. Actor defaults to a peer officer (SoD)."""
    resp = api_client.triage_regulatory_change(
        change_id, {"verdict": verdict, "rationale": rationale}, make_officer_headers(actor)
    )
    if resp.status_code != 200:
        _fail("triage_change", resp)
    return get_success_data(resp)


def create_triaged_change(creator=OFFICER_A, triager=OFFICER_B, verdict="APPLICABLE", **overrides) -> dict:
    """Change created by `creator` and triaged by `triager`. Returns the triaged change."""
    change = create_change(creator=creator, **overrides)
    return triage_change(change["id"], verdict=verdict, actor=triager)


def create_obligation(change_id, activate=True, **overrides) -> dict:
    """Create an obligation for a TRIAGED_APPLICABLE change; optionally activate."""
    payload = create_obligation_payload(regulatory_change_id=change_id, **overrides)
    resp = api_client.create_obligation(payload, make_officer_headers(OFFICER_A))
    if resp.status_code != 201:
        _fail("create_obligation", resp)
    obligation = get_success_data(resp)
    if activate:
        resp = api_client.activate_obligation(obligation["id"], make_officer_headers(OFFICER_A))
        if resp.status_code != 200:
            _fail("activate_obligation", resp)
        obligation = get_success_data(resp)
    return obligation


def create_control(**overrides) -> dict:
    """Create a control (born ACTIVE). Returns the control."""
    resp = api_client.create_control(create_control_payload(**overrides), make_officer_headers(OFFICER_A))
    if resp.status_code != 201:
        _fail("create_control", resp)
    return get_success_data(resp)


def create_mapping(obligation_id, control_id, coverage_weight=3, creator=OFFICER_A) -> dict:
    """Propose a mapping (PROPOSED). Returns the mapping."""
    resp = api_client.create_mapping(
        create_mapping_payload(
            obligation_id=obligation_id, control_id=control_id, coverage_weight=coverage_weight
        ),
        make_officer_headers(creator),
    )
    if resp.status_code != 201:
        _fail("create_mapping", resp)
    return get_success_data(resp)


def create_approved_mapping(obligation_id, control_id, coverage_weight=3, creator=OFFICER_A, approver=OFFICER_B) -> dict:
    """Propose + approve a mapping (approver differs from creator per SoD)."""
    mapping = create_mapping(obligation_id, control_id, coverage_weight, creator=creator)
    resp = api_client.approve_mapping(mapping["id"], make_officer_headers(approver))
    if resp.status_code != 200:
        _fail("approve_mapping", resp)
    return get_success_data(resp)


def create_assessment(change, owner_id, due_date=DEFAULT_DUE_DATE, expected_version=None) -> dict:
    """Assign an impact assessment. `change` is the triaged change entity; its
    version supplies the OCC pin unless expected_version is given."""
    version = expected_version if expected_version is not None else change["version"]
    resp = api_client.create_impact_assessment(
        create_assessment_payload(
            regulatory_change_id=change["id"],
            business_owner_id=owner_id,
            due_date=due_date,
            expected_regulatory_change_version=version,
        ),
        make_officer_headers(OFFICER_A),
    )
    if resp.status_code != 201:
        _fail("create_assessment", resp)
    return get_success_data(resp)


def start_assessment(assessment_id, owner_id) -> dict:
    resp = api_client.start_impact_assessment(assessment_id, make_business_owner_headers(owner_id))
    if resp.status_code != 200:
        _fail("start_assessment", resp)
    return get_success_data(resp)


def submit_assessment(assessment_id, owner_id, **scoring) -> dict:
    resp = api_client.submit_impact_assessment(
        assessment_id, submit_assessment_payload(**scoring), make_business_owner_headers(owner_id)
    )
    if resp.status_code != 200:
        _fail("submit_assessment", resp)
    return get_success_data(resp)


def accept_assessment(assessment_id, manager=MANAGER_1) -> dict:
    resp = api_client.accept_impact_assessment(assessment_id, make_manager_headers(manager))
    if resp.status_code != 200:
        _fail("accept_assessment", resp)
    return get_success_data(resp)


def list_gaps_for_assessment(assessment_id) -> list:
    resp = api_client.list_gap_analyses(
        make_officer_headers(OFFICER_A), params={"impact_assessment_id": assessment_id}
    )
    if resp.status_code != 200:
        _fail("list_gaps_for_assessment", resp)
    data, _meta = validate_paginated(resp)
    return data


def list_gaps_for_obligation(obligation_id) -> list:
    resp = api_client.list_gap_analyses(
        make_officer_headers(OFFICER_A), params={"obligation_id": obligation_id}
    )
    if resp.status_code != 200:
        _fail("list_gaps_for_obligation", resp)
    data, _meta = validate_paginated(resp)
    return data


def get_gap(gap_id) -> dict:
    resp = api_client.get_gap_analysis(gap_id, make_officer_headers(OFFICER_A))
    if resp.status_code != 200:
        _fail("get_gap", resp)
    return get_success_data(resp)


def confirm_gap(gap_id) -> dict:
    resp = api_client.begin_review_gap_analysis(gap_id, make_officer_headers(OFFICER_A))
    if resp.status_code != 200:
        _fail("begin_review_gap", resp)
    resp = api_client.confirm_gap_analysis(gap_id, make_officer_headers(OFFICER_A))
    if resp.status_code != 200:
        _fail("confirm_gap", resp)
    return get_success_data(resp)


def setup_accepted_assessment(
    citation="RCM-1",
    criticality="CRITICAL",
    severity_hint="CRITICAL",
    obligation=True,
    due_date=DEFAULT_DUE_DATE,
    likelihood=3,
    severity=3,
    lines=1,
) -> dict:
    """Owner + TRIAGED_APPLICABLE change (+ one ACTIVE obligation) + assessment
    started, submitted, and accepted. Returns dict of all entities plus gaps."""
    owner = create_business_owner()
    change = create_triaged_change(citation=citation, severity_hint=severity_hint)
    obl = create_obligation(change["id"], criticality=criticality) if obligation else None
    assessment = create_assessment(change, owner["id"], due_date=due_date)
    start_assessment(assessment["id"], owner["id"])
    submitted = submit_assessment(
        assessment["id"], owner["id"],
        likelihood_score=likelihood, severity_score=severity, affected_business_lines=lines,
    )
    accepted = accept_assessment(assessment["id"])
    return {
        "owner": owner,
        "change": get_success_data(api_client.get_regulatory_change(change["id"], make_officer_headers(OFFICER_A))),
        "obligation": obl,
        "assessment": accepted,
        "submitted": submitted,
        "gaps": list_gaps_for_assessment(assessment["id"]),
    }


def setup_confirmed_gap(**kwargs) -> dict:
    """Accepted pipeline + first gap confirmed. Returns pipeline dict plus 'gap'."""
    pipe = setup_accepted_assessment(**kwargs)
    assert pipe["gaps"], "Setup failed: accept produced no gap analyses"
    gap = confirm_gap(pipe["gaps"][0]["id"])
    pipe["gap"] = gap
    return pipe


def create_plan(gap_id, owner_id, target=DEFAULT_PLAN_TARGET, title="Implementation plan") -> dict:
    resp = api_client.create_implementation_plan(
        create_plan_payload(gap_analysis_id=gap_id, title=title, target_completion_date=target),
        make_business_owner_headers(owner_id),
    )
    if resp.status_code != 201:
        _fail("create_plan", resp)
    return get_success_data(resp)


def setup_plan(target_status="APPROVED", target=DEFAULT_PLAN_TARGET, **kwargs) -> dict:
    """Confirmed gap + plan walked to the requested execution status.
    target_status in DRAFT | SUBMITTED | APPROVED | IN_EXECUTION | COMPLETED."""
    pipe = setup_confirmed_gap(**kwargs)
    owner_id = pipe["owner"]["id"]
    plan = create_plan(pipe["gap"]["id"], owner_id, target=target)
    pipe["plan"] = plan
    if target_status == "DRAFT":
        return pipe
    resp = api_client.submit_implementation_plan(plan["id"], make_business_owner_headers(owner_id))
    if resp.status_code != 200:
        _fail("submit_plan", resp)
    pipe["plan"] = get_success_data(resp)
    if target_status == "SUBMITTED":
        return pipe
    resp = api_client.approve_implementation_plan(plan["id"], make_manager_headers(MANAGER_1))
    if resp.status_code != 200:
        _fail("approve_plan", resp)
    pipe["plan"] = get_success_data(resp)
    if target_status == "APPROVED":
        return pipe
    resp = api_client.begin_execution_implementation_plan(plan["id"], make_business_owner_headers(owner_id))
    if resp.status_code != 200:
        _fail("begin_execution_plan", resp)
    pipe["plan"] = get_success_data(resp)
    if target_status == "IN_EXECUTION":
        return pipe
    resp = api_client.complete_implementation_plan(plan["id"], make_business_owner_headers(owner_id))
    if resp.status_code != 200:
        _fail("complete_plan", resp)
    pipe["plan"] = get_success_data(resp)
    return pipe


def setup_completed_plan_with_package(attach_artifact=False, **kwargs) -> dict:
    """Plan completed + evidence package opened (ASSEMBLING)."""
    pipe = setup_plan(target_status="COMPLETED", **kwargs)
    owner_id = pipe["owner"]["id"]
    resp = api_client.create_evidence_package(
        {"implementation_plan_id": pipe["plan"]["id"]}, make_business_owner_headers(owner_id)
    )
    if resp.status_code != 201:
        _fail("create_evidence_package", resp)
    pipe["package"] = get_success_data(resp)
    if attach_artifact:
        resp = api_client.attach_artifact(
            pipe["package"]["id"],
            {"artifact_type": "CONTROL_TEST", "uri": "s3://ev/control-test.pdf"},
            make_business_owner_headers(owner_id),
        )
        if resp.status_code != 201:
            _fail("attach_artifact", resp)
        pipe["package"] = get_success_data(resp)
    return pipe


def setup_published_policy(effective_date=DEFAULT_POLICY_EFFECTIVE, drafter=OFFICER_A, approver=MANAGER_1, **control_overrides) -> dict:
    """Control + policy update submitted, approved, published; rollout live.
    Returns dict with control (pre-approve snapshot), policy_update, rollout."""
    control = create_control(**control_overrides)
    resp = api_client.create_policy_update(
        create_policy_update_payload(control_id=control["id"], effective_date=effective_date),
        make_officer_headers(drafter),
    )
    if resp.status_code != 201:
        _fail("create_policy_update", resp)
    update = get_success_data(resp)
    resp = api_client.submit_policy_update(update["id"], make_officer_headers(drafter))
    if resp.status_code != 200:
        _fail("submit_policy_update", resp)
    resp = api_client.approve_policy_update(
        update["id"], {"expected_control_version": control["version"]}, make_manager_headers(approver)
    )
    if resp.status_code != 200:
        _fail("approve_policy_update", resp)
    update = get_success_data(resp)
    resp = api_client.publish_policy_update(update["id"], make_manager_headers(approver))
    if resp.status_code != 200:
        _fail("publish_policy_update", resp)
    update = get_success_data(resp)
    resp = api_client.list_training_rollouts(
        make_officer_headers(OFFICER_A), params={"policy_update_id": update["id"]}
    )
    if resp.status_code != 200:
        _fail("list_training_rollouts", resp)
    rollouts, _meta = validate_paginated(resp)
    assert len(rollouts) == 1, f"Setup failed: expected 1 rollout, got {len(rollouts)}"
    return {"control": control, "policy_update": update, "rollout": rollouts[0]}


def set_clock(to_iso8601: str) -> dict:
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, make_admin_headers(ADMIN_1))
    if resp.status_code != 200:
        _fail("set_clock", resp)
    return get_success_data(resp)


def get_owner(owner_id) -> dict:
    resp = api_client.get_business_owner(owner_id, make_officer_headers(OFFICER_A))
    if resp.status_code != 200:
        _fail("get_business_owner", resp)
    return get_success_data(resp)


def get_change(change_id) -> dict:
    resp = api_client.get_regulatory_change(change_id, make_officer_headers(OFFICER_A))
    if resp.status_code != 200:
        _fail("get_regulatory_change", resp)
    return get_success_data(resp)


def get_plan(plan_id) -> dict:
    resp = api_client.get_implementation_plan(plan_id, make_manager_headers(MANAGER_1))
    if resp.status_code != 200:
        _fail("get_implementation_plan", resp)
    return get_success_data(resp)


def get_control_now(control_id) -> dict:
    resp = api_client.get_control(control_id, make_officer_headers(OFFICER_A))
    if resp.status_code != 200:
        _fail("get_control", resp)
    return get_success_data(resp)


def list_escalations(params) -> list:
    resp = api_client.list_escalations(make_manager_headers(MANAGER_1), params=params)
    if resp.status_code != 200:
        _fail("list_escalations", resp)
    data, _meta = validate_paginated(resp)
    return data


def get_register() -> dict:
    resp = api_client.get_obligation_register(make_officer_headers(OFFICER_A))
    if resp.status_code != 200:
        _fail("get_obligation_register", resp)
    return get_success_data(resp)


def secretary_headers():
    return make_secretary_headers(SECRETARY_1)
