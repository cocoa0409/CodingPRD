"""Workflow state machines: the rework cycle, the runner-trip fork-join, document
transitions, initial states, idempotency, and invalid/terminal transitions.

Queue A (Difficulty) — rules non_linear_state_machine, boundary_precision_check
(dispatch empty trip).
Queue B (Corner) — state_machines section.
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_schedule_and_account, create_account, create_transaction,
    upload_and_verify_required_docs, verify_documents,
    create_planned_trip, attach_leg, submit_transaction, record_decision,
    create_transaction_verified_and_quoted, setup_rejected_transaction,
    re_verify_and_requote, create_document_payload, set_clock,
    create_runner_trip_payload, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["intake_clerk_headers"]
ANALYST = TEST_USERS["fee_analyst_headers"]
DISPATCHER = TEST_USERS["runner_dispatcher_headers"]


# ─── non_linear_state_machine: rework cycle ───────────────────────────

def test_rework_cycle_rejected_back_to_submitted(api):
    """PRD §3.4: "A successful rework supersedes the prior submission (setting its
    submission_status to SUPERSEDED), creates a fresh QUEUED submission, advances the
    lifecycle from REJECTED back to SUBMITTED, and increments the transaction's version."

    Design: Difficulty/non_linear_state_machine/transaction_rework_cycle_rejected_back_to_submitted
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    txn, sub1, docs = setup_rejected_transaction(account["id"], "REGISTRATION")
    assert txn["lifecycle_status"] == "REJECTED"
    assert txn["rejection_round"] == 1

    re_verify_and_requote(txn["id"], docs)
    sub2 = validate_success(api.submit_transaction(txn["id"], CLERK), 201)

    txn_after = validate_success(api.get_transaction(txn["id"], ANALYST), 200)
    assert txn_after["lifecycle_status"] == "SUBMITTED"  # re-entered after the cycle
    assert txn_after["rejection_round"] == 1

    sub1_after = get_success_data(api.get_submission(sub1["id"], DISPATCHER))
    sub2_after = get_success_data(api.get_submission(sub2["id"], DISPATCHER))
    assert sub1_after["submission_status"] == "SUPERSEDED"
    assert sub2_after["submission_status"] == "QUEUED"


def test_rework_increments_rejection_round_on_first_reject(api):
    """PRD §3.4: "the rejection cascades onto the transaction: the lifecycle moves from
    SUBMITTED back to REJECTED, the transaction's rejection_round increments by one, its
    document_status is forced to INCOMPLETE so the documents must be re-verified for
    rework, and its version increments."

    Design: Difficulty/non_linear_state_machine/transaction_rework_cycle_rejected_back_to_submitted
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    txn, sub1, docs = setup_rejected_transaction(account["id"], "REGISTRATION")
    assert txn["lifecycle_status"] == "REJECTED"
    assert txn["rejection_round"] == 1
    assert txn["document_status"] == "INCOMPLETE"


# ─── non_linear_state_machine: fork-join ──────────────────────────────

def _drive_two_submissions(account_id):
    """Two REGISTRATION transactions each driven to a QUEUED submission. Returns
    (subA, subB)."""
    _txnA, _qa = create_transaction_verified_and_quoted(account_id, "REGISTRATION", vin="1HGCM82633A004352")
    subA = submit_transaction(_txnA["id"])
    _txnB, _qb = create_transaction_verified_and_quoted(account_id, "REGISTRATION", vin="2HGCM82633A004353")
    subB = submit_transaction(_txnB["id"])
    return subA, subB


def test_dispatch_forks_all_legs_then_close_join_blocks(api):
    """PRD §3.4: "Dispatching a PLANNED trip that carries at least one leg fans out:
    every attached leg advances to FILED, the trip moves to DISPATCHED, and the trip's
    version increments."
    PRD §3.4: "Closing a RETURNED trip moves it to CLOSED and bumps its version, but is
    permitted only once every attached leg's leg_status is RESOLVED — the join condition
    that all branches have completed."

    Design: Difficulty/non_linear_state_machine/runnertrip_fork_join_dispatch_and_close
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    subA, subB = _drive_two_submissions(account["id"])

    trip = create_planned_trip(capacity=5)
    legA = attach_leg(trip["id"], subA["id"], trip["version"])
    trip_v1 = get_success_data(api.get_runner_trip(trip["id"], DISPATCHER))["version"]
    legB = attach_leg(trip["id"], subB["id"], trip_v1)

    validate_success(api.dispatch_trip(trip["id"], DISPATCHER), 200)

    # Fork: after the single dispatch both legs are FILED.
    legs_data, _m = get_success_data_legs(api, trip["id"])
    statuses = {l["id"]: l["leg_status"] for l in legs_data}
    assert statuses[legA["id"]] == "FILED"
    assert statuses[legB["id"]] == "FILED"

    api.return_trip(trip["id"], DISPATCHER)
    # Resolve only leg A's submission (ACCEPTED); leg B stays FILED.
    record_decision(subA["id"], "ACCEPTED")

    # Join not satisfied: close is rejected because leg B is not RESOLVED.
    close_res = api.close_trip(trip["id"], DISPATCHER)
    validate_error(close_res, "ERR_INVALID_STATE", expected_status=409)

    trip_after = validate_success(api.get_runner_trip(trip["id"], DISPATCHER), 200)
    assert trip_after["trip_status"] == "RETURNED"


def get_success_data_legs(api, trip_id):
    """Helper: fetch a trip's legs as a list."""
    from test_helpers import validate_paginated
    return validate_paginated(api.list_trip_legs(trip_id, DISPATCHER))


# ─── boundary_precision_check: dispatch empty trip ────────────────────

def test_dispatch_empty_trip_rejected(api):
    """PRD §3.4: "Dispatching a PLANNED trip that carries at least one leg fans out"
    PRD §2.6: "then whether the target resource is in a state from which the requested
    transition is legal (ERR_INVALID_STATE)."

    Design: Difficulty/boundary_precision_check/dispatch_empty_trip_zero_legs_rejected
    """
    set_clock()
    trip = validate_success(api.create_runner_trip(
        create_runner_trip_payload(dmv_office_code="CA-DMV-09", capacity=5), DISPATCHER), 201)
    assert trip["assigned_leg_count"] == 0

    res = api.dispatch_trip(trip["id"], DISPATCHER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    trip_after = validate_success(api.get_runner_trip(trip["id"], DISPATCHER), 200)
    assert trip_after["trip_status"] == "PLANNED"


def test_dispatch_empty_trip_no_transition(api):
    """PRD §3.4: "a new trip begins with trip_status of PLANNED and an assigned_leg_count
    of zero"
    PRD §3.4: "Dispatching a PLANNED trip that carries at least one leg fans out: every
    attached leg advances to FILED, the trip moves to DISPATCHED, and the trip's version
    increments."

    Design: Difficulty/boundary_precision_check/dispatch_empty_trip_zero_legs_rejected
    """
    set_clock()
    trip = validate_success(api.create_runner_trip(
        create_runner_trip_payload(dmv_office_code="CA-DMV-08", capacity=3), DISPATCHER), 201)
    res = api.dispatch_trip(trip["id"], DISPATCHER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    trip_after = validate_success(api.get_runner_trip(trip["id"], DISPATCHER), 200)
    assert trip_after["trip_status"] == "PLANNED"
    assert trip_after["assigned_leg_count"] == 0


# ─── Corner: state_machines ───────────────────────────────────────────

def test_submit_from_draft_without_quote_rejected(api):
    """PRD §3.4: "Submission is permitted only when the transaction's lifecycle_status is
    QUOTED, its document_status is VERIFIED, its active_quote_id is not null, and the
    owning account's status is ACTIVE"

    Design: Corner/state_machines/submit_from_draft_without_quote_returns_invalid_state
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    txn = create_transaction(account["id"], "REGISTRATION", declared_price_cents=0)
    upload_and_verify_required_docs(txn["id"], "REGISTRATION")
    verify_documents(txn["id"])  # document_status VERIFIED but never quoted -> still DRAFT

    res = api.submit_transaction(txn["id"], CLERK)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_cancel_from_cancelled_terminal_rejected(api):
    """PRD §2.8: "it begins at DRAFT, and COMPLETED and CANCELLED are terminal."
    PRD §3.9: "Attempting any cancellation from a lifecycle state outside the permitted
    set is rejected with ERR_INVALID_STATE (HTTP 409)."

    Design: Corner/state_machines/cancel_from_cancelled_terminal_lockdown_returns_invalid_state
    """
    from test_helpers import make_account_holder_headers
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    txn = create_transaction(account["id"], "REGISTRATION", declared_price_cents=0)
    holder = make_account_holder_headers(account["id"])
    validate_success(api.cancel_transaction(txn["id"], holder), 200)

    res = api.cancel_transaction(txn["id"], holder)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_new_transaction_starts_draft_collecting(api):
    """PRD §3.2: "A newly opened transaction begins with lifecycle_status of DRAFT and
    document_status of COLLECTING."

    Design: Corner/state_machines/new_transaction_starts_in_draft_collecting
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    txn = create_transaction(account["id"], "REGISTRATION", declared_price_cents=0)
    fetched = validate_success(api.get_transaction(txn["id"], ANALYST), 200)
    assert fetched["lifecycle_status"] == "DRAFT"
    assert fetched["document_status"] == "COLLECTING"


def test_verify_documents_idempotent_incomplete(api):
    """PRD §3.2: "That evaluation drives the document_status dimension and is
    deterministic: the same set of documents always yields the same outcome."

    Design: Corner/state_machines/verify_documents_idempotent_same_set_same_status
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    txn = create_transaction(account["id"], "REGISTRATION", declared_price_cents=0)
    # Only ID_PROOF uploaded+verified; INSURANCE still missing.
    doc = get_success_data(api.create_document(
        create_document_payload(txn["id"], "ID_PROOF", file_ref="f1"), CLERK))
    api.verify_document(doc["id"], {"decision": "VERIFIED"}, CLERK)

    first = validate_success(api.verify_documents(txn["id"], CLERK), 200)
    assert first["document_status"] == "INCOMPLETE"
    second = validate_success(api.verify_documents(txn["id"], CLERK), 200)
    assert second["document_status"] == "INCOMPLETE"


def test_document_reject_then_reset_cycle(api):
    """PRD §3.2: "Verifying moves a PENDING document to VERIFIED; rejecting moves it to
    REJECTED (for example, when the scan is illegible); and a reset moves a REJECTED
    document back to PENDING after the customer re-uploads."

    Design: Corner/state_machines/document_reject_then_reset_cycle
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    txn = create_transaction(account["id"], "REGISTRATION", declared_price_cents=0)
    doc = get_success_data(api.create_document(
        create_document_payload(txn["id"], "ID_PROOF", file_ref="f1"), CLERK))

    rejected = validate_success(api.verify_document(doc["id"], {"decision": "REJECTED"}, CLERK), 200)
    assert rejected["doc_status"] == "REJECTED"
    reset = validate_success(api.verify_document(doc["id"], {"decision": "RESET"}, CLERK), 200)
    assert reset["doc_status"] == "PENDING"
