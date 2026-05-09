"""Case approval and rejection — REQUESTED → APPROVED / REJECTED."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_surgical_case_payload,
    create_surgical_case,
    approve_case,
    reject_case,
    get_settlement_for_case,
    setup_branching_state_machine,
)


COORD = TEST_USERS["surgical_coordinator_headers"]
DEPT = TEST_USERS["department_head_headers"]
SCHED = TEST_USERS["scheduler_headers"]


def test_approve_with_both_safety_flags_true(api):
    """PRD §3.2: 'Approval by a `DepartmentHead` advances the case from `REQUESTED`
    to `APPROVED`, but only when both safety preconditions are met'."""
    case = create_surgical_case(
        pre_op_assessment_attached=True, informed_consent_verified=True
    )
    res = api.approve_case(case["id"], DEPT)
    approved = validate_success(res, 200)
    assert approved["status"] == "APPROVED"


def test_approve_creates_settlement_in_draft(api):
    """PRD §3.2: 'On approval, the system creates a `Settlement` for the case
    (`status` set to `DRAFT`, `case_id` set to the case's id, `estimated_total_amount`
    left as `null` until the case is scheduled, ... `refund_amount` `0.0`,
    and `insurance_pre_auth_reference` `null`)'."""
    case = create_surgical_case(pre_op_assessment_attached=True, informed_consent_verified=True)
    approve_case(case["id"])
    s = get_settlement_for_case(case["id"])
    assert s is not None
    assert s["status"] == "DRAFT"
    assert s["case_id"] == case["id"]
    assert s["estimated_total_amount"] is None
    assert s["final_total_amount"] is None
    assert s["insurance_pre_auth_reference"] is None
    assert s["refund_amount"] == 0.0


def test_approve_fails_without_pre_op_assessment(api):
    """PRD §3.2: 'the request must already have `pre_op_assessment_attached` set to
    `true` (otherwise the call is rejected with `ERR_PRE_OP_ASSESSMENT_MISSING`)'."""
    case = create_surgical_case(
        pre_op_assessment_attached=False,
        informed_consent_verified=True,
    )
    validate_error(api.approve_case(case["id"], DEPT), "ERR_PRE_OP_ASSESSMENT_MISSING")


def test_approve_fails_without_consent(api):
    """PRD §3.2: '`informed_consent_verified` must already be `true` (otherwise
    rejected with `ERR_INFORMED_CONSENT_MISSING`)'."""
    case = create_surgical_case(
        pre_op_assessment_attached=True,
        informed_consent_verified=False,
    )
    validate_error(api.approve_case(case["id"], DEPT), "ERR_INFORMED_CONSENT_MISSING")


def test_approve_pre_op_evaluated_before_consent(api):
    """PRD §3.2: 'Note that the priority ladder of §2.6 evaluates assessment attachment
    before consent verification — when both flags are missing, the system surfaces the
    assessment error first, not the consent error'."""
    case = create_surgical_case(
        pre_op_assessment_attached=False,
        informed_consent_verified=False,
    )
    validate_error(api.approve_case(case["id"], DEPT), "ERR_PRE_OP_ASSESSMENT_MISSING")


def test_reject_with_reason(api):
    """PRD §3.2: 'Rejection by a `DepartmentHead` advances the case from `REQUESTED`
    to `REJECTED`. ... The optional `rejected_reason` from the request body is
    persisted'."""
    case = create_surgical_case()
    res = api.reject_case(case["id"], DEPT, payload={"rejected_reason": "patient withdrew"})
    rejected = validate_success(res, 200)
    assert rejected["status"] == "REJECTED"
    assert rejected["rejected_reason"] == "patient withdrew"


def test_reject_terminal_cannot_be_advanced(api):
    """PRD §3.2: '`REJECTED` is terminal: a rejected case cannot be approved,
    scheduled, or otherwise advanced'."""
    case = create_surgical_case()
    reject_case(case["id"])
    validate_error(api.approve_case(case["id"], DEPT), "ERR_CASE_NOT_REQUESTED")


def test_approve_after_already_approved_rejected(api):
    """PRD §3.2: 'A request to approve or reject a case that is no longer in
    `REQUESTED` is rejected with `ERR_CASE_NOT_REQUESTED`'."""
    case = create_surgical_case(pre_op_assessment_attached=True, informed_consent_verified=True)
    approve_case(case["id"])
    validate_error(api.approve_case(case["id"], DEPT), "ERR_CASE_NOT_REQUESTED")


def test_approve_not_found(api):
    """PRD §2.6 / §3.2: missing case → ERR_CASE_NOT_FOUND."""
    validate_error(api.approve_case(NON_EXISTENT_UUID, DEPT), "ERR_CASE_NOT_FOUND")


def test_approve_requires_department_head_role(api):
    """PRD §4: 'POST /surgical-cases/{caseId}/approve' is restricted to DepartmentHead.
    PRD §2.1: missing role on authorized list → `ERR_INSUFFICIENT_PERMISSIONS`."""
    case = create_surgical_case(pre_op_assessment_attached=True, informed_consent_verified=True)
    validate_error(api.approve_case(case["id"], SCHED), "ERR_INSUFFICIENT_PERMISSIONS")


# ─── Difficulty Rule 3, instance surgical_case_branching_at_requested ───────

def test_branching_approved_creates_settlement(api):
    """# difficulty: non_linear_state_machine/surgical_case_branching_at_requested

    PRD §3.2: 'On approval, the system creates a `Settlement` for the case
    (`status` set to `DRAFT`, `case_id` set to the case's id, ...)'."""
    bundle = setup_branching_state_machine()
    assert bundle["case1_approved"]["status"] == "APPROVED"
    s = get_settlement_for_case(bundle["case1_approved"]["id"])
    assert s is not None
    assert s["status"] == "DRAFT"


def test_branching_rejected_no_settlement(api):
    """# difficulty: non_linear_state_machine/surgical_case_branching_at_requested

    PRD §3.2 + §3.9: Settlement is created at approval, not rejection. PRD §3.9:
    'A `Settlement` is created with `status` `DRAFT` at the moment its owning case
    is approved (see §3.2)'. PRD §3.2 rejection paragraph names only the persisted
    `rejected_reason` and the `'CASE_REJECTED'` audit entry — no Settlement is
    listed in the rejection cascade.
    """
    bundle = setup_branching_state_machine()
    assert bundle["case2_rejected"]["status"] == "REJECTED"
    assert bundle["case2_rejected"]["rejected_reason"] == "clinical contraindication"
    s = get_settlement_for_case(bundle["case2_rejected"]["id"])
    assert s is None
