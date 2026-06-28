"""Validation rules and validation-priority conflicts.

Queue A (Difficulty) — rule priority_pair_validation_conflict (role>state, state>fiscal).
Queue B (Corner) — validations section (documents-incomplete, payment-mismatch, rework cap).
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_schedule_and_account, create_account, create_transaction,
    upload_and_verify_required_docs, verify_documents, create_document_payload,
    create_transaction_verified_and_quoted, submit_transaction,
    setup_completed_transaction, setup_rejected_transaction, inject_rejection_round,
    make_account_holder_headers, create_payment_payload, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["intake_clerk_headers"]
ANALYST = TEST_USERS["fee_analyst_headers"]
DISPATCHER = TEST_USERS["runner_dispatcher_headers"]


# ─── priority_pair_validation_conflict ────────────────────────────────

def test_forbidden_role_beats_invalid_state_on_quote(api):
    """PRD §2.6: "Authentication is checked first (ERR_UNAUTHENTICATED), then role
    authorization (ERR_FORBIDDEN_ROLE), then existence of referenced resources
    (ERR_NOT_FOUND), then resource ownership for an AccountHolder
    (ERR_NOT_RESOURCE_OWNER), then whether the target resource is in a state from which
    the requested transition is legal (ERR_INVALID_STATE)."

    Design: Difficulty/priority_pair_validation_conflict/forbidden_role_beats_invalid_state_on_quote
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    # Drive the transaction all the way to SUBMITTED so quoting is both a role violation
    # (IntakeClerk may not quote) and a state violation (SUBMITTED is not a quote state).
    txn, _q = create_transaction_verified_and_quoted(account["id"], "REGISTRATION")
    submit_transaction(txn["id"])
    submitted = get_success_data(api.get_transaction(txn["id"], ANALYST))
    assert submitted["lifecycle_status"] == "SUBMITTED"

    # IntakeClerk (wrong role) quoting a SUBMITTED transaction -> role error wins.
    res = api.quote_transaction(
        txn["id"], {"expected_transaction_version": submitted["version"]}, CLERK)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_invalid_state_beats_credit_limit_on_complete(api):
    """PRD §2.6: "then whether the target resource is in a state from which the requested
    transition is legal (ERR_INVALID_STATE). State-machine eligibility for the lifecycle,
    document, trip, submission, and packet dimensions is therefore evaluated before any
    domain-specific business rule that follows it."
    PRD §3.7: "Completing a transaction is the FeeAnalyst's closing act and is permitted
    only when the transaction's lifecycle_status is APPROVED."

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_credit_limit_on_complete
    """
    schedule, fleet = setup_schedule_and_account(
        account_type="FLEET", state_code="CA",
        account_overrides={"credit_terms": True, "credit_limit_cents": 1})
    # Transaction left in DRAFT (never approved). Completing it is a state violation;
    # the fiscal credit-limit rule would also bite, but state is evaluated first.
    txn = create_transaction(fleet["id"], "REGISTRATION", declared_price_cents=0)

    res = api.complete_transaction(txn["id"], ANALYST)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Corner: validations ──────────────────────────────────────────────

def test_submit_with_incomplete_documents_rejected(api):
    """PRD §3.4: "submitting when the checklist is not fully satisfied is rejected with
    ERR_DOCUMENTS_INCOMPLETE (HTTP 409)."

    Design: Corner/validations/submit_with_incomplete_documents_returns_documents_incomplete
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    txn = create_transaction(account["id"], "REGISTRATION", declared_price_cents=0)
    # Only ID_PROOF verified; INSURANCE missing -> document_status INCOMPLETE.
    doc = get_success_data(api.create_document(
        create_document_payload(txn["id"], "ID_PROOF", file_ref="f1"), CLERK))
    api.verify_document(doc["id"], {"decision": "VERIFIED"}, CLERK)
    after_verify = validate_success(api.verify_documents(txn["id"], CLERK), 200)
    assert after_verify["document_status"] == "INCOMPLETE"
    # Quote it (DRAFT -> QUOTED) so lifecycle is a valid submit state but docs are bad.
    validate_success(api.quote_transaction(
        txn["id"], {"expected_transaction_version": after_verify["version"]}, ANALYST), 200)

    res = api.submit_transaction(txn["id"], CLERK)
    validate_error(res, "ERR_DOCUMENTS_INCOMPLETE", expected_status=409)


def test_payment_amount_mismatch_rejected(api):
    """PRD §3.7: "the amount must equal the total_cents of that transaction's SETTLED fee
    quote; a mismatch, or a kind invalid for the account's terms, is rejected with
    ERR_PAYMENT_AMOUNT_MISMATCH (HTTP 422)."

    Design: Corner/validations/payment_amount_mismatch_returns_422
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    txn, _sub, settled = setup_completed_transaction(account["id"], "REGISTRATION")
    assert settled["total_cents"] == 13000

    holder = make_account_holder_headers(account["id"])
    res = api.create_payment(
        account["id"], create_payment_payload(txn["id"], 9999, "CHARGE"), holder)
    validate_error(res, "ERR_PAYMENT_AMOUNT_MISMATCH", expected_status=422)


def test_rework_limit_reached_rejected(api):
    """PRD §3.4: "the rejection_round is strictly less than the rework cap of three
    rounds; a resubmit attempted at or above three rounds is rejected with
    ERR_REWORK_LIMIT_REACHED (HTTP 409)."

    Design: Corner/validations/rework_limit_reached_returns_error
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    txn, _sub, docs = setup_rejected_transaction(account["id"], "REGISTRATION")
    # Force rejection_round to the cap (3) and re-verify documents to VERIFIED so the
    # only failing precondition is the rework cap.
    inject_rejection_round(txn["id"], 3)
    for doc in docs:
        api.verify_document(doc["id"], {"decision": "VERIFIED"}, CLERK)
    validate_success(api.verify_documents(txn["id"], CLERK), 200)

    res = api.submit_transaction(txn["id"], CLERK)
    validate_error(res, "ERR_REWORK_LIMIT_REACHED", expected_status=409)
