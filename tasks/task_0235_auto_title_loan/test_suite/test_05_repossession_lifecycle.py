"""Repossession order lifecycle: branching to SOLD vs CANCELLED, recovery deadline,
grace gate, deficiency, charge-off, and the barred-borrower consequence."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    setup_originated_loan,
    setup_delinquent_loan,
    setup_defaulted_loan,
    setup_recovered_repo,
    setup_charged_off_loan,
    create_borrower,
    create_vehicle,
    create_finalized_appraisal,
    create_submitted_application,
    make_underwriter_headers,
    set_clock,
    create_payment_payload,
    create_assignment_payload,
    create_sale_payload,
    create_application_payload,
)

_SERVICER = TEST_USERS["loan_servicer_headers"]
_RECOVERY = TEST_USERS["recovery_manager_headers"]
_UW = TEST_USERS["underwriter_headers"]


def _list(response):
    body = get_success_data(response)
    return (body, {}) if isinstance(body, list) else (body, {})


# ─────────────────────────────────────────────────────────────────────────
# Branching fork-join: RECOVERED -> SOLD (deficiency, charge-off)
# ─────────────────────────────────────────────────────────────────────────
def test_repossession_recovered_to_sold_records_deficiency_and_charges_off(api):
    """PRD §3.9: "The deficiency_cents is the total owed minus the net proceeds, floored
    at zero".
    PRD §3.9: "Selling the collateral charges off the loan: the loan's payoff dimension
    advances OUTSTANDING → CHARGED_OFF as a cascade."

    Design: Difficulty/non_linear_state_machine/repossession_branching_recovered_to_sold_vs_cancelled
    """
    ctx = setup_recovered_repo()
    repo_id = ctx["repo_order"]["id"]
    loan_id = ctx["loan"]["id"]
    set_clock("2026-03-30T00:00:00.000Z")
    sold = validate_success(
        api.sell_repossession_order(repo_id, create_sale_payload(500000), _RECOVERY), 200)
    assert sold["status"] == "SOLD"
    assert sold["deficiency_cents"] == 195176
    loan = get_success_data(api.get_loan(loan_id, _SERVICER))
    assert loan["payoff_status"] == "CHARGED_OFF"


def test_repossession_recovered_to_cancelled_on_reinstatement(api):
    """PRD §3.7: "When a DEFAULT loan is reinstated ... transitions the active
    repossession order to CANCELLED as a cascade ... advances delinquency_status
    DEFAULT → CURRENT".

    Design: Difficulty/non_linear_state_machine/repossession_branching_recovered_to_sold_vs_cancelled
    """
    ctx = setup_recovered_repo()
    repo_id = ctx["repo_order"]["id"]
    loan_id = ctx["loan"]["id"]
    # In DEFAULT, the reinstatement amount adds the 25000 repo recovery fee:
    # arrears (past-due P+I) + fees + 25000 = 434236 + 25000 = 459236.
    validate_success(
        api.create_payment(loan_id, create_payment_payload(459236, "REINSTATEMENT"), _SERVICER), 201)
    repo = get_success_data(api.get_repossession_order(repo_id, _RECOVERY))
    assert repo["status"] == "CANCELLED"
    loan = get_success_data(api.get_loan(loan_id, _SERVICER))
    assert loan["delinquency_status"] == "CURRENT"


# ─────────────────────────────────────────────────────────────────────────
# Corner: redemption_deadline = recovered_at + grace days
# ─────────────────────────────────────────────────────────────────────────
def test_redemption_deadline_recovered_plus_grace_days(api):
    """PRD §3.9: "sets the redemption_deadline to recovered_at plus the borrower-state
    redemption_grace_days days".

    Design: Corner/calculations/redemption_deadline_recovered_plus_grace_days
    """
    ctx = setup_recovered_repo(recover_clock="2026-03-20T00:00:00.000Z")
    repo = ctx["repo_order"]
    assert repo["redemption_deadline"] == "2026-03-30T00:00:00.000Z"


# ─────────────────────────────────────────────────────────────────────────
# Corner: sale before deadline rejected (redemption grace active)
# ─────────────────────────────────────────────────────────────────────────
def test_redemption_grace_active_blocks_sale(api):
    """PRD §3.9: "the current clock time to be at or after the redemption_deadline (the
    redemption grace must have elapsed; a sale attempted before the deadline is rejected
    with ERR_REDEMPTION_GRACE_ACTIVE)."

    Design: Corner/validations/redemption_grace_active_blocks_sale
    """
    ctx = setup_recovered_repo(recover_clock="2026-03-20T00:00:00.000Z")
    repo_id = ctx["repo_order"]["id"]
    set_clock("2026-03-25T00:00:00.000Z")  # before deadline 2026-03-30
    res = api.sell_repossession_order(repo_id, create_sale_payload(500000), _RECOVERY)
    validate_error(res, "ERR_REDEMPTION_GRACE_ACTIVE")


# ─────────────────────────────────────────────────────────────────────────
# Corner: barred borrower -> new application approve rejected
# ─────────────────────────────────────────────────────────────────────────
def test_barred_borrower_new_application_approve_rejected(api):
    """PRD §3.9: "sets the originating borrower's status to BARRED — a borrower whose
    collateral was sold at a charge-off is barred from having any new application
    approved".
    PRD §3.3: "a BARRED borrower is rejected with ERR_BORROWER_BARRED."

    Design: Corner/validations/barred_borrower_new_application_approve_rejected
    """
    ctx = setup_charged_off_loan()
    borrower_id = ctx["borrower"]["id"]
    # Borrower is now BARRED. Build a fresh appraisal + SUBMITTED application and approve.
    vehicle2 = create_vehicle(borrower_id)
    appr2 = create_finalized_appraisal(vehicle2["id"], appraiser_id="appr-barred-2")
    app2 = create_submitted_application(borrower_id, appr2["id"])
    res = api.approve_application(app2["id"], make_underwriter_headers("uw-barred-2"))
    validate_error(res, "ERR_BORROWER_BARRED")


# ─────────────────────────────────────────────────────────────────────────
# Corner: cross-entity guard — open repo while loan only DELINQUENT
# ─────────────────────────────────────────────────────────────────────────
def test_open_repossession_order_requires_loan_in_default(api):
    """PRD §3.9: "A direct open is rejected with ERR_LOAN_NOT_IN_DEFAULT if the
    referenced loan's delinquency_status is not DEFAULT".

    Design: Difficulty/cross_entity_state_dependency/repo_order_requires_loan_in_default
    """
    ctx = setup_delinquent_loan(install_dev=True)
    loan_id = ctx["loan"]["id"]
    res = api.create_repossession_order({"loan_id": loan_id}, _RECOVERY)
    validate_error(res, "ERR_LOAN_NOT_IN_DEFAULT")


def test_open_repossession_order_on_current_loan_rejected(api):
    """PRD §3.9: "A direct open is rejected with ERR_LOAN_NOT_IN_DEFAULT if the
    referenced loan's delinquency_status is not DEFAULT".

    Design: Difficulty/cross_entity_state_dependency/repo_order_requires_loan_in_default
    """
    ctx = setup_originated_loan()  # delinquency_status CURRENT
    res = api.create_repossession_order({"loan_id": ctx["loan"]["id"]}, _RECOVERY)
    validate_error(res, "ERR_LOAN_NOT_IN_DEFAULT")


# ─────────────────────────────────────────────────────────────────────────
# Corner: second direct repo order while an active order exists
# ─────────────────────────────────────────────────────────────────────────
def test_create_repo_when_active_order_exists_rejected(api):
    """PRD §3.9: "and rejected with ERR_ACTIVE_REPO_EXISTS if a non-terminal
    repossession order already exists for the loan".

    Design: Corner/validations/create_repo_when_active_order_exists_rejected
    """
    ctx = setup_defaulted_loan(install_dev=False)  # cascade already opened an ORDERED order
    loan_id = ctx["loan"]["id"]
    res = api.create_repossession_order({"loan_id": loan_id}, _RECOVERY)
    validate_error(res, "ERR_ACTIVE_REPO_EXISTS")


# ─────────────────────────────────────────────────────────────────────────
# Corner: assignment window range error (window_end == window_start)
# ─────────────────────────────────────────────────────────────────────────
def test_assignment_window_end_not_after_start_range_error(api):
    """PRD §2.6: "a recovery assignment's window_end strictly after its window_start".
    PRD §3.9: "where window_end must be strictly after window_start."

    Design: Corner/validations/assignment_window_end_not_after_start_range_error
    """
    ctx = setup_defaulted_loan(install_dev=False)
    repo_id = ctx["repo_order"]["id"]
    res = api.create_assignment(
        repo_id,
        create_assignment_payload("Agent Z", "2026-03-16T08:00:00.000Z", "2026-03-16T08:00:00.000Z"),
        _RECOVERY)
    validate_error(res, "ERR_VALIDATION_RANGE")
