"""Compensation packages and payroll splits: initial states, one-open-slot
rules, the revision cycle, creator/approver segregation, the percentage-sum
boundary, the suspend/resume cycle, and the certificate-driven exemption flag
(PRD §2.8, §3.2, §3.5)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_package,
    add_split,
    api_client,
    create_certificate_payload,
    create_draft_assignment,
    create_draft_record,
    create_employee,
    create_engagement,
    create_package_payload,
    create_policy,
    create_program,
    create_split_payload,
    get_assignment,
    mark_issued_payload,
    setup_active_assignment,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
PAYROLL = TEST_USERS["payroll_headers"]
MOBILITY_APPROVER = TEST_USERS["mobility_approver_headers"]
COORDINATOR = TEST_USERS["vendor_coordinator_headers"]


def _draft_assignment(totalization=False, employee_ref="E1001", **policy_overrides):
    program = create_program()
    employee = create_employee(employee_ref=employee_ref)
    policy = create_policy(**policy_overrides)
    assignment = create_draft_assignment(
        program["id"], employee["id"], policy["id"], totalization_applies=totalization)
    return assignment


def test_initial_states_on_entity_creation(api, payroll_headers, vendor_coordinator_headers):
    """PRD §3.2: "With program, employee, and policy in place, a `MobilityAdmin`
    creates the assignment itself in `DRAFT`"
    PRD §3.2: "The creator's identity is recorded as `created_by_user_id`, and
    `revision_number` starts at 0."
    PRD §3.4: "New engagements start in `ENGAGED` with `revision_count` at 0."
    PRD §3.5: "The application moves `REQUESTED` → `SUBMITTED` when the coordinator
    submits it to the authorities."

    Design: Corner/entities/initial_states_on_entity_creation
    """
    assignment = _draft_assignment()
    assert assignment["status"] == "DRAFT"

    package = validate_success(api.create_package(
        create_package_payload(assignment["id"]), payroll_headers), 201)
    assert package["status"] == "DRAFT"
    assert package["revision_number"] == 0
    assert isinstance(package["version"], int)

    engagement = create_engagement(assignment["id"], scope="HOME_ONLY")
    assert engagement["status"] == "ENGAGED"
    assert engagement["revision_count"] == 0

    certificate = validate_success(api.create_certificate(
        create_certificate_payload(assignment["id"]), vendor_coordinator_headers), 201)
    assert certificate["status"] == "REQUESTED"


def test_duplicate_open_package_and_split_rejected(api, payroll_headers):
    """PRD §3.2: "At most one package per assignment may be open — `DRAFT`,
    `SUBMITTED`, or `APPROVED` all count as open, and a second attempt is rejected
    with `ERR_DUPLICATE_PACKAGE`."
    PRD §3.2: "At most one split per assignment may be open across `DRAFT`, `ACTIVE`,
    and `SUSPENDED`, else `ERR_DUPLICATE_SPLIT`."

    Design: Corner/validations/duplicate_open_package_and_split_rejected
    """
    assignment = _draft_assignment()
    add_package(assignment["id"], state="draft")
    add_split(assignment["id"], state="draft")

    res = api.create_package(
        create_package_payload(assignment["id"], letter_title="Letter B",
                               home_base_annual_cents=11000000),
        payroll_headers)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_PACKAGE)

    res = api.create_split(
        create_split_payload(assignment["id"], home_payroll_pct=50, host_payroll_pct=50),
        payroll_headers)
    validate_error(res, ApiErrorId.ERR_DUPLICATE_SPLIT)


def test_package_revise_cycle_increments_revision_and_clears_approval(api, payroll_headers):
    """PRD §3.2: "Revision is cyclic: a `PayrollSpecialist` may return a `SUBMITTED`
    package to `DRAFT`, incrementing `revision_number` by one and clearing
    `approved_by_user_id`; the same revise action works from `APPROVED`, but only while
    the linked assignment is still in `DRAFT` — revising the package of an assignment
    that has progressed further is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/package_revise_cycle_increments_revision_and_clears_approval
    """
    # Assignment still DRAFT: revise from APPROVED is allowed.
    first = _draft_assignment()
    package = add_package(first["id"], state="approved")
    revised = validate_success(api.revise_package(package["id"], payroll_headers), 200)
    assert revised["status"] == "DRAFT"
    assert revised["revision_number"] == 1
    assert revised["approved_by_user_id"] is None

    # Assignment ACTIVE: revise is forbidden.
    ctx = setup_active_assignment(
        employee_overrides={"employee_ref": "E1002", "full_name": "B Two"},
        policy_overrides={"effective_from": "2028-01-01", "effective_to": "2029-12-31"})
    res = api.revise_package(ctx["package"]["id"], payroll_headers)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_sod_package_creator_cannot_approve_own_package(api, payroll_headers):
    """PRD §2.8: "The operator who approves a compensation package must differ from
    the package's `created_by_user_id`."
    PRD §2.8: "Any attempt to perform both sides of a controlled step with the same
    `X-User-ID` is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

    Design: Corner/validations/sod_package_creator_cannot_approve_own_package
    """
    from test_helpers import make_mobility_approver_headers

    assignment = _draft_assignment()
    # Created and submitted under payroll user id ps-1.
    package = add_package(assignment["id"], state="submitted")

    # The same user id holding the MobilityApprover role is still the creator.
    res = api.approve_package(package["id"], make_mobility_approver_headers("ps-1"))
    validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    fetched = validate_success(api.get_package(package["id"], payroll_headers), 200)
    assert fetched["status"] == "SUBMITTED"


def test_split_percentage_extreme_sums_accepted(api, payroll_headers):
    """PRD §3.2: "Alongside the letter, a `PayrollSpecialist` creates the payroll
    split for the assignment with `home_payroll_pct` and `host_payroll_pct`, each
    between 0 and 100 inclusive and together summing to exactly one hundred — any other
    total is rejected with `ERR_SPLIT_SUM_INVALID` (HTTP 422) — and the optional
    `shadow_payroll_host` flag, defaulting to true, which records whether a host shadow
    payroll is run."

    Design: Difficulty/boundary_precision_check/split_percentage_sum_boundary
    """
    # Distinct employees so the closed-interval overlap rule does not fire, and a
    # disjoint policy window so the same-country half-open window rule (PRD §3.1)
    # does not reject the second policy as a genuine overlap.
    first = _draft_assignment(employee_ref="E1001")
    second = _draft_assignment(employee_ref="E1002",
                               effective_from="2028-01-01", effective_to="2029-12-31")

    # 100/0: sum exactly 100 at the range extreme; created and activated.
    split_full_home = validate_success(api.create_split(
        create_split_payload(first["id"], home_payroll_pct=100, host_payroll_pct=0),
        payroll_headers), 201)
    activated = validate_success(api.activate_split(split_full_home["id"], payroll_headers), 200)
    assert activated["status"] == "ACTIVE"

    # 0/100: the other extreme; created in DRAFT.
    split_full_host = validate_success(api.create_split(
        create_split_payload(second["id"], home_payroll_pct=0, host_payroll_pct=100),
        payroll_headers), 201)
    assert split_full_host["status"] == "DRAFT"


def test_split_percentage_sum_not_one_hundred_rejected(api, payroll_headers):
    """PRD §3.2: "Alongside the letter, a `PayrollSpecialist` creates the payroll
    split for the assignment with `home_payroll_pct` and `host_payroll_pct`, each
    between 0 and 100 inclusive and together summing to exactly one hundred — any other
    total is rejected with `ERR_SPLIT_SUM_INVALID` (HTTP 422) — and the optional
    `shadow_payroll_host` flag, defaulting to true, which records whether a host shadow
    payroll is run."

    Design: Difficulty/boundary_precision_check/split_percentage_sum_boundary
    """
    assignment = _draft_assignment()
    res = api.create_split(
        create_split_payload(assignment["id"], home_payroll_pct=99, host_payroll_pct=2),
        payroll_headers)
    validate_error(res, ApiErrorId.ERR_SPLIT_SUM_INVALID)


def test_split_suspend_blocks_record_creation(api, payroll_headers):
    """PRD §3.3: "Creation is gated in pipeline order: the assignment must be `ACTIVE`
    (`ERR_INVALID_STATE`); an `ACTIVE` payroll split must exist (`ERR_SPLIT_NOT_ACTIVE`)"
    PRD §3.2: "An `ACTIVE` split may be suspended (`ACTIVE` → `SUSPENDED`) and later
    resumed (`SUSPENDED` → `ACTIVE`)"

    Design: Difficulty/non_linear_state_machine/payroll_split_suspend_resume_cycle
    """
    ctx = setup_active_assignment()
    split_id = ctx["split"]["id"]
    asg_id = ctx["assignment"]["id"]

    suspended = validate_success(api.suspend_split(split_id, payroll_headers), 200)
    assert suspended["status"] == "SUSPENDED"

    res = api.create_record(
        {"assignment_id": asg_id, "tax_year": 2026, "period_month": 9,
         "total_gross_cents": 900000, "per_diem_days": 20, "housing_receipts_cents": 310000},
        payroll_headers)
    validate_error(res, ApiErrorId.ERR_SPLIT_NOT_ACTIVE)


def test_split_resume_restores_record_creation(api, payroll_headers):
    """PRD §3.2: "An `ACTIVE` split may be suspended (`ACTIVE` → `SUSPENDED`) and later
    resumed (`SUSPENDED` → `ACTIVE`), but resuming requires the linked assignment itself
    to be `ACTIVE`"
    PRD §3.3: "The record is created in `DRAFT` with all computed fields derived
    immediately from the `ACTIVE` split's percentages and the assignment's policy"

    Design: Difficulty/non_linear_state_machine/payroll_split_suspend_resume_cycle
    """
    ctx = setup_active_assignment()
    split_id = ctx["split"]["id"]
    asg_id = ctx["assignment"]["id"]

    validate_success(api.suspend_split(split_id, payroll_headers), 200)
    resumed = validate_success(api.resume_split(split_id, payroll_headers), 200)
    assert resumed["status"] == "ACTIVE"

    record = create_draft_record(asg_id, tax_year=2026, period_month=9)
    assert record["status"] == "DRAFT"

    split = validate_success(api.get_split(split_id, payroll_headers), 200)
    assert split["status"] == "ACTIVE"


def test_coc_issuance_flips_split_exemption(api, payroll_headers, vendor_coordinator_headers):
    """PRD §3.5: "On issuance the payroll split's `coc_exempt` flag becomes true, so
    new and amended draft records compute `employer_socsec_cents` as zero (§3.3)."
    PRD §3.2: "The split is created in `DRAFT` with its computed `coc_exempt` flag
    false."

    Design: Corner/state_machines/coc_issuance_flips_split_exemption
    """
    assignment = _draft_assignment(totalization=True)
    split = add_split(assignment["id"], state="draft")
    assert split["coc_exempt"] is False

    certificate = validate_success(api.create_certificate(
        create_certificate_payload(assignment["id"]), vendor_coordinator_headers), 201)
    validate_success(api.submit_certificate(certificate["id"], vendor_coordinator_headers), 200)
    validate_success(api.mark_issued(
        certificate["id"], mark_issued_payload("2026-09-01", "2027-08-31"),
        vendor_coordinator_headers), 200)

    split_after = validate_success(api.get_split(split["id"], payroll_headers), 200)
    assert split_after["coc_exempt"] is True, (
        "certificate issuance must flip the split's coc_exempt flag to true"
    )
