"""Cyclic state machines: session revision loop and proposal negotiation rounds.

Queue A (Difficulty) translations for the two non-linear (cyclic) state
machines in the contract.
"""
from test_helpers import (
    validate_success, get_success_data,
    make_counselor_headers, make_creditor_rep_headers,
    create_agency, create_counselor, create_creditor, create_client,
    open_intake_session, add_debt_account, counter_payload, resubmit_payload,
    api_client,
)


def test_session_revision_loop_second_round(api):
    """PRD §3.3: "From `OPEN`, the counselor may send the session back for
    revision, moving it to `NEEDS_REVISION`; this is allowed only from `OPEN`,
    otherwise `ERR_INVALID_STATE`."
    PRD §3.3: "From `NEEDS_REVISION`, resuming returns it to `OPEN`, allowed only
    from `NEEDS_REVISION`, otherwise `ERR_INVALID_STATE`. This `OPEN` ↔
    `NEEDS_REVISION` loop may cycle any number of rounds."

    Design: Difficulty/non_linear_state_machine/cyclic_session_revision_loop
    """
    agency = create_agency(monthly_fee_cents=3500)
    counselor = create_counselor(agency["id"])
    client = create_client(agency["id"], counselor["id"])
    session = open_intake_session(client["id"], counselor["id"])
    cn = make_counselor_headers(counselor["id"])

    validate_success(api.request_revision(session["id"], cn), 200)
    validate_success(api.resume_session(session["id"], cn), 200)
    second = validate_success(api.request_revision(session["id"], cn), 200)
    assert second["status"] == "NEEDS_REVISION"


def test_session_resume_returns_to_open(api):
    """PRD §3.3: "From `NEEDS_REVISION`, resuming returns it to `OPEN`, allowed
    only from `NEEDS_REVISION`, otherwise `ERR_INVALID_STATE`. This `OPEN` ↔
    `NEEDS_REVISION` loop may cycle any number of rounds."

    Design: Difficulty/non_linear_state_machine/cyclic_session_revision_loop
    """
    agency = create_agency(monthly_fee_cents=3500)
    counselor = create_counselor(agency["id"])
    client = create_client(agency["id"], counselor["id"])
    session = open_intake_session(client["id"], counselor["id"])
    cn = make_counselor_headers(counselor["id"])

    validate_success(api.request_revision(session["id"], cn), 200)
    resumed = validate_success(api.resume_session(session["id"], cn), 200)
    assert resumed["status"] == "OPEN"


def test_proposal_resubmit_increments_round_and_returns_submitted(api):
    """PRD §3.4: "In response, a `Counselor` may resubmit a `COUNTERED` proposal
    with a new `requested_concession_apr` (required, otherwise
    `ERR_INVALID_CONCESSION`); resubmission increments `round_index` by one,
    returns the proposal from `COUNTERED` to `SUBMITTED`, and moves the account
    from `COUNTERED` back to `PROPOSED`."

    Design: Difficulty/non_linear_state_machine/cyclic_proposal_negotiation_rounds
    """
    agency = create_agency(monthly_fee_cents=3500)
    counselor = create_counselor(agency["id"])
    creditor = create_creditor(agency["id"])
    client = create_client(agency["id"], counselor["id"])
    acct = add_debt_account(
        client["id"], counselor["id"], creditor["id"], account_ref="A",
        original_balance_cents=300000, proposed_monthly_payment_cents=30000,
    )
    rep = make_creditor_rep_headers(creditor["id"])
    validate_success(api.counter_proposal(acct["proposal_id"], counter_payload(0.1099), rep), 200)
    cn = make_counselor_headers(counselor["id"])
    resubmitted = validate_success(
        api.resubmit_proposal(acct["proposal_id"], resubmit_payload(0.0899), cn), 200
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["round_index"] == 2


def test_proposal_resubmit_returns_account_to_proposed(api):
    """PRD §3.4: "resubmission increments `round_index` by one, returns the
    proposal from `COUNTERED` to `SUBMITTED`, and moves the account from
    `COUNTERED` back to `PROPOSED`."

    Design: Difficulty/non_linear_state_machine/cyclic_proposal_negotiation_rounds
    """
    agency = create_agency(monthly_fee_cents=3500)
    counselor = create_counselor(agency["id"])
    creditor = create_creditor(agency["id"])
    client = create_client(agency["id"], counselor["id"])
    acct = add_debt_account(
        client["id"], counselor["id"], creditor["id"], account_ref="A",
        original_balance_cents=300000, proposed_monthly_payment_cents=30000,
    )
    rep = make_creditor_rep_headers(creditor["id"])
    validate_success(api.counter_proposal(acct["proposal_id"], counter_payload(0.1099), rep), 200)
    cn = make_counselor_headers(counselor["id"])
    validate_success(api.resubmit_proposal(acct["proposal_id"], resubmit_payload(0.0899), cn), 200)
    acct_after = get_success_data(api.get_debt_account(acct["id"], cn))
    assert acct_after["status"] == "PROPOSED"
