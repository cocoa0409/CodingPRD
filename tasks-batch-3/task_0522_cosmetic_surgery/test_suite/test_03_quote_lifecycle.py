"""Quote and consultation state machine: initial states, present/accept/reject
branching, terminal lockdown, empty-quote and open-quote guards."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS, PROC_A,
    create_procedure, create_patient, create_completed_consultation,
    create_draft_quote, create_presented_quote,
    create_consent_payload, create_line_item_payload,
)

FRONT = TEST_USERS["front_desk_headers"]
BILLING = TEST_USERS["billing_headers"]


def test_consultation_starts_scheduled(api):
    """PRD §3.2: "The consultation begins in SCHEDULED."

    Design: Corner/state_machines/consultation_initial_state_scheduled
    """
    patient = create_patient()
    resp = api.create_consultation(
        {"patient_id": patient["id"], "surgeon_user_id": "surgeon-1",
         "chief_complaint": "nose"}, FRONT)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"


def test_accept_draft_quote_returns_invalid_state(api):
    """PRD §3.3: "Accepting a presented quote is likewise a FrontDeskCoordinator action,
    moving it from PRESENTED to ACCEPTED ... and the quote must currently be PRESENTED
    (otherwise ERR_INVALID_STATE)."

    Design: Corner/state_machines/quote_accept_from_draft_returns_invalid_state
    """
    procA = create_procedure(**PROC_A)
    quote, _cons, _pat, _lis = create_draft_quote([procA["id"]])
    resp = api.accept_quote(quote["id"], FRONT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_reject_already_rejected_quote_returns_invalid_state(api):
    """PRD §3.3: "A presented quote may instead be rejected by a FrontDeskCoordinator,
    moving it from PRESENTED to REJECTED; this requires the quote to be PRESENTED
    (otherwise ERR_INVALID_STATE) ... REJECTED and EXPIRED are terminal states for a
    quote."

    Design: Corner/state_machines/quote_reject_from_rejected_terminal_lockdown
    """
    procA = create_procedure(**PROC_A)
    quote, _cons, _pat, _lis = create_presented_quote([procA["id"]], sign_consent=False)
    get_success_data(api.reject_quote(quote["id"], FRONT))
    resp = api.reject_quote(quote["id"], FRONT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_close_consultation_blocked_by_presented_quote(api):
    """PRD §3.2: "Closing is blocked, however, if any QuotePackage on that consultation
    is still in PRESENTED status; such an attempt is rejected with ERR_OPEN_QUOTE_EXISTS."

    Design: Corner/state_machines/consultation_close_blocked_by_presented_quote
    """
    procA = create_procedure(**PROC_A)
    quote, cons, _pat, _lis = create_presented_quote([procA["id"]], sign_consent=False)
    resp = api.close_consultation(cons["id"], FRONT)
    validate_error(resp, ApiErrorId.ERR_OPEN_QUOTE_EXISTS, 409)


def test_empty_quote_cannot_be_presented(api):
    """PRD §3.3: "Presenting the quote is a FrontDeskCoordinator action that moves it
    from DRAFT to PRESENTED. It requires the quote to currently be DRAFT (otherwise
    ERR_INVALID_STATE) and to have at least one line item (otherwise ERR_EMPTY_QUOTE)."

    Design: Difficulty/boundary_precision_check/boundary_empty_quote_cannot_present
    """
    patient = create_patient()
    cons = create_completed_consultation(patient["id"])
    quote = get_success_data(api.create_quote_package({"consultation_id": cons["id"]}, FRONT))
    resp = api.present_quote(quote["id"], FRONT)
    validate_error(resp, ApiErrorId.ERR_EMPTY_QUOTE, 409)


def test_quote_with_one_line_can_present_boundary(api):
    """PRD §3.3: "It requires the quote to currently be DRAFT (otherwise
    ERR_INVALID_STATE) and to have at least one line item (otherwise ERR_EMPTY_QUOTE)."

    Design: Difficulty/boundary_precision_check/boundary_empty_quote_cannot_present
    """
    procA = create_procedure(**PROC_A)
    quote, _cons, _pat, _lis = create_draft_quote([procA["id"]])
    resp = api.present_quote(quote["id"], FRONT)
    data = validate_success(resp, 200)
    assert data["status"] == "PRESENTED"


def test_reject_arm_voids_submitted_financing(api):
    """PRD §3.3: "A presented quote may instead be rejected by a FrontDeskCoordinator,
    moving it from PRESENTED to REJECTED ... Both rejection and expiry carry the same
    cascade: any FinancingApplication on the quote that is still SUBMITTED is
    transitioned to VOIDED."

    Design: Difficulty/non_linear_state_machine/nonlinear_quote_branching_accept_vs_reject
    """
    procA = create_procedure(**PROC_A)
    quote, _cons, _pat, _lis = create_presented_quote([procA["id"]], sign_consent=False)
    fin = get_success_data(api.submit_financing(
        {"quote_package_id": quote["id"], "lender": "CHERRY",
         "requested_amount_cents": 100000}, BILLING))
    rejected = get_success_data(api.reject_quote(quote["id"], FRONT))
    assert rejected["status"] == "REJECTED"
    fin_after = get_success_data(api.get_financing(fin["id"], FRONT))
    assert fin_after["status"] == "VOIDED"


def test_accept_arm_converts_parent_consultation(api):
    """PRD §3.3: "When acceptance succeeds, two side effects fire: the parent
    Consultation transitions from COMPLETED to CONVERTED, and the quote's
    balance_due_cents is recomputed."

    Design: Difficulty/non_linear_state_machine/nonlinear_quote_branching_accept_vs_reject
    """
    procA = create_procedure(**PROC_A)
    quote, cons, _pat, _lis = create_presented_quote(
        [procA["id"]], deposit_cents=170000, sign_consent=True)
    accepted = get_success_data(api.accept_quote(quote["id"], FRONT))
    assert accepted["status"] == "ACCEPTED"
    cons_after = get_success_data(api.get_consultation(cons["id"], FRONT))
    assert cons_after["status"] == "CONVERTED"
