"""State-machine breadth: invalid transitions (re-verify, reject-from-terminal,
send-notice-from-suspended) and initial state.

Corner queue B: state_machines.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_funding_ready, setup_funded_invoice, submit_and_verify_invoice,
    create_relationship, create_approved_client, create_approved_debtor,
    post_collection, create_pending_client,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
UW = TEST_USERS["underwriter_headers"]
FO = TEST_USERS["funding_headers"]
CO = TEST_USERS["collections_headers"]


def test_verify_already_verified_returns_invalid_state(api):
    """PRD §3.4: "Verification requires the invoice to be `SUBMITTED`." PRD §2.6:
    "State validity — the target resource is in a state from which the requested
    transition is defined (`ERR_INVALID_STATE`, HTTP 409)."

    A second verify on a VERIFIED invoice -> ERR_INVALID_STATE.

    Design: Corner/state_machines/sm_verify_from_already_verified_returns_invalid_state
    """
    parties = setup_funding_ready(
        debtor_approve_overrides={"approved_credit_ceiling_cents": 100_000_000,
                                  "verification_required": False})
    invoice = submit_and_verify_invoice(parties["client"]["id"], parties["debtor"]["id"],
                                        invoice_number="INV-IV", face_amount_cents=100000)
    res = api.verify_invoice(invoice["id"],
                             {"method": "WAIVED", "confirmed_amount_cents": 100000}, FO)
    validate_error(res, "ERR_INVALID_STATE")


def test_reject_from_terminal_settled_returns_invalid_state(api):
    """PRD §3.4: "A submitted invoice that should not proceed may instead be
    rejected by the funding officer, moving `SUBMITTED → REJECTED` with no side
    effects." PRD §2.6: "State validity ... (`ERR_INVALID_STATE`, HTTP 409)."

    Rejecting a SETTLED (terminal) invoice -> ERR_INVALID_STATE.

    Design: Corner/state_machines/sm_reject_from_terminal_settled_returns_invalid_state
    """
    ctx = setup_funded_invoice(face_amount_cents=100000, advance_rate_pct=0.85,
                               fee_rate_per_day=0.0005,
                               invoice_overrides={"invoice_number": "INV-TL"})
    inv_id = ctx["invoice"]["id"]
    post_collection(inv_id, ctx["client"]["id"], 100000, "2026-05-21T00:00:00Z")
    settled = validate_success(api.get_invoice(inv_id, FO), 200)
    assert settled["status"] == "SETTLED"
    res = api.reject_invoice(inv_id, FO)
    validate_error(res, "ERR_INVALID_STATE")


def test_client_initial_state_is_pending(api):
    """PRD §3.1: "A new client starts in `PENDING` status with
    `approved_advance_rate_pct`, `credit_limit_cents`,
    `default_concentration_limit_pct`, and `credit_decision_user_id` all unset".

    Design: Corner/state_machines/sm_client_initial_state_pending
    """
    program = get_success_data(api.create_program({"name": "P-INIT"}, ADMIN))
    client = get_success_data(api.create_client(
        {"program_id": program["id"], "legal_name": "InitCo",
         "requested_advance_rate_pct": 0.8}, ADMIN))
    assert client["status"] == "PENDING"
    assert client["approved_advance_rate_pct"] is None
    assert client["credit_limit_cents"] is None


def test_send_notice_from_suspended_returns_invalid_state(api):
    """PRD §3.3: "Sending the notice requires the relationship's `notice_status`
    to be `PENDING`". PRD §2.6: "State validity — the target resource is in a
    state from which the requested transition is defined (`ERR_INVALID_STATE`,
    HTTP 409)."

    send-notice on a SUSPENDED relationship -> ERR_INVALID_STATE.

    Design: Corner/state_machines/sm_send_notice_from_suspended_invalid
    """
    program = get_success_data(api.create_program({"name": "P-SN"}, ADMIN))
    client = create_approved_client(program["id"])
    debtor = create_approved_debtor(program["id"])
    rel = create_relationship(client["id"], debtor["id"], noticed=True)
    validate_success(api.suspend_relationship(rel["id"], FO), 200)
    res = api.send_notice(rel["id"], FO)
    validate_error(res, "ERR_INVALID_STATE")
