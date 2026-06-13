"""Dispatch, payout-attempt outcomes, and the delivery axis.

Covers the three dispatch preconditions (funded / cleared / recipient verified),
the success bubble onto delivery_status + ledger, and the FAILED-attempt cap.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    setup_corridor, setup_sender, setup_recipient,
    setup_funded_transfer, setup_funded_screened_transfer,
    setup_dispatched_transfer, setup_transfer_with_failed_attempts,
    create_locked_quote, create_transfer_from_quote,
    report_outcome_payload, ledger_entries_for, get_corridor, ledger_net,
    TEST_USERS,
)

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["remittance_agent_headers"]
OFFICER = TEST_USERS["compliance_officer_headers"]
OPERATOR = TEST_USERS["payout_operator_headers"]


def _pending_attempt(api, transfer_id):
    from test_helpers import validate_paginated
    data, _meta = validate_paginated(api.list_payout_attempts(
        OPERATOR, params={"transfer_id": transfer_id, "outcome": "PENDING"}))
    return data[0]


# ─── dispatch requires recipient VERIFIED (cross-entity state dependency) ───

def test_dispatch_with_unverified_recipient_rejected(api):
    """PRD §3.6: "the beneficiary's `kyc_status` must be `VERIFIED` (else
    `ERR_RECIPIENT_NOT_VERIFIED`)."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_recipient_verified
    """
    # Recipient never submits KYC -> UNVERIFIED; transfer is funded + cleared.
    corridor, sender, recipient, quote, transfer = setup_funded_screened_transfer(
        send_principal_minor=50000, recipient_verified=False)
    assert transfer["compliance_status"] == "CLEARED"
    res = api.dispatch_transfer(transfer["id"], OPERATOR)
    validate_error(res, "ERR_RECIPIENT_NOT_VERIFIED")
    after = validate_success(api.get_transfer(transfer["id"], AGENT), 200)
    assert after["delivery_status"] == "PENDING", after["delivery_status"]


def test_dispatch_with_verified_recipient_succeeds(api):
    """PRD §3.6: "A dispatch from `delivery_status` of `PENDING` creates a
    `PayoutAttempt` and moves the transfer to `IN_TRANSIT`."

    Design: Difficulty/cross_entity_state_dependency/dispatch_requires_recipient_verified
    """
    corridor, sender, recipient, quote, transfer = setup_funded_screened_transfer(
        send_principal_minor=50000, recipient_verified=True)
    dispatched = validate_success(api.dispatch_transfer(transfer["id"], OPERATOR), 200)
    assert dispatched["delivery_status"] == "IN_TRANSIT", dispatched["delivery_status"]


# ─── priority pair: forbidden role beats invalid state on dispatch ──────────

def test_agent_dispatch_on_unfunded_transfer_gets_forbidden(api):
    """PRD §3.9: "then that the caller's role is permitted for the endpoint
    (`ERR_FORBIDDEN_FOR_ROLE`); then that every path identifier and body foreign key
    resolves to an existing resource ... then that the target resource is in a state
    from which the requested transition is allowed (`ERR_INVALID_STATE`)."

    Design: Difficulty/priority_pair_validation_conflict/forbidden_role_beats_invalid_state_on_dispatch
    """
    corridor = setup_corridor(rolling_window_cap_minor=4000000)
    sender = setup_sender()
    recipient = setup_recipient(sender["id"])
    quote = create_locked_quote(corridor["id"], sender["id"], 50000)
    transfer = create_transfer_from_quote(quote, recipient["id"])
    # UNFUNDED (invalid state for dispatch) AND caller is RemittanceAgent (not allowed).
    # The auth (role) check wins over the state check.
    res = api.dispatch_transfer(transfer["id"], AGENT)
    validate_error(res, "ERR_FORBIDDEN_FOR_ROLE")
    after = validate_success(api.get_transfer(transfer["id"], AGENT), 200)
    assert after["delivery_status"] == "PENDING", after["delivery_status"]


def test_operator_dispatch_on_unfunded_transfer_gets_not_funded(api):
    """PRD §3.6: "the transfer must be funded (`funding_status` equal to `FUNDED`, else
    `ERR_TRANSFER_NOT_FUNDED`)."

    Design: Difficulty/priority_pair_validation_conflict/forbidden_role_beats_invalid_state_on_dispatch
    """
    corridor = setup_corridor(rolling_window_cap_minor=4000000)
    sender = setup_sender()
    recipient = setup_recipient(sender["id"], verified=True)
    quote = create_locked_quote(corridor["id"], sender["id"], 50000)
    transfer = create_transfer_from_quote(quote, recipient["id"])
    validate_success(api.screen_transfer(transfer["id"], OFFICER), 200)
    # Same UNFUNDED transfer, but now the authorized operator calls: state check fires.
    res = api.dispatch_transfer(transfer["id"], OPERATOR)
    validate_error(res, "ERR_TRANSFER_NOT_FUNDED")


# ─── dispatch under compliance hold (corner: state_machines/validations) ────

def test_dispatch_under_compliance_hold_rejected(api):
    """PRD §3.6: "its `compliance_status` must be `CLEARED` (a transfer still under
    hold yields `ERR_COMPLIANCE_HOLD`)."

    Design: Corner/state_machines/dispatch_under_compliance_hold_rejected
    """
    from test_helpers import setup_held_transfer_with_case
    corridor, sender, recipient, transfer, case = setup_held_transfer_with_case(
        recipient_verified=True)
    assert transfer["compliance_status"] == "HELD"
    res = api.dispatch_transfer(transfer["id"], OPERATOR)
    validate_error(res, "ERR_COMPLIANCE_HOLD")
    after = validate_success(api.get_transfer(transfer["id"], AGENT), 200)
    assert after["delivery_status"] == "PENDING", after["delivery_status"]


# ─── dispatch before funded, role-authorized (corner: state_machines) ───────

def test_dispatch_cleared_but_unfunded_returns_not_funded(api):
    """PRD §3.6: "the transfer must be funded (`funding_status` equal to `FUNDED`, else
    `ERR_TRANSFER_NOT_FUNDED`)."

    Design: Corner/state_machines/dispatch_before_funded_returns_not_funded
    """
    corridor = setup_corridor(rolling_window_cap_minor=4000000)
    sender = setup_sender()
    recipient = setup_recipient(sender["id"], verified=True)
    quote = create_locked_quote(corridor["id"], sender["id"], 50000)
    transfer = create_transfer_from_quote(quote, recipient["id"])
    validate_success(api.screen_transfer(transfer["id"], OFFICER), 200)
    res = api.dispatch_transfer(transfer["id"], OPERATOR)
    validate_error(res, "ERR_TRANSFER_NOT_FUNDED")


# ─── payout success bubble (corner: state_machines) ─────────────────────────

def test_payout_success_marks_delivered_and_credits_ledger(api):
    """PRD §3.6: "A `SUCCEEDED` outcome sets the attempt's `outcome` to `SUCCEEDED`,
    advances the transfer's `delivery_status` to `DELIVERED`, releases the corridor
    reservation by subtracting `send_principal_minor` from the corridor's
    `reserved_minor`, and writes a `RECIPIENT_CREDIT` ledger entry whose `amount_minor`
    is the positive `send_principal_minor`."

    Design: Corner/state_machines/payout_success_bubbles_to_delivered_and_credits_ledger
    """
    corridor, transfer, attempt = setup_dispatched_transfer(send_principal_minor=50000)
    reported = validate_success(api.report_payout_outcome(
        attempt["id"], report_outcome_payload("SUCCEEDED"), OPERATOR), 200)
    assert reported["outcome"] == "SUCCEEDED", reported["outcome"]
    after_t = validate_success(api.get_transfer(transfer["id"], AGENT), 200)
    assert after_t["delivery_status"] == "DELIVERED", after_t["delivery_status"]
    after_c = get_corridor(corridor["id"])
    assert after_c["reserved_minor"] == 0, after_c["reserved_minor"]
    entries = ledger_entries_for(transfer["id"])
    credit = [e for e in entries if e["entry_type"] == "RECIPIENT_CREDIT"]
    assert credit and credit[0]["amount_minor"] == 50000, credit
    # Delivered transfer's ledger nets to exactly 0 (PRD §3.8).
    assert ledger_net(entries) == 0, ledger_net(entries)


# ─── max payout attempts cap (corner: state_machines) ───────────────────────

def test_retry_dispatch_after_two_failures_rejected(api):
    """PRD §3.6: "Dispatching again from `delivery_status` of `FAILED` is permitted
    only while the count of this transfer's `FAILED` payout attempts is below the
    maximum of 2; a retry beyond that is rejected with `ERR_MAX_ATTEMPTS_REACHED`."

    Design: Corner/state_machines/retry_dispatch_after_max_attempts_returns_invalid_state_error
    """
    corridor, transfer = setup_transfer_with_failed_attempts(num_failed=2, send_principal_minor=50000)
    assert transfer["delivery_status"] == "FAILED"
    res = api.dispatch_transfer(transfer["id"], OPERATOR)
    validate_error(res, "ERR_MAX_ATTEMPTS_REACHED")
    after = validate_success(api.get_transfer(transfer["id"], AGENT), 200)
    assert after["delivery_status"] == "FAILED", after["delivery_status"]
