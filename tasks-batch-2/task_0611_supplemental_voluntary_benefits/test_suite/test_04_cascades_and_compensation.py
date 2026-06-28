"""Transitive cascades (terminate-employee, disburse) and compensating ledger
reversals (void, return) plus the conserved deduction aggregate.

Difficulty queue A: transitive_cascade, compensating_invariant.
Corner queue B: state_machines (disbursement return).
"""
from test_helpers import (
    validate_success,
    validate_paginated,
    TEST_USERS,
    fixtures,
)

_ADMIN = TEST_USERS["benefits_admin_headers"]
_ADJUSTER = TEST_USERS["claims_adjuster_headers"]
_EMPLOYEE = TEST_USERS["employee_headers"]


# ---------------------------------------------------------------------------
# transitive_cascade / terminate_employee_cascades_enrollment_then_election
# ---------------------------------------------------------------------------
def test_terminate_employee_cascades_to_enrollment_and_election(api):
    """PRD §3.6: "When a `BenefitsAdmin` terminates an `Employee`, the employee's
    `employment_status` becomes `TERMINATED`, each of that employee's `ACTIVE`
    enrollments undergoes the same `ACTIVE`-to-`TERMINATED` transition with all of
    its side effects, the governing locked elections are revoked, and the
    employee's aggregate deduction total is recomputed."

    Design: Difficulty/transitive_cascade/terminate_employee_cascades_enrollment_then_election
    """
    emp, prod, period, employee, enr, items = fixtures.create_active_enrollment(
        enrollment_overrides={"pretax": True}
    )
    validate_success(api.terminate_employee(employee["id"], _ADMIN))
    edata = validate_success(api.get_employee(employee["id"], _ADMIN))
    assert edata["employment_status"] == "TERMINATED"
    assert edata["total_weekly_deduction_cents"] == 0
    enr_data = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    assert enr_data["lifecycle_status"] == "TERMINATED"
    assert enr_data["funding_status"] == "LAPSED"


def test_terminate_employee_revokes_locked_section125_election(api):
    """PRD §3.6: "if a `LOCKED` `Section125Election` governs this enrollment, it is
    transitioned to `REVOKED` with its `qualifying_event` set to `TERMINATION`"

    Design: Difficulty/transitive_cascade/terminate_employee_cascades_enrollment_then_election
    """
    emp, prod, period, employee, enr, items = fixtures.create_active_enrollment(
        enrollment_overrides={"pretax": True}
    )
    api.terminate_employee(employee["id"], _ADMIN)
    rows, _meta = validate_paginated(
        api.list_section125_elections(_ADMIN, params={"enrollment_id": enr["id"]})
    )
    assert len(rows) == 1
    assert rows[0]["status"] == "REVOKED"
    assert rows[0]["qualifying_event"] == "TERMINATION"


# ---------------------------------------------------------------------------
# transitive_cascade / disburse_cascades_disbursement_then_claim_paid
# ---------------------------------------------------------------------------
def test_disburse_creates_settled_disbursement(api):
    """PRD §3.9: "The disbursement is created and immediately settles: its
    `status` is `SETTLED`, and as its settlement side effect it sets the parent
    claim's `status` to `PAID` and the claim's `paid_cents` to the disbursement's
    `amount_cents`."

    Design: Difficulty/transitive_cascade/disburse_cascades_disbursement_then_claim_paid
    """
    emp, prod, period, employee, enr, acct, items = (
        fixtures.setup_funded_enrollment_with_account(
            schedule_items=[{"event_code": "FRACTURE", "flat_benefit_cents": 200000}]
        )
    )
    claim = fixtures.file_review_approve_claim(
        enr["id"], acct["id"], "FRACTURE", "2026-03-20T00:00:00Z"
    )
    disb = validate_success(api.disburse_claim(claim["id"], _ADJUSTER), 201)
    assert disb["status"] == "SETTLED"
    assert disb["amount_cents"] == 200000


def test_disburse_cascades_claim_to_paid(api):
    """PRD §3.9: "as its settlement side effect it sets the parent claim's
    `status` to `PAID` and the claim's `paid_cents` to the disbursement's
    `amount_cents`."

    Design: Difficulty/transitive_cascade/disburse_cascades_disbursement_then_claim_paid
    """
    emp, prod, period, employee, enr, acct, items = (
        fixtures.setup_funded_enrollment_with_account(
            schedule_items=[{"event_code": "FRACTURE", "flat_benefit_cents": 200000}]
        )
    )
    claim = fixtures.file_review_approve_claim(
        enr["id"], acct["id"], "FRACTURE", "2026-03-20T00:00:00Z"
    )
    api.disburse_claim(claim["id"], _ADJUSTER)
    cdata = validate_success(api.get_claim(claim["id"], _ADMIN))
    assert cdata["status"] == "PAID"
    assert cdata["paid_cents"] == 200000


# ---------------------------------------------------------------------------
# compensating_invariant / claim_void_conserves_benefit_paid_cents
# ---------------------------------------------------------------------------
def test_void_moves_claim_to_voided(api):
    """PRD §3.9: "an `APPROVED` claim with no settled disbursement may be
    **voided** by a `ClaimsAdjuster`, moving it from `APPROVED` to the terminal
    `VOIDED` state"

    Design: Difficulty/compensating_invariant/claim_void_conserves_benefit_paid_cents
    """
    emp, prod, period, employee, enr, acct, items = (
        fixtures.setup_funded_enrollment_with_account(
            schedule_items=[{"event_code": "FRACTURE", "flat_benefit_cents": 200000}]
        )
    )
    claim = fixtures.file_review_approve_claim(
        enr["id"], acct["id"], "FRACTURE", "2026-03-20T00:00:00Z"
    )
    voided = validate_success(api.void_claim(claim["id"], _ADJUSTER))
    assert voided["status"] == "VOIDED"


def test_void_credits_back_benefit_paid_cents(api):
    """PRD §3.9: "it performs the same compensating credit-back of
    `benefit_paid_cents` (wellness excluded) and recompute of
    `benefit_remaining_cents`."

    Design: Difficulty/compensating_invariant/claim_void_conserves_benefit_paid_cents
    """
    emp, prod, period, employee, enr, acct, items = (
        fixtures.setup_funded_enrollment_with_account(
            schedule_items=[{"event_code": "FRACTURE", "flat_benefit_cents": 200000}]
        )
    )
    claim = fixtures.file_review_approve_claim(
        enr["id"], acct["id"], "FRACTURE", "2026-03-20T00:00:00Z"
    )
    api.void_claim(claim["id"], _ADJUSTER)
    data = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    assert data["benefit_paid_cents"] == 0
    assert data["benefit_remaining_cents"] == 500000


# ---------------------------------------------------------------------------
# compensating_invariant / enrollment_terminate_conserves_total_weekly_deduction
# ---------------------------------------------------------------------------
def test_activate_adds_weekly_deduction_to_employee_total(api):
    """PRD §3.6: "On a successful activation the system recomputes the employee's
    `total_weekly_deduction_cents`, adding this enrollment's
    `weekly_deduction_cents` into the aggregate."

    Design: Difficulty/compensating_invariant/enrollment_terminate_conserves_total_weekly_deduction
    """
    emp, prod, period, employee, enr, items = fixtures.create_active_enrollment(
        product_overrides={"weekly_premium_cents": 1200, "eoi_surcharge_bps": 0}
    )
    data = validate_success(api.get_employee(employee["id"], _ADMIN))
    assert data["total_weekly_deduction_cents"] == 1200


def test_terminate_restores_employee_total_to_zero(api):
    """PRD §3.6: "the employee's `total_weekly_deduction_cents` is recomputed,
    removing this enrollment's `weekly_deduction_cents` from the aggregate"

    Design: Difficulty/compensating_invariant/enrollment_terminate_conserves_total_weekly_deduction
    """
    emp, prod, period, employee, enr, items = fixtures.create_active_enrollment(
        product_overrides={"weekly_premium_cents": 1200, "eoi_surcharge_bps": 0}
    )
    api.terminate_enrollment(enr["id"], _ADMIN)
    enr_data = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    assert enr_data["lifecycle_status"] == "TERMINATED"
    emp_data = validate_success(api.get_employee(employee["id"], _ADMIN))
    assert emp_data["total_weekly_deduction_cents"] == 0


# ---------------------------------------------------------------------------
# Corner: state_machines / disbursement_return_reverts_claim_to_approved
# ---------------------------------------------------------------------------
def test_disbursement_return_reverts_claim_and_ledger(api):
    """PRD §3.9: "an ACH **return** on a `SETTLED` disbursement is recorded by a
    `ClaimsAdjuster`, moving the disbursement from `SETTLED` to the terminal
    `RETURNED` state (permitted only from `SETTLED`); the return credits the
    enrollment's `benefit_paid_cents` back by the disbursement's `amount_cents`
    (wellness excluded), recomputes `benefit_remaining_cents`, sets the parent
    claim's `status` back to `APPROVED`, and resets the claim's `paid_cents` to 0"

    Design: Corner/state_machines/disbursement_return_reverts_claim_to_approved
    """
    emp, prod, period, employee, enr, acct, items = (
        fixtures.setup_funded_enrollment_with_account(
            schedule_items=[{"event_code": "FRACTURE", "flat_benefit_cents": 200000}]
        )
    )
    claim, disb = fixtures.file_approve_disburse_claim(
        enr["id"], acct["id"], "FRACTURE", "2026-03-20T00:00:00Z"
    )
    returned = validate_success(api.return_disbursement(disb["id"], _ADJUSTER))
    assert returned["status"] == "RETURNED"
    cdata = validate_success(api.get_claim(claim["id"], _ADMIN))
    assert cdata["status"] == "APPROVED"
    assert cdata["paid_cents"] == 0
    edata = validate_success(api.get_enrollment(enr["id"], _ADMIN))
    assert edata["benefit_paid_cents"] == 0
