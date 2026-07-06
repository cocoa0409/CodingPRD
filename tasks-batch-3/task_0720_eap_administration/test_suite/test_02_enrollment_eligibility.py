"""Benefit plans, employee enrollment, eligibility, and dependents."""
import pytest
from test_helpers import (
    TEST_USERS, validate_success, validate_error, ApiErrorId,
)
import test_helpers.fixtures as fx

ADMIN = TEST_USERS["program_admin_headers"]
COORD = TEST_USERS["care_coordinator_headers"]


def test_enroll_employee_with_draft_plan_returns_plan_not_published(api):
    """PRD §3.2: "A plan is born in `DRAFT` status and must be published — moving
    it to `PUBLISHED` — before any employee can be assigned to it."
    PRD §3.2: "it must already be `PUBLISHED`; enrolling against an unpublished
    plan is rejected with `ERR_PLAN_NOT_PUBLISHED`."

    Design: Corner/validations/enroll_employee_with_draft_plan_returns_plan_not_published
    """
    contract = fx.create_contract(employer_name="DraftCo")
    plan = fx.create_draft_plan(contract["id"], name="Draft")
    payload = {"contract_id": contract["id"], "plan_id": plan["id"],
               "full_name": "Empl Df", "external_ref": "EDF1"}
    validate_error(api.create_employee(payload, ADMIN),
                   ApiErrorId.ERR_PLAN_NOT_PUBLISHED.value)


def test_enroll_employee_plan_not_under_contract_returns_referential_mismatch(api):
    """PRD §2.5: "When enrolling an employee, the supplied `plan_id` must name a
    benefit plan that belongs to the supplied `contract_id`."
    PRD §2.5: "several creates must satisfy cross-foreign-key consistency,
    enforced with `ERR_REFERENTIAL_MISMATCH` (HTTP 409)."

    Design: Corner/validations/enroll_employee_plan_not_under_contract_returns_referential_mismatch
    """
    contract_a = fx.create_contract(employer_name="RefA")
    contract_b = fx.create_contract(employer_name="RefB")
    plan_b = fx.create_published_plan(contract_b["id"], name="PlanB")
    payload = {"contract_id": contract_a["id"], "plan_id": plan_b["id"],
               "full_name": "Empl Rf", "external_ref": "ERF1"}
    validate_error(api.create_employee(payload, ADMIN),
                   ApiErrorId.ERR_REFERENTIAL_MISMATCH.value)


def test_duplicate_external_ref_within_contract_rejected(api):
    """PRD §3.2: "The `external_ref` must be unique within the contract; a
    collision is rejected with `ERR_DUPLICATE_EXTERNAL_REF`."

    Design: Corner/validations/duplicate_external_ref_within_contract_rejected
    """
    contract = fx.create_contract(employer_name="DupCo")
    plan = fx.create_published_plan(contract["id"])
    fx.create_employee(contract["id"], plan["id"], full_name="First", external_ref="DUP")
    payload = {"contract_id": contract["id"], "plan_id": plan["id"],
               "full_name": "Second", "external_ref": "DUP"}
    validate_error(api.create_employee(payload, ADMIN),
                   ApiErrorId.ERR_DUPLICATE_EXTERNAL_REF.value)


def test_authorize_ineligible_employee_returns_employee_ineligible(api):
    """PRD §3.3: "The sponsoring employee's `eligibility_status` must be
    `ELIGIBLE` or `GRACE`, or the request fails with `ERR_EMPLOYEE_INELIGIBLE`."

    Design: Corner/validations/authorize_ineligible_employee_returns_employee_ineligible
    """
    contract, plan, employee = fx.setup_contract_plan_employee()
    validate_success(api.set_eligibility(
        employee["id"], {"eligibility_status": "INELIGIBLE"}, ADMIN))
    case = fx.create_case(contract["id"], employee["id"])
    validate_error(api.authorize_case(
        case["id"], {"expected_contract_version": contract["version"]}, COORD),
        ApiErrorId.ERR_EMPLOYEE_INELIGIBLE.value)


def test_dependent_not_under_employee_on_case_rejected(api):
    """PRD §3.3: "If a `dependent_id` is supplied, it must be a dependent of the
    named `employee_id`; otherwise the open is rejected with
    `ERR_DEPENDENT_NOT_UNDER_EMPLOYEE`."

    Design: Corner/validations/dependent_not_under_employee_on_case_rejected
    """
    from test_helpers import create_dependent_payload, create_case_payload
    contract = fx.create_contract(employer_name="DepCo")
    plan = fx.create_published_plan(contract["id"])
    e1 = fx.create_employee(contract["id"], plan["id"], full_name="Emp1", external_ref="D1")
    e2 = fx.create_employee(contract["id"], plan["id"], full_name="Emp2", external_ref="D2")
    dep = validate_success(api.create_dependent(
        create_dependent_payload(e2["id"], full_name="Dep of E2", relationship="CHILD"), ADMIN), 201)
    payload = create_case_payload(contract["id"], e1["id"], dependent_id=dep["id"])
    validate_error(api.create_case(payload, COORD),
                   ApiErrorId.ERR_DEPENDENT_NOT_UNDER_EMPLOYEE.value)
