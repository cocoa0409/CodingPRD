"""Non-linear claim state machine (REQUEST_DOCS / resubmit cycle) and the two independent
Account dimensions (funding_status x compliance_hold). Plus invalid-transition corner cases.

Translates Difficulty/non_linear_state_machine instances and several
Corner/state_machines instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId, TEST_USERS,
    setup_active_fsa, setup_active_hsa, setup_reimbursed_hsa, file_claim, get_account,
    create_batch, make_adjudicator_headers, make_participant_headers,
    make_disburser_headers, post_contribution,
)

ADMIN = TEST_USERS["plan_admin_headers"]


# --- Claim revision cycle (SUBMITTED -> PENDING_SUBSTANTIATION -> SUBMITTED -> APPROVED) ---

def test_request_docs_moves_submitted_to_pending_substantiation(api):
    """PRD §3.4: "A `REQUEST_DOCS` decision is available only when the claim is `SUBMITTED`,
    is not `substantiated`, and has a `claimed_amount_cents` strictly greater than the
    account's `auto_adjudication_threshold_cents`; it moves the claim from `SUBMITTED` to
    `PENDING_SUBSTANTIATION` and records `adjudicated_by`."

    Design: Difficulty/non_linear_state_machine/claim_substantiation_revision_cycle
    """
    py, p, acc = setup_active_fsa(
        account_type="HEALTH_FSA", elected_amount_cents=335000,
        auto_adjudication_threshold_cents=10000)
    claim = file_claim(acc["id"], p["id"], service_date="2026-04-01",
                       expense_category="MEDICAL",
                       claimed_amount_cents=50000, substantiated=False)
    resp = api.adjudicate_claim(claim["id"], {"decision": "REQUEST_DOCS"},
                                make_adjudicator_headers("adj-1"))
    data = validate_success(resp)
    assert data["status"] == "PENDING_SUBSTANTIATION"


def test_resubmit_cycles_back_to_submitted_then_approves(api):
    """PRD §3.4: "the resubmit operation requires `substantiated` to be supplied as `true`,
    sets the claim's `substantiated` to `true`, moves it from `PENDING_SUBSTANTIATION` back
    to `SUBMITTED` (the revision loop, re-entering adjudication), and increments `version` by
    one."
    PRD §3.4: "Approval moves the claim from `SUBMITTED` to `APPROVED`".

    Full A->B->A loop then a terminal APPROVE.

    Design: Difficulty/non_linear_state_machine/claim_substantiation_revision_cycle
    """
    py, p, acc = setup_active_fsa(
        account_type="HEALTH_FSA", elected_amount_cents=335000,
        auto_adjudication_threshold_cents=10000)
    claim = file_claim(acc["id"], p["id"], service_date="2026-04-01",
                       expense_category="MEDICAL",
                       claimed_amount_cents=50000, substantiated=False)
    api.adjudicate_claim(claim["id"], {"decision": "REQUEST_DOCS"},
                         make_adjudicator_headers("adj-1"))
    resub = validate_success(api.resubmit_claim(
        claim["id"], {"substantiated": True}, make_participant_headers(p["id"])))
    assert resub["status"] == "SUBMITTED", "resubmit cycles back to SUBMITTED"
    assert resub["substantiated"] is True

    approved = validate_success(api.adjudicate_claim(
        claim["id"], {"decision": "APPROVE"}, make_adjudicator_headers("adj-1")))
    assert approved["status"] == "APPROVED"


# --- Account parallel dimensions: one disburse flips funding AND compliance ---

def test_unsubstantiated_full_drawdown_flips_funding_status_to_depleted(api):
    """PRD §3.6: "If a claim is reimbursed but its `available_balance_cents` reaches zero,
    the account's `funding_status` moves from `ACTIVE` to `DEPLETED`".

    A single unsubstantiated 50000 reimbursement on a 50000-elected HEALTH_FSA exhausts the
    balance, flipping funding_status to DEPLETED.

    Design: Difficulty/non_linear_state_machine/account_parallel_funding_and_compliance_dimensions
    """
    py, p, acc = setup_active_fsa(
        account_type="HEALTH_FSA", elected_amount_cents=50000,
        auto_adjudication_threshold_cents=100000)
    claim = file_claim(acc["id"], p["id"], service_date="2026-04-01",
                       expense_category="VISION",
                       claimed_amount_cents=50000, substantiated=False)
    validate_success(api.adjudicate_claim(
        claim["id"], {"decision": "APPROVE"}, make_adjudicator_headers("adj-1")))
    batch = create_batch(p["id"], [claim["id"]])
    live = get_account(acc["id"])
    validate_success(api.disburse_batch(
        batch["id"], {"expected_account_version": live["version"]},
        make_disburser_headers("disb-1")))

    after = validate_success(api.get_account(acc["id"], ADMIN))
    assert after["funding_status"] == "DEPLETED", "available hit 0 → DEPLETED"


def test_unsubstantiated_reimbursement_flips_compliance_hold_to_held(api):
    """PRD §3.6: "If a reimbursed claim was not `substantiated`, the account's
    `compliance_hold` moves from `CLEAR` to `HELD`, blocking subsequent reimbursements on
    that account until the hold is cleared."

    The same disburse that depletes the account also sets compliance_hold HELD — the two
    dimensions move independently on one row.

    Design: Difficulty/non_linear_state_machine/account_parallel_funding_and_compliance_dimensions
    """
    py, p, acc = setup_active_fsa(
        account_type="HEALTH_FSA", elected_amount_cents=50000,
        auto_adjudication_threshold_cents=100000)
    claim = file_claim(acc["id"], p["id"], service_date="2026-04-01",
                       expense_category="VISION",
                       claimed_amount_cents=50000, substantiated=False)
    validate_success(api.adjudicate_claim(
        claim["id"], {"decision": "APPROVE"}, make_adjudicator_headers("adj-1")))
    batch = create_batch(p["id"], [claim["id"]])
    live = get_account(acc["id"])
    validate_success(api.disburse_batch(
        batch["id"], {"expected_account_version": live["version"]},
        make_disburser_headers("disb-1")))

    after = validate_success(api.get_account(acc["id"], ADMIN))
    assert after["compliance_hold"] == "HELD", "unsubstantiated reimbursement → HELD"


# --- Corner state_machines invalid transitions / valid side-effects ---

def test_adjudicate_already_denied_claim_returns_invalid_state(api):
    """PRD §3.4: "`DENIED` is terminal. Adjudicating a claim that is not in a state
    permitting the chosen transition is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/adjudicate_already_denied_claim_returns_invalid_state
    """
    py, p, acc = setup_active_fsa(
        account_type="HEALTH_FSA", elected_amount_cents=100000,
        auto_adjudication_threshold_cents=1000000)
    claim = file_claim(acc["id"], p["id"], service_date="2026-04-01",
                       expense_category="MEDICAL",
                       claimed_amount_cents=50000, substantiated=True)
    validate_success(api.adjudicate_claim(
        claim["id"], {"decision": "DENY", "denial_reason": "NOT_QUALIFIED"},
        make_adjudicator_headers("adj-1")))
    resp = api.adjudicate_claim(claim["id"], {"decision": "APPROVE"},
                                make_adjudicator_headers("adj-1"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_claim(claim["id"], ADMIN))
    assert after["status"] == "DENIED"


def test_resubmit_from_submitted_returns_invalid_state(api):
    """PRD §3.4: "A claim in `PENDING_SUBSTANTIATION` returns to the queue when the
    `Participant` resubmits it with documentation".

    Resubmit is valid only from PENDING_SUBSTANTIATION; on a SUBMITTED claim the transition
    is not permitted, so ERR_INVALID_STATE.

    Design: Corner/state_machines/resubmit_from_submitted_returns_invalid_state
    """
    py, p, acc = setup_active_fsa(
        account_type="HEALTH_FSA", elected_amount_cents=100000,
        auto_adjudication_threshold_cents=1000000)
    claim = file_claim(acc["id"], p["id"], service_date="2026-04-01",
                       expense_category="MEDICAL",
                       claimed_amount_cents=50000, substantiated=True)
    resp = api.resubmit_claim(claim["id"], {"substantiated": True},
                              make_participant_headers(p["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_claim(claim["id"], ADMIN))
    assert after["status"] == "SUBMITTED"


def test_activate_already_active_account_returns_invalid_state(api):
    """PRD §3.2: "Activation is permitted only while the account is `PENDING`; otherwise it
    is rejected with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/activate_already_active_account_returns_invalid_state
    """
    py, p, acc = setup_active_fsa(
        account_type="HEALTH_FSA", elected_amount_cents=100000)
    resp = api.activate_account(acc["id"], ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    after = validate_success(api.get_account(acc["id"], ADMIN))
    assert after["funding_status"] == "ACTIVE"


def test_depleted_hsa_reopens_on_new_contribution(api):
    """PRD §3.3: "If the account had been `DEPLETED` and the new contribution lifts its
    `available_balance_cents` above zero, the account re-opens, moving `funding_status` from
    `DEPLETED` back to `ACTIVE`."

    Design: Corner/state_machines/claim_depletes_then_contribution_reopens_account
    """
    py, p, acc, claim = setup_reimbursed_hsa(contribution_cents=100000, claim_cents=100000)
    assert acc["funding_status"] == "DEPLETED" and acc["available_balance_cents"] == 0
    post_contribution(acc["id"], 25000, acc["version"], source="EMPLOYER",
                      posted_at="2026-05-01T00:00:00Z")
    after = validate_success(api.get_account(acc["id"], ADMIN))
    assert after["available_balance_cents"] == 25000
    assert after["funding_status"] == "ACTIVE", "DEPLETED -> ACTIVE reopen"


def test_reverse_already_reversed_contribution_returns_invalid_state(api):
    """PRD §3.3: "A reversal is permitted only while the contribution is `POSTED`; an attempt
    to reverse an already-`REVERSED` contribution is an `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/reverse_already_reversed_contribution_returns_invalid_state
    """
    py, p, acc = setup_active_hsa(elected_amount_cents=437500)
    contrib = validate_success(api.create_contribution(
        acc["id"],
        {"amount_cents": 50000, "source": "PAYROLL", "posted_at": "2026-02-01T00:00:00Z",
         "expected_account_version": acc["version"]}, ADMIN), expected_status=201)
    live = get_account(acc["id"])
    validate_success(api.reverse_contribution(
        acc["id"], contrib["id"], {"expected_account_version": live["version"]}, ADMIN))
    live2 = get_account(acc["id"])
    resp = api.reverse_contribution(
        acc["id"], contrib["id"], {"expected_account_version": live2["version"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    rows, _ = validate_paginated(api.list_contributions(acc["id"], ADMIN))
    target = next(c for c in rows if c["id"] == contrib["id"])
    assert target["status"] == "REVERSED", "contribution status unchanged after rejected reverse"
