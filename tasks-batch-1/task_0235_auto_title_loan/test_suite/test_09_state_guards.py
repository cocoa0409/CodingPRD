"""State-machine guards: invalid transitions, idempotent re-trigger, precondition
enforcement, terminal lockdown, and a cross-entity lien-filing referential guard."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    setup_finalized_appraisal,
    setup_submitted_application,
    setup_originated_loan,
    file_loan_lien,
    get_loan_lien,
    make_appraiser_headers,
    make_underwriter_headers,
    set_clock,
    CLOCK_ORIGIN,
    create_payment_payload,
    create_title_lien_file_payload,
)

_UW = TEST_USERS["underwriter_headers"]
_APPR = TEST_USERS["appraiser_headers"]
_SERVICER = TEST_USERS["loan_servicer_headers"]
_CLERK = TEST_USERS["title_clerk_headers"]


# ─────────────────────────────────────────────────────────────────────────
# Corner: finalize an already-FINALIZED appraisal -> ERR_INVALID_STATE
# ─────────────────────────────────────────────────────────────────────────
def test_finalize_already_finalized_appraisal_returns_invalid_state(api):
    """PRD §3.2: "Finalizing an appraisal is performed by an Appraiser and is permitted
    only when the appraisal is in DRAFT; an attempt to finalize an appraisal not in
    DRAFT is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/finalize_already_finalized_appraisal_returns_invalid_state
    """
    set_clock(CLOCK_ORIGIN)
    _, _, _, appraisal = setup_finalized_appraisal(appraiser_id="appr-ff")
    res = api.finalize_appraisal(appraisal["id"], make_appraiser_headers("appr-ff"))
    validate_error(res, "ERR_INVALID_STATE")


# ─────────────────────────────────────────────────────────────────────────
# Corner: approve an already-APPROVED application -> ERR_INVALID_STATE
# ─────────────────────────────────────────────────────────────────────────
def test_approve_already_approved_application_returns_invalid_state(api):
    """PRD §3.3: "A request to approve an application that is not SUBMITTED is rejected
    with ERR_INVALID_STATE."

    Design: Corner/state_machines/approve_already_approved_application_returns_invalid_state
    """
    ctx = setup_originated_loan()  # application already APPROVED
    res = api.approve_application(ctx["application"]["id"], make_underwriter_headers("uw-again"))
    validate_error(res, "ERR_INVALID_STATE")


# ─────────────────────────────────────────────────────────────────────────
# Corner: declare-default on a CURRENT loan -> ERR_INVALID_STATE
# ─────────────────────────────────────────────────────────────────────────
def test_declare_default_on_current_loan_returns_invalid_state(api):
    """PRD §3.7: "This is permitted only when the loan's delinquency_status is
    DELINQUENT and its payoff_status is OUTSTANDING; otherwise the request is rejected
    with ERR_INVALID_STATE."

    Design: Corner/state_machines/declare_default_on_current_loan_returns_invalid_state
    """
    ctx = setup_originated_loan()  # delinquency_status CURRENT
    res = api.declare_default(ctx["loan"]["id"], _SERVICER)
    validate_error(res, "ERR_INVALID_STATE")


# ─────────────────────────────────────────────────────────────────────────
# Corner: terminal lockdown — file a RELEASED lien again -> ERR_INVALID_STATE
# ─────────────────────────────────────────────────────────────────────────
def test_file_lien_already_released_terminal_lockdown(api):
    """PRD §3.4: "A filing attempt on a lien that is not PENDING is rejected with
    ERR_INVALID_STATE".
    PRD §3.7: "This payoff cascades: the title lien transitions FILED → RELEASED".

    Design: Corner/state_machines/file_lien_already_released_terminal_lockdown
    """
    ctx = setup_originated_loan()
    loan_id = ctx["loan"]["id"]
    _filed, lien_id = file_loan_lien(loan_id)
    # Full REGULAR payoff releases the lien via cascade.
    validate_success(
        api.create_payment(loan_id, create_payment_payload(600000, "REGULAR"), _SERVICER), 201)
    res = api.file_title_lien(lien_id, create_title_lien_file_payload("DMV-TL-2"), _CLERK)
    validate_error(res, "ERR_INVALID_STATE")


# ─────────────────────────────────────────────────────────────────────────
# Corner: cross-entity referential — file lien after loan REDEEMED
# ─────────────────────────────────────────────────────────────────────────
def test_lien_file_after_redeemed_rejected_referential(api):
    """PRD §3.4: "a filing attempt while the loan's payoff_status is anything other than
    OUTSTANDING is rejected with ERR_LIEN_LOAN_NOT_OUTSTANDING."

    Design: Corner/validations/lien_file_after_redeemed_rejected_referential
    """
    # Clean loan, lien left PENDING. Redeem the clean loan (no repo -> amount == 600000),
    # then attempt to file the still-PENDING lien.
    ctx = setup_originated_loan()
    loan_id = ctx["loan"]["id"]
    lien = get_loan_lien(loan_id)  # PENDING
    validate_success(
        api.create_payment(loan_id, create_payment_payload(600000, "REDEMPTION"), _SERVICER), 201)
    res = api.file_title_lien(lien["id"], create_title_lien_file_payload("DMV-LR-1"), _CLERK)
    validate_error(res, "ERR_LIEN_LOAN_NOT_OUTSTANDING")
