"""Transitive cascade chains: completion settle->balance->suspend (depth 3), and the
DMV-reject round-bump->documents-incomplete cascade (depth 2).

Queue A (Difficulty) — rule transitive_cascade.
"""
from test_helpers import (
    api_client, validate_success, get_success_data,
    setup_schedule_and_account,
    create_transaction_verified_and_quoted, submit_transaction,
    create_planned_trip, attach_leg, record_decision,
    setup_trip_returned, TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["fee_analyst_headers"]
DISPATCHER = TEST_USERS["runner_dispatcher_headers"]


def _drive_to_approved(account_id, transaction_type="REGISTRATION", **txn_overrides):
    txn, _q = create_transaction_verified_and_quoted(
        account_id, transaction_type, txn_overrides=txn_overrides)
    submission = submit_transaction(txn["id"])
    trip = create_planned_trip()
    attach_leg(trip["id"], submission["id"], trip["version"])
    api_client.dispatch_trip(trip["id"], DISPATCHER)
    api_client.return_trip(trip["id"], DISPATCHER)
    record_decision(submission["id"], "ACCEPTED")
    return get_success_data(api_client.get_transaction(txn["id"], ANALYST))


def test_dmv_reject_bumps_round_then_sets_documents_incomplete(api):
    """PRD §3.4: "the rejection cascades onto the transaction: the lifecycle moves from
    SUBMITTED back to REJECTED, the transaction's rejection_round increments by one, its
    document_status is forced to INCOMPLETE so the documents must be re-verified for
    rework, and its version increments."

    Design: Difficulty/transitive_cascade/dmv_reject_bumps_round_then_sets_documents_incomplete_depth2
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    txn, submission, _trip, _leg = setup_trip_returned(account["id"], "REGISTRATION")
    assert txn["lifecycle_status"] == "SUBMITTED"
    assert txn["document_status"] == "VERIFIED"

    decided = validate_success(api.submission_decision(
        submission["id"], {"outcome": "DMV_REJECTED", "rejection_reason": "Wrong office"},
        DISPATCHER), 200)
    assert decided["submission_status"] == "DMV_REJECTED"

    txn_after = validate_success(api.get_transaction(txn["id"], ANALYST), 200)
    assert txn_after["lifecycle_status"] == "REJECTED"
    assert txn_after["rejection_round"] == 1
    assert txn_after["document_status"] == "INCOMPLETE"


def test_dmv_reject_sets_submission_dmv_rejected(api):
    """PRD §3.4: "On a rejecting decision a rejection_reason must be provided (and is
    stored on the submission); the submission moves to DMV_REJECTED, its leg becomes
    RESOLVED, and the rejection cascades onto the transaction"

    Design: Difficulty/transitive_cascade/dmv_reject_bumps_round_then_sets_documents_incomplete_depth2
    """
    schedule, account = setup_schedule_and_account(account_type="RETAIL", state_code="CA")
    txn, submission, _trip, leg = setup_trip_returned(account["id"], "REGISTRATION")

    decided = validate_success(api.submission_decision(
        submission["id"], {"outcome": "DMV_REJECTED", "rejection_reason": "Illegible"},
        DISPATCHER), 200)
    assert decided["submission_status"] == "DMV_REJECTED"
    leg_after = validate_success(api.get_runner_leg(leg["id"], DISPATCHER), 200)
    assert leg_after["leg_status"] == "RESOLVED"
