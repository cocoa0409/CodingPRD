"""Corner-queue tests: state-machine preconditions, invalid transitions,
idempotency, and side effects (activation, completion, drop, lawsuit dismissal)."""
import pytest
from test_helpers import (
    ApiErrorId, TEST_USERS, make_client_headers, validate_success, validate_error,
    get_success_data, create_lawsuit_payload,
    set_clock, create_client, create_program, create_debt, create_offer,
)

ADMIN = TEST_USERS["program_admin_headers"]
AGENT = TEST_USERS["negotiation_agent_headers"]


def test_activate_with_no_enrolled_debt_returns_no_enrolled_debts(api):
    """PRD §3.4: "It further requires that the program hold at least one debt in `ENROLLED` status; with no enrolled debt the activation is rejected with `ERR_NO_ENROLLED_DEBTS` (HTTP 409)."

    Design: Corner/state_machines/activate_program_with_no_enrolled_debt_returns_no_enrolled_debts
    """
    client = create_client(full_name="C", email="c5@x.com", state_code="CA")
    program = create_program(client["id"], monthly_deposit_amount=600)
    res = api.activate_program(program["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_NO_ENROLLED_DEBTS)


def test_activate_already_active_returns_invalid_state(api):
    """PRD §3.4: "Activation requires the program to currently be in `ENROLLING`; an attempt from any other phase is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/activate_already_active_program_returns_invalid_state
    """
    client = create_client(full_name="C", email="c6@x.com", state_code="CA")
    program = create_program(client["id"], monthly_deposit_amount=600)
    create_debt(program["id"], creditor_name="Cred", account_number="AA-1",
               original_balance=5000)
    get_success_data(api.activate_program(program["id"], ADMIN))
    res = api.activate_program(program["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_reject_already_rejected_offer_returns_invalid_state(api):
    """PRD §3.6: "A `NegotiationAgent` rejects a `PENDING` offer, moving it to `REJECTED`; rejection requires the offer to be `PENDING`, otherwise `ERR_INVALID_STATE`."

    Design: Corner/state_machines/reject_already_rejected_offer_returns_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(full_name="C", email="c7@x.com", state_code="CA")
    program = create_program(client["id"], monthly_deposit_amount=600)
    debt = create_debt(program["id"], creditor_name="Cred", account_number="RR-1",
                      original_balance=5000)
    get_success_data(api.activate_program(program["id"], ADMIN))
    offer = create_offer(program["id"], debt["id"], offer_pct=0.40,
                        due_date="2026-12-01T00:00:00Z")
    get_success_data(api.reject_offer(offer["id"], AGENT))
    res = api.reject_offer(offer["id"], AGENT)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_complete_with_outstanding_debt_returns_completion_not_eligible(api):
    """PRD §3.11: "Completion is permitted only when the program is `completion_eligible`: every debt must be terminal — that is, each debt is either `SETTLED` or `WITHDRAWN` — and no `SettlementFee` may remain `OUTSTANDING`. If either condition fails, completion is rejected with `ERR_COMPLETION_NOT_ELIGIBLE` (HTTP 409)."

    Design: Corner/state_machines/complete_program_with_outstanding_debt_returns_completion_not_eligible
    """
    client = create_client(full_name="C", email="c8@x.com", state_code="CA")
    program = create_program(client["id"], monthly_deposit_amount=600)
    create_debt(program["id"], creditor_name="Cred", account_number="CE-1",
               original_balance=5000)
    get_success_data(api.activate_program(program["id"], ADMIN))
    res = api.complete_program(program["id"], ADMIN)
    validate_error(res, ApiErrorId.ERR_COMPLETION_NOT_ELIGIBLE)


def test_drop_from_enrolling_terminates_and_refunds(api):
    """PRD §3.10: "the phase moves to `TERMINATED`."
    PRD §3.10: "The residual dedicated-account balance is refunded to the client — the rounded-half-up cents equivalent of the balance is added to the client's `refunded_to_client_cents`, and the account balance is set to zero."

    Design: Corner/state_machines/drop_from_enrolling_terminates_and_refunds
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(full_name="C", email="c9@x.com", state_code="CA")
    program = create_program(client["id"], monthly_deposit_amount=600)
    create_debt(program["id"], creditor_name="Cred", account_number="DR-1",
               original_balance=5000)
    ch = make_client_headers(client["id"])
    get_success_data(api.create_deposit(
        {"program_id": program["id"], "scheduled_for": "2026-05-10T00:00:00Z",
         "amount": 600}, ch))
    drop_res = api.drop_program(program["id"], ch)
    dropped = validate_success(drop_res, 200)
    assert dropped["program_phase"] == "TERMINATED"
    client_after = get_success_data(api.get_client(client["id"], ADMIN))
    assert client_after["refunded_to_client_cents"] == 60000
    acct = get_success_data(api.list_accounts(ADMIN, params={"program_id": program["id"]}))[0]
    assert acct["balance"] == pytest.approx(0.00, abs=0.01)


def test_dismiss_lawsuit_reverts_debt_to_enrolled(api):
    """PRD §3.9: "a `ProgramAdmin` dismisses a `REFERRED` lawsuit, moving it to `RESOLVED_DISMISSED`; dismissal requires the lawsuit to be `REFERRED`, otherwise `ERR_INVALID_STATE`. On dismissal the linked debt reverts out of `LAWSUIT`: it returns to `IN_NEGOTIATION` if it had a prior offer, or otherwise back to `ENROLLED`."

    Design: Corner/state_machines/dismiss_lawsuit_reverts_debt_out_of_lawsuit
    """
    set_clock("2026-06-01T00:00:00Z")
    client = create_client(full_name="C", email="c10@x.com", state_code="CA")
    program = create_program(client["id"], monthly_deposit_amount=600)
    debt = create_debt(program["id"], creditor_name="Cred", account_number="LD-1",
                      original_balance=5000)
    get_success_data(api.activate_program(program["id"], ADMIN))
    lawsuit = get_success_data(api.create_lawsuit(
        create_lawsuit_payload(program["id"], debt["id"],
                              court_reference="CR-1", filed_at="2026-05-01T00:00:00Z"), ADMIN))
    dismissed = validate_success(api.dismiss_lawsuit(lawsuit["id"], ADMIN), 200)
    assert dismissed["status"] == "RESOLVED_DISMISSED"
    debt_after = get_success_data(api.get_debt(debt["id"], ADMIN))
    assert debt_after["status"] == "ENROLLED"
