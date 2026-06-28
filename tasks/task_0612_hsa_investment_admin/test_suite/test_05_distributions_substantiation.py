"""Distributions: request, clear, substantiate (two-person control), reverse, the
receipt vault, the card-active clear precondition, and the cash-conservation invariant.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
)
from test_helpers.fixtures import (
    ADMIN, ADMIN_A, ADMIN_B, set_clock, create_accountholder, open_account,
    attest_coverage, verify_account, setup_active_account_with_cash,
    request_distribution, clear_distribution, request_and_clear_distribution,
    vault_receipt, issue_and_activate_card,
)
from test_helpers.test_users import make_accountholder_headers
from test_helpers.api_client import api_client

ADMIN_HDR = ADMIN


# ── invalid_state_beats_insufficient_cash_on_clear (Difficulty/priority_pair) ─

def test_reclear_cleared_distribution_returns_invalid_state(api):
    """PRD §3.8: "Clearing a distribution is permitted only while it is `REQUESTED`,
    requires the account's `lifecycle_status` to be `ACTIVE` (else `ERR_INVALID_STATE`),
    and requires the account's `cash_balance_cents` to be at least the distribution's
    `amount_cents` (else `ERR_INSUFFICIENT_CASH`)."
    PRD §2.9: "Only after these gates does the platform evaluate state-machine
    eligibility (`ERR_INVALID_STATE`, HTTP 409) and the operation's domain-specific
    business rules."

    A second clear of an already-CLEARED distribution (now cash 0) fails state before
    fiscal -> ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_insufficient_cash_on_clear
    """
    account, holder, _c = setup_active_account_with_cash(amount_cents=60000,
                                                         date_of_birth="1986-06-06",
                                                         clock="2026-03-01T00:00:00Z")
    dist = request_and_clear_distribution(account["id"], holder["id"],
                                          "REIMBURSEMENT", 60000, clearer=ADMIN_A)
    assert dist["status"] == "CLEARED"
    res = api.clear_distribution(account["id"], dist["id"], ADMIN_A)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE)


def test_reclear_does_not_move_cash(api):
    """PRD §3.8: "On a successful clear the distribution moves to `CLEARED`, the
    account's `cash_balance_cents` decreases by `amount_cents`".

    The rejected second clear leaves cash at 0 (unchanged by the failed re-clear).

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_insufficient_cash_on_clear
    """
    account, holder, _c = setup_active_account_with_cash(amount_cents=60000,
                                                         date_of_birth="1986-06-06",
                                                         clock="2026-03-01T00:00:00Z")
    dist = request_and_clear_distribution(account["id"], holder["id"],
                                          "REIMBURSEMENT", 60000, clearer=ADMIN_A)
    validate_error(api.clear_distribution(account["id"], dist["id"], ADMIN_A),
                   ApiErrorId.ERR_INVALID_STATE)
    acct = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert acct["cash_balance_cents"] == 0


# ── distribution_clear_requires_card_active (Difficulty/cross_entity_state) ──

def test_clear_debit_card_distribution_with_suspended_card_rejected(api):
    """PRD §3.8: "If the method is `DEBIT_CARD`, the referenced card must be in `ACTIVE`
    status at clear time (else `ERR_CARD_NOT_ACTIVE`)."

    Design: Difficulty/cross_entity_state_dependency/distribution_clear_requires_card_active
    """
    set_clock("2026-03-01T00:00:00Z")
    account, holder, _c = setup_active_account_with_cash(amount_cents=80000,
                                                         date_of_birth="1991-11-11",
                                                         clock="2026-03-01T00:00:00Z")
    card = issue_and_activate_card(account["id"], holder["id"], "1111")
    dist = request_distribution(account["id"], holder["id"], "DEBIT_CARD", 50000,
                                card_id=card["id"])
    # Suspend the card before clearing.
    validate_success(api.suspend_card(account["id"], card["id"],
                                      make_accountholder_headers(holder["id"])), 200)
    res = api.clear_distribution(account["id"], dist["id"], ADMIN_A)
    validate_error(res, ApiErrorId.ERR_CARD_NOT_ACTIVE)


def test_clear_with_suspended_card_keeps_requested_and_cash(api):
    """PRD §3.8: "A newly requested distribution takes `status` `REQUESTED`".

    A clear rejected for a suspended card leaves the distribution REQUESTED and cash
    unchanged at 80000.

    Design: Difficulty/cross_entity_state_dependency/distribution_clear_requires_card_active
    """
    account, holder, _c = setup_active_account_with_cash(amount_cents=80000,
                                                         date_of_birth="1991-11-11",
                                                         clock="2026-03-01T00:00:00Z")
    card = issue_and_activate_card(account["id"], holder["id"], "1111")
    dist = request_distribution(account["id"], holder["id"], "DEBIT_CARD", 50000,
                                card_id=card["id"])
    validate_success(api.suspend_card(account["id"], card["id"],
                                      make_accountholder_headers(holder["id"])), 200)
    validate_error(api.clear_distribution(account["id"], dist["id"], ADMIN_A),
                   ApiErrorId.ERR_CARD_NOT_ACTIVE)
    after = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert after["cash_balance_cents"] == 80000
    dists = validate_success(api.list_distributions(account["id"], ADMIN_HDR), 200)
    target = next(d for d in dists if d["id"] == dist["id"])
    assert target["status"] == "REQUESTED"


# ── distribution_reverse_conserves_cash (Difficulty/compensating_invariant) ──

def test_distribution_reverse_restores_cash(api):
    """PRD §3.8: "An admin may reverse a `CLEARED` distribution — permitted only from
    `CLEARED` (else `ERR_INVALID_STATE`) — which moves it to `REVERSED` and refunds the
    money: the account's `cash_balance_cents` increases by `amount_cents`, conserving
    total funds."

    cash 300000 -> clear 80000 -> 220000 -> reverse -> 300000 (restored).

    Design: Difficulty/compensating_invariant/distribution_reverse_conserves_cash
    """
    account, holder, _c = setup_active_account_with_cash(amount_cents=300000,
                                                         coverage_tier="FAMILY",
                                                         date_of_birth="1977-07-17",
                                                         clock="2026-03-01T00:00:00Z")
    dist = request_and_clear_distribution(account["id"], holder["id"],
                                          "REIMBURSEMENT", 80000, clearer=ADMIN_A)
    mid = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert mid["cash_balance_cents"] == 220000
    reversed_d = validate_success(
        api.reverse_distribution(account["id"], dist["id"], ADMIN_B), 200)
    assert reversed_d["status"] == "REVERSED"
    after = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert after["cash_balance_cents"] == 300000


def test_distribution_clear_then_reverse_nets_zero(api):
    """PRD §3.8: "the account's `cash_balance_cents` increases by `amount_cents`,
    conserving total funds."

    The clear (-80000) followed by the reverse (+80000) nets zero; cash returns to its
    pre-clear value of 300000.

    Design: Difficulty/compensating_invariant/distribution_reverse_conserves_cash
    """
    account, holder, _c = setup_active_account_with_cash(amount_cents=300000,
                                                         coverage_tier="FAMILY",
                                                         date_of_birth="1977-07-17",
                                                         clock="2026-03-01T00:00:00Z")
    pre = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)["cash_balance_cents"]
    dist = request_and_clear_distribution(account["id"], holder["id"],
                                          "REIMBURSEMENT", 80000, clearer=ADMIN_A)
    validate_success(api.reverse_distribution(account["id"], dist["id"], ADMIN_B), 200)
    post = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)["cash_balance_cents"]
    assert post == pre == 300000


# ── clear_distribution_insufficient_cash (Corner/validations) ────────────────

def test_clear_distribution_insufficient_cash_rejected(api):
    """PRD §3.8: "requires the account's `cash_balance_cents` to be at least the
    distribution's `amount_cents` (else `ERR_INSUFFICIENT_CASH`)."

    Clearing a 90000 distribution against 50000 cash -> ERR_INSUFFICIENT_CASH; cash stays
    50000 and the distribution stays REQUESTED.

    Design: Corner/validations/clear_distribution_insufficient_cash
    """
    account, holder, _c = setup_active_account_with_cash(amount_cents=50000,
                                                         date_of_birth="1980-04-24",
                                                         clock="2026-03-01T00:00:00Z")
    dist = request_distribution(account["id"], holder["id"], "REIMBURSEMENT", 90000)
    res = api.clear_distribution(account["id"], dist["id"], ADMIN_A)
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_CASH)
    acct = validate_success(api.get_account(account["id"], ADMIN_HDR), 200)
    assert acct["cash_balance_cents"] == 50000
    dists = validate_success(api.list_distributions(account["id"], ADMIN_HDR), 200)
    target = next(d for d in dists if d["id"] == dist["id"])
    assert target["status"] == "REQUESTED"


# ── substantiate_segregation_same_admin (Corner/validations) ─────────────────

def test_substantiate_by_clearer_returns_segregation_violation(api):
    """PRD §3.8: "the acting admin's `X-User-ID` must differ from the distribution's
    `cleared_by_user_id`: the operator who cleared a distribution may not be the one who
    substantiates it, and a same-operator attempt is rejected with
    `ERR_SEGREGATION_VIOLATION`."

    Design: Corner/validations/substantiate_segregation_same_admin
    """
    account, holder, _c = setup_active_account_with_cash(amount_cents=80000,
                                                         date_of_birth="1980-03-30",
                                                         clock="2026-03-01T00:00:00Z")
    dist = request_and_clear_distribution(account["id"], holder["id"],
                                          "REIMBURSEMENT", 50000, clearer=ADMIN_A)
    # adminA (the clearer) attempts to substantiate.
    res = api.substantiate_distribution(account["id"], dist["id"], {}, ADMIN_A)
    validate_error(res, ApiErrorId.ERR_SEGREGATION_VIOLATION)
    dists = validate_success(api.list_distributions(account["id"], ADMIN_HDR), 200)
    target = next(d for d in dists if d["id"] == dist["id"])
    assert target["substantiation_status"] == "UNSUBSTANTIATED"


# ── substantiate_receipt_underfunded (Corner/validations) ────────────────────

def test_substantiate_with_underfunded_receipt_rejected(api):
    """PRD §3.8: "its `amount_cents` must be at least the distribution's `amount_cents`
    (else `ERR_RECEIPT_UNDERFUNDED`)."

    A 40000 receipt cannot substantiate a 50000 distribution.

    Design: Corner/validations/substantiate_receipt_underfunded
    """
    account, holder, _c = setup_active_account_with_cash(amount_cents=80000,
                                                         date_of_birth="1980-02-20",
                                                         clock="2026-03-01T00:00:00Z")
    receipt = vault_receipt(account["id"], holder["id"], amount_cents=40000,
                            is_qualified_medical=True, merchant="Pharmacy",
                            service_date="2026-02-01T00:00:00Z")
    dist = request_and_clear_distribution(account["id"], holder["id"],
                                          "REIMBURSEMENT", 50000, clearer=ADMIN_A)
    res = api.substantiate_distribution(account["id"], dist["id"],
                                        {"receipt_id": receipt["id"]}, ADMIN_B)
    validate_error(res, ApiErrorId.ERR_RECEIPT_UNDERFUNDED)
    dists = validate_success(api.list_distributions(account["id"], ADMIN_HDR), 200)
    target = next(d for d in dists if d["id"] == dist["id"])
    assert target["substantiation_status"] == "UNSUBSTANTIATED"
    rcpt = validate_success(api.get_receipt(receipt["id"], ADMIN_HDR), 200)
    assert rcpt["status"] == "VAULTED"


# ── receipt_not_available_wrong_account (Corner/errors) ──────────────────────

def test_substantiate_with_receipt_from_other_account_rejected(api):
    """PRD §3.8: "When a `receipt_id` is supplied, the referenced receipt must be
    `VAULTED` and must belong to the same account (else `ERR_RECEIPT_NOT_AVAILABLE`)".

    Substantiating account A's distribution with account B's receipt is rejected.

    Design: Corner/errors/receipt_not_available_wrong_account
    """
    set_clock("2026-03-01T00:00:00Z")
    accA, holderA, _ca = setup_active_account_with_cash(amount_cents=80000,
                                                        date_of_birth="1980-09-19",
                                                        clock="2026-03-01T00:00:00Z")
    accB, holderB, _cb = setup_active_account_with_cash(amount_cents=80000,
                                                        date_of_birth="1980-10-20",
                                                        clock="2026-03-01T00:00:00Z")
    rcpt_b = vault_receipt(accB["id"], holderB["id"], amount_cents=60000,
                           is_qualified_medical=True, merchant="OtherClinic",
                           service_date="2026-02-03T00:00:00Z")
    distA = request_and_clear_distribution(accA["id"], holderA["id"],
                                           "REIMBURSEMENT", 50000, clearer=ADMIN_A)
    res = api.substantiate_distribution(accA["id"], distA["id"],
                                        {"receipt_id": rcpt_b["id"]}, ADMIN_B)
    validate_error(res, ApiErrorId.ERR_RECEIPT_NOT_AVAILABLE)


# ── distribution_substantiate_twice_returns_already_substantiated (Corner) ───

def test_substantiate_already_substantiated_rejected(api):
    """PRD §3.8: "The distribution must be `CLEARED` (else `ERR_INVALID_STATE`) and must
    still be `UNSUBSTANTIATED` (else `ERR_ALREADY_SUBSTANTIATED`)."

    A first substantiate (no receipt) flips status to NONQUALIFIED; a second substantiate
    is rejected with ERR_ALREADY_SUBSTANTIATED.

    Design: Corner/state_machines/distribution_substantiate_twice_returns_already_substantiated
    """
    account, holder, _c = setup_active_account_with_cash(amount_cents=80000,
                                                         date_of_birth="1980-10-10",
                                                         clock="2026-03-01T00:00:00Z")
    dist = request_and_clear_distribution(account["id"], holder["id"],
                                          "REIMBURSEMENT", 50000, clearer=ADMIN_A)
    first = validate_success(
        api.substantiate_distribution(account["id"], dist["id"], {}, ADMIN_B), 200)
    assert first["substantiation_status"] == "NONQUALIFIED"
    res = api.substantiate_distribution(account["id"], dist["id"], {}, ADMIN_B)
    validate_error(res, ApiErrorId.ERR_ALREADY_SUBSTANTIATED)


# ── fk_reverse_list_receipts_by_account (Corner/endpoints) ───────────────────

def test_list_receipts_filtered_by_account(api):
    """PRD §3.7: "Receipts can be fetched individually and listed, with the list
    optionally filtered by `account_id`, by `distribution_id`, or by `status`".

    A receipt vaulted to the account appears in GET /hsa/receipts?account_id=.

    Design: Corner/endpoints/fk_reverse_list_receipts_by_account
    """
    account, holder, _c = setup_active_account_with_cash(amount_cents=80000,
                                                         date_of_birth="1980-05-25",
                                                         clock="2026-03-01T00:00:00Z")
    receipt = vault_receipt(account["id"], holder["id"], amount_cents=25000,
                            is_qualified_medical=True, merchant="Lab",
                            service_date="2026-02-02T00:00:00Z")
    res = api.list_receipts(ADMIN_HDR, params={"account_id": account["id"]})
    receipts = validate_success(res, 200)
    ids = [r["id"] for r in receipts]
    assert receipt["id"] in ids
    target = next(r for r in receipts if r["id"] == receipt["id"])
    assert target["account_id"] == account["id"]
