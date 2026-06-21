"""Enrollment creation gates and clinical activation gates.

Queue A: cross_entity_state_dependency (activate requires intake APPROVED;
         Rx issue requires eligibility APPROVED).
Queue B: validations (intake-member mismatch, plan retired, Rx required),
         state_machines (double-activate idempotency), consistency_model
         (immediate cycle-0 invoice visibility).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    factories as f,
    fixtures,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["program_admin_headers"]
CLINICIAN = TEST_USERS["clinician_headers"]
BILLING = TEST_USERS["billing_agent_headers"]


def test_enrollment_activate_requires_intake_approved(api):
    """PRD §3.4: "The referenced intake assessment must be in `APPROVED` status
    (else `ERR_INTAKE_NOT_APPROVED`)."

    Design: Difficulty/cross_entity_state_dependency/enrollment_activate_requires_intake_approved
    """
    program = fixtures.create_program()
    plan = fixtures.create_plan(program["id"])
    member = fixtures.create_member(program["id"])
    intake = fixtures.create_intake_under_review(member["id"])  # not approved
    enrollment = validate_success(
        api.create_enrollment(f.create_enrollment_payload(member["id"], plan["id"], intake["id"]), ADMIN),
        201,
    )
    resp = api.activate_enrollment(enrollment["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INTAKE_NOT_APPROVED.value, 409)
    after = validate_success(api.get_enrollment(enrollment["id"], ADMIN), 200)
    assert after["clinical_status"] == "PENDING_CLINICAL", "failed activate must not advance status"


def test_rx_issue_requires_eligibility_approved(api):
    """PRD §3.10: "The referenced eligibility determination must be `APPROVED`
    (else `ERR_ELIGIBILITY_NOT_APPROVED`)."

    Design: Difficulty/cross_entity_state_dependency/rx_issue_requires_eligibility_approved
    """
    ctx = fixtures.create_pending_enrollment(
        plan_overrides={"tier": "RX", "monthly_fee_cents": 9000}, intake_weight_kg=95
    )
    enr_id = ctx["enrollment"]["id"]
    det = fixtures.create_pending_eligibility(ctx["member"]["id"], enr_id)  # still PENDING
    rx = fixtures.create_requested_rx(enr_id, det["id"])
    version = fixtures.get_enrollment_version(enr_id)
    resp = api.issue_rx(rx["id"], f.issue_rx_payload(version), CLINICIAN)
    validate_error(resp, ApiErrorId.ERR_ELIGIBILITY_NOT_APPROVED.value, 409)
    after = validate_success(api.get_rx(rx["id"], CLINICIAN), 200)
    assert after["status"] == "REQUESTED", "failed issue must leave Rx in REQUESTED"


def test_activate_with_approved_intake_succeeds(api):
    """PRD §3.4: "When all gates pass, activation advances `clinical_status` to
    `ACTIVE`, sets the member's `status` to `ENROLLED`, stamps `billing_anchor_utc`
    from the program's `current_utc`, automatically advances `billing_status` from
    `UNBILLED` to `CURRENT`, and generates the cycle-0 invoice with `cycles_billed`
    becoming 1."

    Design: Difficulty/cross_entity_state_dependency/enrollment_activate_requires_intake_approved
    """
    ctx = fixtures.create_pending_enrollment()  # intake APPROVED, COACHING plan
    activated = validate_success(api.activate_enrollment(ctx["enrollment"]["id"], ADMIN), 200)
    assert activated["clinical_status"] == "ACTIVE", (
        f"approved-intake activation must advance to ACTIVE, got {activated['clinical_status']}"
    )
    assert activated["billing_status"] == "CURRENT", "billing_status must auto-advance to CURRENT"


def test_rx_issue_with_approved_eligibility_succeeds(api):
    """PRD §3.10: "A successful issuance snapshots the qualifying BMI into
    `qualifying_bmi`, records the issuing clinician's identifier into
    `clinician_user_id`, and advances the enrollment's `version` by one."

    Design: Difficulty/cross_entity_state_dependency/rx_issue_requires_eligibility_approved
    """
    ctx = fixtures.create_pending_enrollment(
        plan_overrides={"tier": "RX", "monthly_fee_cents": 9000}, intake_weight_kg=95
    )
    enr_id = ctx["enrollment"]["id"]
    det = fixtures.create_approved_eligibility(ctx["member"]["id"], enr_id)  # APPROVED
    rx = fixtures.create_requested_rx(enr_id, det["id"])
    version = fixtures.get_enrollment_version(enr_id)
    issued = validate_success(api.issue_rx(rx["id"], f.issue_rx_payload(version), CLINICIAN), 200)
    assert issued["status"] == "ISSUED", f"approved-eligibility issue must produce ISSUED, got {issued['status']}"


def test_intake_member_mismatch_on_enroll(api):
    """PRD §3.4: "The referenced intake assessment must belong to the same member
    named by `member_id`, or the create is rejected with
    `ERR_INTAKE_MEMBER_MISMATCH`."

    Design: Corner/validations/intake_member_mismatch_on_enroll
    """
    program = fixtures.create_program()
    plan = fixtures.create_plan(program["id"])
    member_a = fixtures.create_member(program["id"])
    member_b = fixtures.create_member(program["id"])
    intake_a = fixtures.create_approved_intake(member_a["id"])
    resp = api.create_enrollment(
        f.create_enrollment_payload(member_b["id"], plan["id"], intake_a["id"]), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_INTAKE_MEMBER_MISMATCH.value, 409)


def test_enroll_on_retired_plan_blocked(api):
    """PRD §3.4: "the chosen plan must be active, or the create is rejected with
    `ERR_PLAN_RETIRED`."

    Design: Corner/validations/enroll_on_retired_plan_blocked
    """
    program = fixtures.create_program()
    plan = fixtures.create_plan(program["id"])
    validate_success(api.retire_plan(plan["id"], ADMIN), 200)
    member = fixtures.create_member(program["id"])
    intake = fixtures.create_approved_intake(member["id"])
    resp = api.create_enrollment(
        f.create_enrollment_payload(member["id"], plan["id"], intake["id"]), ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_RETIRED.value, 409)


def test_rx_required_for_rx_tier_activation(api):
    """PRD §3.4: "If the chosen plan's tier is `RX`, there must exist an
    `RxAuthorization` for this enrollment in `ISSUED` status (else
    `ERR_RX_AUTHORIZATION_REQUIRED`)."

    Design: Corner/validations/rx_required_for_rx_tier_activation
    """
    ctx = fixtures.create_pending_enrollment(
        plan_overrides={"tier": "RX", "monthly_fee_cents": 9000}
    )
    resp = api.activate_enrollment(ctx["enrollment"]["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_RX_AUTHORIZATION_REQUIRED.value, 409)


def test_double_activate_returns_invalid_state(api):
    """PRD §3.4: "Clinical activation ... is permitted only when `clinical_status`
    is `PENDING_CLINICAL` (else `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/invalid_transition_enrollment_activate_already_active
    """
    ctx = fixtures.create_active_enrollment()
    enr_id = ctx["enrollment"]["id"]
    resp = api.activate_enrollment(enr_id, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    after = validate_success(api.get_enrollment(enr_id, ADMIN), 200)
    assert after["cycles_billed"] == 1, "second activate must not generate a duplicate cycle-0 invoice"


def test_activate_immediate_invoice_visible_same_flow(api):
    """PRD §3.4: "When all gates pass, activation advances `clinical_status` to
    `ACTIVE` ... and generates the cycle-0 invoice with `cycles_billed` becoming 1."

    Design: Corner/consistency_model/activate_immediate_invoice_visible_same_flow
    """
    ctx = fixtures.create_active_enrollment()
    enr_id = ctx["enrollment"]["id"]
    data, _meta = fixtures.list_invoices(enr_id)
    cycle0 = [inv for inv in data if inv["cycle_index"] == 0]
    assert len(cycle0) == 1, (
        f"exactly one cycle-0 invoice must be visible immediately after activation, got {len(cycle0)}"
    )
