"""Assignment dual approval: referential gates, certificate gate, and the
segregation-of-duties check between the two approval steps (PRD §2.8, §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_certificate,
    add_package,
    add_split,
    api_client,
    create_draft_assignment,
    create_employee,
    create_policy,
    create_program,
    get_assignment,
    make_mobility_approver_headers,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
BU = TEST_USERS["bu_approver_headers"]
PAYROLL = TEST_USERS["payroll_headers"]


def _to_pending_mobility(assignment_id):
    """DRAFT -> PENDING_BU_APPROVAL -> PENDING_MOBILITY_APPROVAL (PRD §3.2)."""
    validate_success(api_client.submit_assignment(assignment_id, ADMIN), 200)
    validate_success(api_client.approve_bu(assignment_id, BU), 200)


def test_activation_gates_fire_in_order_then_succeed(api, mobility_approver_headers):
    """PRD §3.2: "Mobility approval additionally enforces three referential gates, all
    409s: an `APPROVED` compensation package must exist (`ERR_PACKAGE_NOT_APPROVED`),
    an `ACTIVE` payroll split must exist (`ERR_SPLIT_NOT_ACTIVE`), and when
    `totalization_applies` is true an `ISSUED` certificate of coverage must exist
    (`ERR_COC_REQUIRED`)."

    Design: Difficulty/cross_entity_state_dependency/activation_requires_approved_package_and_active_split
    """
    program = create_program()
    employee = create_employee()
    policy = create_policy()
    assignment = create_draft_assignment(program["id"], employee["id"], policy["id"])
    package = add_package(assignment["id"], state="submitted")
    split = add_split(assignment["id"], state="draft")
    _to_pending_mobility(assignment["id"])

    # Package merely SUBMITTED -> the package gate fires.
    res = api.approve_mobility(assignment["id"], mobility_approver_headers)
    validate_error(res, ApiErrorId.ERR_PACKAGE_NOT_APPROVED)

    validate_success(api.approve_package(package["id"], mobility_approver_headers), 200)

    # Package APPROVED but split still DRAFT -> the split gate fires.
    res = api.approve_mobility(assignment["id"], mobility_approver_headers)
    validate_error(res, ApiErrorId.ERR_SPLIT_NOT_ACTIVE)

    validate_success(api.activate_split(split["id"], PAYROLL), 200)

    activated = validate_success(api.approve_mobility(assignment["id"], mobility_approver_headers), 200)
    assert activated["status"] == "ACTIVE"


def test_activation_split_gate_isolated(api, mobility_approver_headers):
    """PRD §3.2: "Mobility approval additionally enforces three referential gates, all
    409s: an `APPROVED` compensation package must exist (`ERR_PACKAGE_NOT_APPROVED`),
    an `ACTIVE` payroll split must exist (`ERR_SPLIT_NOT_ACTIVE`), and when
    `totalization_applies` is true an `ISSUED` certificate of coverage must exist
    (`ERR_COC_REQUIRED`)."

    Design: Difficulty/cross_entity_state_dependency/activation_requires_approved_package_and_active_split
    """
    program = create_program()
    employee = create_employee()
    policy = create_policy()
    assignment = create_draft_assignment(program["id"], employee["id"], policy["id"])
    add_package(assignment["id"], state="approved")
    split = add_split(assignment["id"], state="draft")
    _to_pending_mobility(assignment["id"])

    # Package gate passes; only the split gate can fail.
    res = api.approve_mobility(assignment["id"], mobility_approver_headers)
    validate_error(res, ApiErrorId.ERR_SPLIT_NOT_ACTIVE)

    validate_success(api.activate_split(split["id"], PAYROLL), 200)
    activated = validate_success(api.approve_mobility(assignment["id"], mobility_approver_headers), 200)
    assert activated["status"] == "ACTIVE"


def test_activation_with_totalization_requires_issued_certificate(api, mobility_approver_headers):
    """PRD §3.2: "Mobility approval additionally enforces three referential gates, all
    409s: an `APPROVED` compensation package must exist (`ERR_PACKAGE_NOT_APPROVED`),
    an `ACTIVE` payroll split must exist (`ERR_SPLIT_NOT_ACTIVE`), and when
    `totalization_applies` is true an `ISSUED` certificate of coverage must exist
    (`ERR_COC_REQUIRED`)."

    Design: Corner/validations/activation_with_totalization_requires_issued_certificate
    """
    program = create_program()
    employee = create_employee()
    policy = create_policy()
    assignment = create_draft_assignment(
        program["id"], employee["id"], policy["id"], totalization_applies=True)
    add_package(assignment["id"], state="approved")
    add_split(assignment["id"], state="active")
    # Certificate created but only REQUESTED — never submitted or issued.
    add_certificate(assignment["id"], state="requested")
    _to_pending_mobility(assignment["id"])

    res = api.approve_mobility(assignment["id"], mobility_approver_headers)
    validate_error(res, ApiErrorId.ERR_COC_REQUIRED)
    assert get_assignment(assignment["id"])["status"] == "PENDING_MOBILITY_APPROVAL"


def test_sod_dual_approval_requires_two_distinct_users(api):
    """PRD §2.8: "And the mobility approver who activates an assignment must differ
    from the assignment's `bu_approved_by_user_id` — the business-unit approver who
    performed the first approval step."
    PRD §2.8: "Any attempt to perform both sides of a controlled step with the same
    `X-User-ID` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

    Design: Corner/validations/sod_dual_approval_requires_two_distinct_users
    """
    program = create_program()
    employee = create_employee()
    policy = create_policy()
    assignment = create_draft_assignment(program["id"], employee["id"], policy["id"])
    add_package(assignment["id"], state="approved")
    add_split(assignment["id"], state="active")
    _to_pending_mobility(assignment["id"])  # BU approval recorded under user id bu-1

    # Replay the same user id under the MobilityApprover role.
    res = api.approve_mobility(assignment["id"], make_mobility_approver_headers("bu-1"))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert get_assignment(assignment["id"])["status"] == "PENDING_MOBILITY_APPROVAL"
