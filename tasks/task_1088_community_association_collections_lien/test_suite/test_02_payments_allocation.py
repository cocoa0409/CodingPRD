"""Payment allocation waterfall, full-payment cascade, empty-candidate edge,
reversal compensation, and trust-cash conservation."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    fixtures,
)

AGENT = TEST_USERS["collections_agent_headers"]
TRUSTEE = TEST_USERS["trust_accountant_headers"]


# --- transitive_cascade / tc_full_payment_depth2 (queue A, >=2 tests) ---

def test_full_payment_pays_assessment(api):
    """PRD §3.3: "the system applies to each assessment the smaller of the remaining payment
    and that assessment's `balance_cents`, records the applied amount, decrements the
    assessment's `balance_cents`, and marks the assessment `PAID` when its balance reaches
    zero or `PARTIAL` otherwise."

    Design: Difficulty/transitive_cascade/tc_full_payment_depth2
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    base = fixtures.setup_delinquent_account(api, amount_cents=50000)
    acct_id, asm_id = base["account"]["id"], base["assessment"]["id"]
    pay = validate_success(
        api.create_payment({"account_id": acct_id, "amount_cents": 50000,
                            "received_date": "2026-05-01T00:00:00Z"}, AGENT),
        expected_status=201)
    assert pay["unapplied_cents"] == 0
    asm = get_success_data(api.get_assessment(asm_id, AGENT))
    assert asm["status"] == "PAID"
    assert asm["balance_cents"] == 0


def test_full_payment_returns_account_to_current(api):
    """PRD §3.1: "Whenever a payment allocation drives an account's `total_balance_cents` to
    zero, the system returns the account to `CURRENT`: a `DELINQUENT → CURRENT` transition"

    Design: Difficulty/transitive_cascade/tc_full_payment_depth2
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    base = fixtures.setup_delinquent_account(api, amount_cents=50000)
    acct_id = base["account"]["id"]
    validate_success(
        api.create_payment({"account_id": acct_id, "amount_cents": 50000,
                            "received_date": "2026-05-01T00:00:00Z"}, AGENT),
        expected_status=201)
    acct = get_success_data(api.get_account(acct_id, AGENT))
    assert acct["status"] == "CURRENT"
    assert acct["total_balance_cents"] == 0


# --- boundary_precision_check / bp_empty_open_assessments_payment (queue A, >=2 tests) ---

def test_payment_with_no_open_assessments_all_unapplied(api):
    """PRD §3.3: "If the account has no `OPEN` or `PARTIAL` assessment, the entire amount
    becomes `unapplied_cents`."

    Design: Difficulty/boundary_precision_check/bp_empty_open_assessments_payment
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    assoc, acct = fixtures.setup_account(api, {"name": "Sage HOA", "state_code": "NV"})
    pay = validate_success(
        api.create_payment({"account_id": acct["id"], "amount_cents": 5000,
                            "received_date": "2026-05-01T00:00:00Z"}, AGENT),
        expected_status=201)
    assert pay["status"] == "POSTED"
    assert pay["unapplied_cents"] == 5000
    assert pay["allocations"] == []


def test_payment_with_no_open_assessments_leaves_balance_zero(api):
    """PRD §3.3: "any amount left after all live charges are satisfied is retained as the
    payment's `unapplied_cents` (an overpayment credit, which may be zero)."
    PRD §3.2: "An account's `total_balance_cents` is, at every instant, the sum of
    `balance_cents` across that account's assessments whose `status` is `OPEN` or `PARTIAL`"

    Design: Difficulty/boundary_precision_check/bp_empty_open_assessments_payment
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    assoc, acct = fixtures.setup_account(api, {"name": "Sage HOA", "state_code": "NV"})
    validate_success(
        api.create_payment({"account_id": acct["id"], "amount_cents": 5000,
                            "received_date": "2026-05-01T00:00:00Z"}, AGENT),
        expected_status=201)
    data = get_success_data(api.get_account(acct["id"], AGENT))
    assert data["total_balance_cents"] == 0


# --- compensating_invariant / ci_trust_cash_conservation (queue A, >=2 tests) ---

def test_trust_rises_on_payment_post(api):
    """PRD §3.3: "Posting a payment increases the association's `trust_balance_cents` by the
    payment's `amount_cents`, recomputes the account's `total_balance_cents`"

    Design: Difficulty/compensating_invariant/ci_trust_cash_conservation
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    assoc, acct = fixtures.setup_account(api, {"name": "Gale HOA"})
    validate_success(
        api.create_payment({"account_id": acct["id"], "amount_cents": 70000,
                            "received_date": "2026-05-01T00:00:00Z"}, AGENT),
        expected_status=201)
    a = get_success_data(api.get_association(assoc["id"], TRUSTEE))
    assert a["trust_balance_cents"] == 70000


def test_trust_returns_to_zero_after_reversal(api):
    """PRD §3.3: "the association's `trust_balance_cents` is decreased by the payment's
    `amount_cents`, so that the post-and-reverse pair leaves trust cash unchanged."

    Design: Difficulty/compensating_invariant/ci_trust_cash_conservation
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    assoc, acct = fixtures.setup_account(api, {"name": "Gale HOA"})
    pay = validate_success(
        api.create_payment({"account_id": acct["id"], "amount_cents": 70000,
                            "received_date": "2026-05-01T00:00:00Z"}, AGENT),
        expected_status=201)
    assert get_success_data(api.get_association(assoc["id"], TRUSTEE))["trust_balance_cents"] == 70000
    validate_success(api.reverse_payment(pay["id"], "NSF", AGENT))
    a = get_success_data(api.get_association(assoc["id"], TRUSTEE))
    assert a["trust_balance_cents"] == 0


# --- Queue B: state_machines ---

def test_reversal_reopens_assessment_and_delinquent(api):
    """PRD §3.3: "The account's `total_balance_cents` is recomputed; if it becomes greater
    than zero and the account had been returned to `CURRENT` by this very payment, the
    account moves back to `DELINQUENT`."

    Design: Corner/state_machines/payment_reversal_reopens_assessment_and_delinquent
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    base = fixtures.setup_delinquent_account(api, amount_cents=40000)
    acct_id, asm_id = base["account"]["id"], base["assessment"]["id"]
    pay = get_success_data(
        api.create_payment({"account_id": acct_id, "amount_cents": 40000,
                            "received_date": "2026-05-01T00:00:00Z"}, AGENT))
    reversed_pay = validate_success(api.reverse_payment(pay["id"], "NSF", AGENT))
    assert reversed_pay["status"] == "REVERSED"
    asm = get_success_data(api.get_assessment(asm_id, AGENT))
    assert asm["status"] == "OPEN"
    assert asm["balance_cents"] == 40000
    acct = get_success_data(api.get_account(acct_id, AGENT))
    assert acct["status"] == "DELINQUENT"
    assert acct["total_balance_cents"] == 40000


def test_reverse_already_reversed_payment_rejected(api):
    """PRD §3.3: "Reversal is permitted only on a payment currently in `POSTED`; reversing an
    already-`REVERSED` payment yields `ERR_INVALID_STATE`."

    Design: Corner/state_machines/payment_reverse_already_reversed_invalid
    """
    fixtures.set_clock(api, "2026-05-01T00:00:00Z")
    assoc, acct = fixtures.setup_account(api, {"name": "Oak2 HOA"})
    pay = get_success_data(
        api.create_payment({"account_id": acct["id"], "amount_cents": 20000,
                            "received_date": "2026-05-01T00:00:00Z"}, AGENT))
    validate_success(api.reverse_payment(pay["id"], "NSF", AGENT))
    resp = api.reverse_payment(pay["id"], "ADJUSTMENT", AGENT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
