"""Annual operating budget lifecycle and budget-variance arithmetic."""
from test_helpers import (
    validate_success, validate_error,
    create_budget, setup_active_agreement, setup_approved_budget,
    setup_owner_and_aircraft,
    post_expense, generate_statement, create_budget_payload,
    make_owner_headers, TEST_USERS,
)

AE = TEST_USERS["account_executive_headers"]


def test_budget_reject_revise_resubmit_cycle(api):
    """PRD §3.2: "A `REJECTED` budget is not terminal. When the
    `AccountExecutive` revises any of the six amount fields, the budget
    reopens: the supplied amounts replace the stored ones, `rejection_reason`
    is cleared, and the budget returns to `DRAFT`, ready to be submitted
    again."

    Design: Corner/state_machines/budget_reject_revise_resubmit_cycle
    """
    scenario = setup_active_agreement(tail_number="N280JX")
    aircraft_id = scenario["aircraft"]["id"]
    owner_id = scenario["owner"]["id"]

    budget = create_budget(aircraft_id, fiscal_year=2026)
    validate_success(api.submit_budget(budget["id"], AE), 200)
    rejected = validate_success(
        api.reject_budget(budget["id"], {"reason": "fuel too low"},
                          make_owner_headers(owner_id)),
        200,
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "fuel too low"

    revised = validate_success(
        api.patch_budget(budget["id"], {"fuel_cents": 1440000}, AE), 200
    )
    assert revised["status"] == "DRAFT", (
        f"revision should reopen to DRAFT, got {revised['status']}"
    )
    assert revised["fuel_cents"] == 1440000
    assert revised.get("rejection_reason") is None, "rejection_reason must be cleared"

    validate_success(api.submit_budget(budget["id"], AE), 200)
    approved = validate_success(
        api.approve_budget(budget["id"], make_owner_headers(owner_id)), 200
    )
    assert approved["status"] == "APPROVED"


def test_duplicate_budget_year_rejected(api):
    """PRD §3.2: "At most one budget may exist per aircraft and fiscal year; a
    duplicate is rejected with `ERR_BUDGET_YEAR_EXISTS`."

    Design: Corner/validations/duplicate_budget_year_rejected
    """
    _owner, aircraft = setup_owner_and_aircraft(tail_number="N370JX")
    create_budget(aircraft["id"], fiscal_year=2026)
    res = api.create_budget(
        create_budget_payload(
            aircraft["id"], fiscal_year=2026, fuel_cents=1, maintenance_cents=1,
            crew_cents=1, hangar_cents=1, insurance_cents=1, other_cents=1,
        ),
        AE,
    )
    validate_error(res, "ERR_BUDGET_YEAR_EXISTS", expected_status=409)


def test_statement_budget_variance_with_approved_budget(api):
    """PRD §3.8: "Otherwise the annual total is the sum of the budget's six
    lines, the monthly share is that annual total divided by twelve and rounded
    half up to integer cents, and `budget_variance_cents` is the
    `accrual_total_cents` minus that monthly share."

    Design: Corner/calculations/statement_budget_variance_with_approved_budget
    """
    scenario = setup_active_agreement(tail_number="N330JX")
    aircraft_id = scenario["aircraft"]["id"]
    owner_id = scenario["owner"]["id"]
    # Annual total 1200000+960000+2400000+600000+480000+240000 == 5880000;
    # monthly share round_half_up(5880000/12) == 490000.
    setup_approved_budget(aircraft_id, owner_id, fiscal_year=2026)
    post_expense(aircraft_id, category="FUEL", amount_cents=250000,
                 service_date="2026-08-05", paid_date="2026-08-07")

    statement = generate_statement(aircraft_id, period="2026-08")
    assert statement["accrual_total_cents"] == 250000
    assert statement["budget_variance_cents"] == -240000, (
        f"variance should be 250000 - 490000 = -240000, got "
        f"{statement['budget_variance_cents']}"
    )


def test_statement_budget_variance_null_without_approved_budget(api):
    """PRD §3.8: "The platform finds the `APPROVED` `OperatingBudget` for the
    statement's aircraft whose `fiscal_year` equals the year of the period
    start; if none exists, `budget_variance_cents` is null."

    Design: Corner/calculations/statement_budget_variance_null_without_approved_budget
    """
    scenario = setup_active_agreement(tail_number="N340JX")
    aircraft_id = scenario["aircraft"]["id"]
    budget = create_budget(aircraft_id, fiscal_year=2026)
    validate_success(api.submit_budget(budget["id"], AE), 200)  # SUBMITTED only
    post_expense(aircraft_id, category="FUEL", amount_cents=250000,
                 service_date="2026-08-05", paid_date="2026-08-07")

    statement = generate_statement(aircraft_id, period="2026-08")
    assert statement["accrual_total_cents"] == 250000
    assert statement["budget_variance_cents"] is None, (
        f"no APPROVED budget exists, variance must be null, got "
        f"{statement['budget_variance_cents']}"
    )
