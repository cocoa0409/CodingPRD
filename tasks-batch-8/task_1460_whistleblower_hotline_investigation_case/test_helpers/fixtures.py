"""Composite setup helpers — multi-step scenario builders.

Every fixture builds its preconditions from scratch using only PRD-declared endpoints,
because the test harness restarts the API server before each test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_assignment_payload,
    create_case_payload,
    create_conclude_payload,
    create_determination_payload,
    create_evidence_payload,
    create_interview_payload,
    create_legal_hold_payload,
    create_remediation_action_payload,
    create_review_payload,
    create_screen_payload,
    create_staff_member_payload,
    create_triage_payload,
)
from .test_users import (
    make_admin_headers,
    make_intake_headers,
    make_investigator_headers,
    make_officer_headers,
    make_reporter_headers,
)


# ---------------------------------------------------------------------------
# Tier 1: staff + case primitives
# ---------------------------------------------------------------------------

def create_staff(display_name, email, capabilities, max_active_cases=5, **overrides):
    """Register a staff member; returns the StaffMember dict."""
    payload = create_staff_member_payload(
        display_name=display_name, email=email,
        capabilities=capabilities, max_active_cases=max_active_cases, **overrides,
    )
    resp = api_client.create_staff_member(payload, make_admin_headers())
    data = get_success_data(resp)
    assert data.get("id"), f"Setup failed: create_staff_member -> {data}"
    return data


def setup_standard_staff():
    """The canonical quartet: intake, officer1, officer2, investigator.

    Returns dict with keys s_int, s_off, s_off2, s_inv (each a StaffMember dict)
    and matching headers helpers bound to the real entity ids.
    """
    s_int = create_staff("Ingrid Intake", "intake@corp.example", ["INTAKE"])
    s_off = create_staff("Olivia Officer", "officer@corp.example", ["OFFICER"])
    s_off2 = create_staff("Oscar Officer", "officer2@corp.example", ["OFFICER"])
    s_inv = create_staff("Ian Vest", "investigator@corp.example", ["INVESTIGATION"])
    return {
        "s_int": s_int, "s_off": s_off, "s_off2": s_off2, "s_inv": s_inv,
        "h_int": make_intake_headers(s_int["id"]),
        "h_off": make_officer_headers(s_off["id"]),
        "h_off2": make_officer_headers(s_off2["id"]),
        "h_inv": make_investigator_headers(s_inv["id"]),
    }


def create_case(**overrides):
    """File a hotline report; returns (case_dict, reporter_access_key)."""
    payload = create_case_payload(**overrides)
    resp = api_client.create_case(payload, make_reporter_headers(f"reporter-{payload.get('channel', 'WEB_PORTAL')}"))
    data = get_success_data(resp)
    assert data.get("id"), f"Setup failed: create_case -> {data}"
    key = data.get("reporter_access_key")
    assert key, f"Setup failed: create_case did not return reporter_access_key -> {data}"
    return data, key


def triage_case(case_id, h_int, **overrides):
    payload = create_triage_payload(**overrides)
    resp = api_client.triage_case(case_id, payload, h_int)
    data = get_success_data(resp)
    assert data.get("status") in ("TRIAGED", "REJECTED"), f"Setup failed: triage -> {data}"
    return data


# ---------------------------------------------------------------------------
# Tier 2: routing helpers (auto + override)
# ---------------------------------------------------------------------------

def propose_assignment_auto(case_id, case_version, h_proposer):
    resp = api_client.create_assignment(case_id, {"expected_case_version": case_version}, h_proposer)
    data = get_success_data(resp)
    assert data.get("id"), f"Setup failed: auto-assign -> {data}"
    return data


def propose_assignment_override(case_id, case_version, investigator_id, h_officer, reason="Domain expertise"):
    payload = create_assignment_payload(
        case_version, investigator_id=investigator_id, override_reason=reason,
    )
    resp = api_client.create_assignment(case_id, payload, h_officer)
    data = get_success_data(resp)
    assert data.get("id"), f"Setup failed: override-assign -> {data}"
    return data


def screen_clear(assignment_id, h_screener):
    resp = api_client.screen_assignment(assignment_id, create_screen_payload(outcome="CLEAR"), h_screener)
    data = get_success_data(resp)
    assert data.get("status") == "CLEARED", f"Setup failed: screen CLEAR -> {data}"
    return data


def activate_assignment(assignment_id, h_officer):
    resp = api_client.activate_assignment(assignment_id, h_officer)
    data = get_success_data(resp)
    assert data.get("status") == "ACTIVE", f"Setup failed: activate -> {data}"
    return data


def get_case(case_id, h_reader):
    resp = api_client.get_case(case_id, h_reader)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 3: lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_case_triaged(_triage_overrides=None, **case_overrides):
    """Staff quartet + one case triaged (default FRAUD/STAFF/NONE/NONE -> MEDIUM)."""
    staff = setup_standard_staff()
    case, key = create_case(**case_overrides)
    triaged = triage_case(case["id"], staff["h_int"], **(_triage_overrides or {}))
    return {"staff": staff, "case": triaged, "reporter_key": key}


def setup_case_assigned(_triage_overrides=None, **case_overrides):
    """Case triaged + auto assignment PROPOSED (not yet screened)."""
    ctx = setup_case_triaged(_triage_overrides=_triage_overrides, **case_overrides)
    staff = ctx["staff"]
    asg = propose_assignment_auto(ctx["case"]["id"], ctx["case"]["version"], staff["h_int"])
    ctx["assignment"] = asg
    ctx["case"] = get_case(ctx["case"]["id"], staff["h_off"])
    return ctx


def setup_case_under_investigation(_triage_overrides=None, **case_overrides):
    """Full chain: triage -> assign -> screen CLEAR -> activate. Case is UNDER_INVESTIGATION."""
    ctx = setup_case_assigned(_triage_overrides=_triage_overrides, **case_overrides)
    staff = ctx["staff"]
    screen_clear(ctx["assignment"]["id"], staff["h_int"])
    activate_assignment(ctx["assignment"]["id"], staff["h_off"])
    ctx["case"] = get_case(ctx["case"]["id"], staff["h_off"])
    return ctx


def add_conducted_interview(ctx, start="2026-08-03T10:00:00Z", end="2026-08-03T11:00:00Z"):
    staff = ctx["staff"]
    iv_payload = create_interview_payload(ctx["case"]["id"], scheduled_start=start, scheduled_end=end)
    resp = api_client.create_interview(iv_payload, staff["h_inv"])
    iv = get_success_data(resp)
    assert iv.get("id"), f"Setup failed: create interview -> {iv}"
    resp2 = api_client.conclude_interview(iv["id"], create_conclude_payload(), staff["h_inv"])
    conducted = get_success_data(resp2)
    assert conducted.get("status") == "CONDUCTED", f"Setup failed: conclude -> {conducted}"
    return conducted


def add_sealed_evidence(ctx, sealer="h_int"):
    staff = ctx["staff"]
    ev_payload = create_evidence_payload(ctx["case"]["id"])
    resp = api_client.create_evidence_item(ev_payload, staff["h_inv"])
    ev = get_success_data(resp)
    assert ev.get("id"), f"Setup failed: create evidence -> {ev}"
    resp2 = api_client.seal_evidence(ev["id"], staff[sealer])
    sealed = get_success_data(resp2)
    assert sealed.get("status") == "SEALED", f"Setup failed: seal -> {sealed}"
    return sealed


def add_determination(ctx, finding="UNSUBSTANTIATED", rationale=None):
    staff = ctx["staff"]
    current = get_case(ctx["case"]["id"], staff["h_off"])
    payload = create_determination_payload(
        current["version"],
        finding=finding,
        rationale=rationale or "Evidence reviewed shows the allegation is not supported on the balance of proof.",
    )
    resp = api_client.create_determination(ctx["case"]["id"], payload, staff["h_inv"])
    det = get_success_data(resp)
    assert det.get("id"), f"Setup failed: create determination -> {det}"
    return det


def submit_determination(ctx, determination_id):
    staff = ctx["staff"]
    resp = api_client.submit_determination(determination_id, staff["h_inv"])
    det = get_success_data(resp)
    assert det.get("status") == "SUBMITTED", f"Setup failed: submit -> {det}"
    return det


def review_approve(ctx, determination_id, reviewer="h_off2", notice_summary="Case closed with no findings disclosed."):
    staff = ctx["staff"]
    payload = create_review_payload(decision="APPROVE", notice_summary=notice_summary)
    resp = api_client.review_determination(determination_id, payload, staff[reviewer])
    det = get_success_data(resp)
    assert det.get("status") == "APPROVED", f"Setup failed: review APPROVE -> {det}"
    return det


def setup_case_determination_review(finding="UNSUBSTANTIATED", _triage_overrides=None, **case_overrides):
    """Case in DETERMINATION_REVIEW with a SUBMITTED determination."""
    ctx = setup_case_under_investigation(_triage_overrides=_triage_overrides, **case_overrides)
    ctx["interview"] = add_conducted_interview(ctx)
    ctx["evidence"] = add_sealed_evidence(ctx)
    ctx["determination"] = add_determination(ctx, finding=finding)
    ctx["determination"] = submit_determination(ctx, ctx["determination"]["id"])
    ctx["case"] = get_case(ctx["case"]["id"], ctx["staff"]["h_off"])
    return ctx


def setup_case_closure_ready(finding="UNSUBSTANTIATED", _triage_overrides=None, **case_overrides):
    """Case in CLOSURE_READY with a SENT closure notice (via direct-to-closure review)."""
    ctx = setup_case_determination_review(finding=finding, _triage_overrides=_triage_overrides, **case_overrides)
    ctx["determination"] = review_approve(ctx, ctx["determination"]["id"])
    ctx["case"] = get_case(ctx["case"]["id"], ctx["staff"]["h_off"])
    resp = api_client.list_closure_notices(ctx["case"]["id"], ctx["staff"]["h_off"])
    notices = get_success_data(resp)
    assert isinstance(notices, list) and len(notices) == 1, f"Setup failed: notices -> {notices}"
    ctx["notice"] = notices[0]
    return ctx


def setup_case_in_remediation(_triage_overrides=None, **case_overrides):
    """SUBSTANTIATED case in REMEDIATION (approved, no remediation action yet)."""
    ctx = setup_case_determination_review(finding="SUBSTANTIATED", _triage_overrides=_triage_overrides, **case_overrides)
    ctx["determination"] = review_approve(ctx, ctx["determination"]["id"])
    ctx["case"] = get_case(ctx["case"]["id"], ctx["staff"]["h_off"])
    assert ctx["case"]["status"] == "REMEDIATION", f"Setup failed: expected REMEDIATION -> {ctx['case']}"
    return ctx


def setup_case_monitoring(_triage_overrides=None, **case_overrides):
    """Full lifecycle through MONITORING: closure-ready -> reporter ack -> plan ACTIVE."""
    ctx = setup_case_closure_ready(_triage_overrides=_triage_overrides, **case_overrides)
    staff = ctx["staff"]
    resp = api_client.acknowledge_notice(ctx["notice"]["id"], make_reporter_headers(ctx["reporter_key"]))
    ack = get_success_data(resp)
    assert ack.get("status") == "ACKNOWLEDGED", f"Setup failed: acknowledge -> {ack}"
    ctx["notice"] = ack
    ctx["case"] = get_case(ctx["case"]["id"], staff["h_off"])
    resp = api_client.list_monitoring_plans(ctx["case"]["id"], staff["h_off"])
    plans = get_success_data(resp)
    assert isinstance(plans, list) and len(plans) == 1, f"Setup failed: plans -> {plans}"
    ctx["plan"] = plans[0]
    return ctx


def setup_remediation_action(ctx, decider="h_off2", approve=True, **overrides):
    """Propose (+ optionally approve) a remediation action on ctx's approved determination."""
    staff = ctx["staff"]
    payload = create_remediation_action_payload(**overrides)
    resp = api_client.create_remediation_action(ctx["determination"]["id"], payload, staff["h_off"])
    action = get_success_data(resp)
    assert action.get("id"), f"Setup failed: create remediation action -> {action}"
    if approve:
        resp2 = api_client.decide_remediation_action(action["id"], {"decision": "APPROVE"}, staff[decider])
        action = get_success_data(resp2)
        assert action.get("status") == "IN_PROGRESS", f"Setup failed: decide APPROVE -> {action}"
    return action


def setup_case_with_active_hold(**case_overrides):
    """Case (default RECEIVED) with one ACTIVE legal hold placed by officer1."""
    staff = setup_standard_staff()
    case, key = create_case(**case_overrides)
    resp = api_client.create_legal_hold(create_legal_hold_payload(case["id"]), staff["h_off"])
    hold = get_success_data(resp)
    assert hold.get("status") == "ACTIVE", f"Setup failed: create hold -> {hold}"
    case = get_case(case["id"], staff["h_off"])
    return {"staff": staff, "case": case, "hold": hold, "reporter_key": key}
