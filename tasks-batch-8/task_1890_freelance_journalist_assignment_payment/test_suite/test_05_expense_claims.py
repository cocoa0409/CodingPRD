"""Expense claims: category caps, the silent cap rule, the receipt gate,
amount sanity, and terminal-state lockdown on decisions."""
from test_helpers import (
    ApiErrorId,
    create_assignment,
    create_expense_claim,
    decide_expense,
    get_expense_claim,
    make_contributor_headers,
    settle_expense,
    setup_assignment_in_state,
    setup_contributor_with_agreement,
    submit_expense,
    validate_error,
    validate_success,
    walk_assignment,
)
from test_helpers import api_client as _api
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["desk_admin_headers"]
EDITOR = TEST_USERS["editor_headers"]


def test_zero_requested_amount_rejected(api):
    """PRD section 3.7: "A contributor first requests pre-approval on their
    own assignment — the claim's `assignment_id` ties it to that brief —
    supplying a `category` — one of `TRAVEL`, `MEALS`, `EQUIPMENT`, `OTHER` —
    and a `requested_cents` of at least 1; amounts below 1 are rejected with
    `ERR_INVALID_AMOUNT`."

    Design: Corner/errors/invalid_amount_zero_expense
    """
    _contributor, _agr, assignment = setup_assignment_in_state(
        "OFFERED", legal_name="Zero Zoe", email="zoe@x.com")
    contributor_id = assignment["contributor_id"]
    resp = api.create_expense_claim(
        assignment["id"], {"category": "MEALS", "requested_cents": 0},
        make_contributor_headers(contributor_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_AMOUNT, 422)


def test_decide_on_rejected_claim_fails(api):
    """PRD section 3.7: "Rejection moves the claim to `REJECTED` with no
    amount recorded." (no transition leaves REJECTED)
    PRD section 3.11: "Authentication comes first (missing or malformed
    headers yield `ERR_UNAUTHENTICATED`), then role authorization
    (`ERR_FORBIDDEN_ROLE`), then path existence left-to-right
    (`ERR_NOT_FOUND`), then state-machine legality including terminal-state
    lockdown (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/expense_decide_on_already_decided_rejected
    """
    _contributor, _agr, assignment = setup_assignment_in_state(
        "OFFERED", legal_name="Exp Eve", email="eve@x.com")
    contributor_id = assignment["contributor_id"]
    claim = create_expense_claim(assignment["id"], contributor_id,
                                 category="MEALS", requested_cents=3000)
    rejected = decide_expense(claim["id"], "REJECT")
    assert rejected["status"] == "REJECTED"

    resp = api.decide_expense_claim(claim["id"], {"decision": "APPROVE"},
                                    EDITOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_expense_claim(claim["id"])["status"] == "REJECTED"


def test_silent_category_cap_and_receipt_gate(api):
    """PRD section 3.7: "Approval requires the claim to be
    `PRE_APPROVAL_REQUESTED` and the assignment to be in `OFFERED`,
    `ACCEPTED`, or `IN_PROGRESS`; it sets `approved_cents` to the smaller of
    `requested_cents` and the category cap from the desk's
    `category_caps_cents` (defaults: `TRAVEL` 50000, `MEALS` 7500,
    `EQUIPMENT` 20000, `OTHER` 5000)."
    PRD section 3.7: "the `expense_reimbursement` rule sets
    `reimbursable_cents` to the smaller of `claimed_cents` and
    `approved_cents`. When the claim exceeds the approval the excess is
    silently forfeited — no error, no partial flag."
    PRD section 3.7: "The receipt gate is a validation, not part of the
    reimbursement formula: when `claimed_cents` is at or above the desk's
    `receipt_required_cents` (default 2500), `receipt_attached` must be true,
    and its absence is rejected with `ERR_RECEIPT_REQUIRED`."

    Design: Corner/calculations/expense_silent_cap_and_receipt_gate
    """
    _contributor, _agr, assignment = setup_assignment_in_state(
        "ACCEPTED", legal_name="Expense Ed", email="ed@x.com")
    contributor_id = assignment["contributor_id"]
    claim_meals = create_expense_claim(assignment["id"], contributor_id,
                                       category="MEALS", requested_cents=9000)
    claim_other = create_expense_claim(assignment["id"], contributor_id,
                                       category="OTHER", requested_cents=2600)
    decided_meals = decide_expense(claim_meals["id"], "APPROVE")
    assert decided_meals["approved_cents"] == 7500, (
        "MEALS cap 7500 silently caps the requested 9000, no error")
    decided_other = decide_expense(claim_other["id"], "APPROVE")
    assert decided_other["approved_cents"] == 2600, "below OTHER cap 5000"

    # Claim over approval: claimed 8000 > approved 7500 (receipt attached
    # because 8000 >= 2500).
    submit_expense(claim_meals["id"], contributor_id, 8000,
                   receipt_attached=True)
    # Settlement requires the assignment in UNDER_VERIFICATION or later.
    walk_assignment(assignment["id"], contributor_id, "UNDER_VERIFICATION")
    settled = settle_expense(claim_meals["id"], "REIMBURSE")
    assert settled["status"] == "REIMBURSABLE"
    assert settled["reimbursable_cents"] == 7500, (
        "min(claimed 8000, approved 7500); excess silently forfeited")

    # Receipt gate: claimed 2600 >= 2500 without a receipt is rejected.
    resp = api.submit_expense_claim(
        claim_other["id"],
        {"claimed_cents": 2600, "receipt_attached": False},
        make_contributor_headers(contributor_id))
    validate_error(resp, ApiErrorId.ERR_RECEIPT_REQUIRED, 422)
    assert get_expense_claim(claim_other["id"])["status"] == "APPROVED"
