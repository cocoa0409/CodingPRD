"""Dual control: teller requests, instrument issuance, fee waiver, over-limit."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    TEST_USERS, basic_setup, teller_h, instrument_params, fee_waiver_params,
    over_limit_params, issue_instrument,
    MONEY_ORDER_FEE_CENTS, MONEY_ORDER_MAX_CENTS,
)

MGR = TEST_USERS["manager_headers"]
HT = TEST_USERS["head_teller_headers"]


def test_instrument_fee_pinned_evaluation_order(api):
    """PRD §3.5: "The fee is fixed per instrument type — 800 cents for a
    cashier's check, 200 for a money order — and the waiver flag, when true,
    zeroes it." and "the customer pays cash at the window: the face amount plus
    the issuance fee."

    Design: Difficulty/combinatorial_formula/instrument_fee_pinned_evaluation_order
    """
    ctx = basic_setup(api, account_balance=777_000)
    txn = issue_instrument(api, ctx["drawer"], ctx["account"], ctx["teller"],
                           50_000, "MONEY_ORDER")
    assert txn["type"] == "MONEY_ORDER_PURCHASE"
    assert txn["fee_cents"] == 200
    exp = validate_success(api.get_expected_cash(ctx["drawer"]["id"], MGR))
    assert exp["expected_cash_cents"] == 50_200


def test_instrument_purchase_does_not_debit_account(api):
    """PRD §3.5: "the account's `balance_cents` is not debited — the account
    identity exists for reporting".

    Design: Difficulty/combinatorial_formula/instrument_fee_pinned_evaluation_order
    """
    ctx = basic_setup(api, account_balance=777_000)
    issue_instrument(api, ctx["drawer"], ctx["account"], ctx["teller"],
                     300_000, "CASHIERS_CHECK")
    acct = validate_success(api.get_account(ctx["account"]["id"], MGR))
    assert acct["balance_cents"] == 777_000
    txns = get_success_data(api.list_transactions(MGR, {"drawer_id": ctx["drawer"]["id"]}))
    assert txns[0]["fee_cents"] == 800


def test_money_order_face_limit_boundary(api):
    """PRD §3.5: "A money order's face may not exceed 100000 cents
    (`ERR_INSTRUMENT_LIMIT`); a cashier's check has no face cap."

    Design: Corner/errors/money_order_face_limit_boundary
    """
    ctx = basic_setup(api)
    resp = api.create_teller_request(ctx["drawer"]["id"], {
        "type": "ISSUE_INSTRUMENT",
        "params": instrument_params(ctx["account"]["id"], "MONEY_ORDER", 100_001),
    }, ctx["teller_h"])
    validate_error(resp, "ERR_INSTRUMENT_LIMIT", 422)
    ok = validate_success(api.create_teller_request(ctx["drawer"]["id"], {
        "type": "ISSUE_INSTRUMENT",
        "params": instrument_params(ctx["account"]["id"], "MONEY_ORDER", 100_000),
    }, ctx["teller_h"]), 201)
    assert ok["status"] == "PENDING"


def test_instrument_direct_post_requires_approval(api):
    """PRD §3.3: "`CASHIERS_CHECK_PURCHASE` and `MONEY_ORDER_PURCHASE` are
    rejected at the window with `ERR_INSTRUMENT_REQUIRES_APPROVAL`, because
    negotiable instruments are issued only through an approved dual-control
    request."

    Design: Corner/errors/instrument_direct_post_requires_approval
    """
    ctx = basic_setup(api)
    resp = api.post_transaction(ctx["drawer"]["id"], {
        "account_id": ctx["account"]["id"], "type": "CASHIERS_CHECK_PURCHASE",
        "amount_cents": 25_000,
    }, ctx["teller_h"])
    validate_error(resp, "ERR_INSTRUMENT_REQUIRES_APPROVAL", 409)


def test_approve_with_requester_id_rejected_sod(api):
    """PRD §3.5: "The decider's `X-User-ID` must differ from
    `requested_by_user_id`; a self-decision is `ERR_SOD_VIOLATION` whether it
    arrives under a manager role or any other."

    Design: Corner/validations/approve_with_requester_id_rejected_sod
    """
    ctx = basic_setup(api)
    req = validate_success(api.create_teller_request(ctx["drawer"]["id"], {
        "type": "ISSUE_INSTRUMENT",
        "params": instrument_params(ctx["account"]["id"], "MONEY_ORDER", 50_000),
    }, ctx["teller_h"]), 201)
    # Manager role but carrying the requester's id -> SoD violation
    resp = api.approve_teller_request(req["id"], teller_h(ctx["teller"]) | {"X-User-Role": "BranchManager"})
    validate_error(resp, "ERR_SOD_VIOLATION", 409)
    after = validate_success(api.get_teller_request(req["id"], MGR))
    assert after["status"] == "PENDING"


def test_rejected_request_creates_approval_record(api):
    """PRD §3.5: "Either decision writes an immutable `Approval` record — the
    decision ledger of §3.10 — with `action_type` `TELLER_REQUEST`, the request
    as its subject, and the decider in `approved_by_user_id`."

    Design: Corner/state_machines/rejected_request_creates_approval_record
    """
    ctx = basic_setup(api)
    req = validate_success(api.create_teller_request(ctx["drawer"]["id"], {
        "type": "ISSUE_INSTRUMENT",
        "params": instrument_params(ctx["account"]["id"], "CASHIERS_CHECK", 25_000,
                                    fee_waived=True),
    }, ctx["teller_h"]), 201)
    rejected = validate_success(api.reject_teller_request(req["id"], MGR))
    assert rejected["status"] == "REJECTED"
    approvals = get_success_data(api.list_approvals(MGR, {"branch_id": ctx["branch"]["id"]}))
    assert len(approvals) == 1
    rec = approvals[0]
    assert rec["action_type"] == "TELLER_REQUEST"
    assert rec["status"] == "REJECTED"
    assert rec["approved_by_user_id"] == "mgr-1"
    assert rec["subject_id"] == req["id"]
    assert rec["subject_type"] == "TellerRequest"


def test_teller_request_expires_on_date_change(api):
    """PRD §3.5: "A request that is still `PENDING` when the logical clock first
    lands on a later calendar date than its creation date expires automatically
    to `EXPIRED`, and nothing may execute it thereafter."

    Design: Corner/state_machines/teller_request_expires_on_date_change
    """
    ctx = basic_setup(api)
    req = validate_success(api.create_teller_request(ctx["drawer"]["id"], {
        "type": "ISSUE_INSTRUMENT",
        "params": instrument_params(ctx["account"]["id"], "MONEY_ORDER", 50_000),
    }, ctx["teller_h"]), 201)
    get_success_data(api.set_clock("2026-08-02T00:00:00Z", MGR))
    after = validate_success(api.get_teller_request(req["id"], MGR))
    assert after["status"] == "EXPIRED"
    resp = api.approve_teller_request(req["id"], MGR)
    validate_error(resp, "ERR_INVALID_STATE", 409)
    txns = get_success_data(api.list_transactions(MGR, {"drawer_id": ctx["drawer"]["id"]}))
    assert txns == []


def test_fee_waiver_request_refunds_fee_to_account(api):
    """PRD §3.5: "Execution refunds the fee by adding the transaction's
    `fee_cents` back to the account's `balance_cents`; the drawer's cash is
    untouched by the refund."

    Design: Corner/calculations/fee_waiver_request_refunds_fee_to_account
    """
    ctx = basic_setup(api, account_balance=0)
    txn = issue_instrument(api, ctx["drawer"], ctx["account"], ctx["teller"],
                           50_000, "MONEY_ORDER")
    req = validate_success(api.create_teller_request(ctx["drawer"]["id"], {
        "type": "FEE_WAIVER", "params": fee_waiver_params(txn["id"]),
    }, ctx["teller_h"]), 201)
    executed = validate_success(api.approve_teller_request(req["id"], MGR))
    assert executed["status"] == "EXECUTED"
    acct = validate_success(api.get_account(ctx["account"]["id"], MGR))
    assert acct["balance_cents"] == 200
    exp = validate_success(api.get_expected_cash(ctx["drawer"]["id"], MGR))
    assert exp["expected_cash_cents"] == 50_200


def test_fee_waiver_unknown_transaction_rejected(api):
    """PRD §3.5: "`params` names a `transaction_id`: an existing `POSTED`
    instrument-purchase transaction on the same branch (anything else — an
    unknown id, a voided transaction, a non-instrument transaction, another
    branch's transaction — is `ERR_TRANSACTION_NOT_FOUND`, HTTP 404)."

    Design: Corner/errors/fee_waiver_unknown_transaction_rejected
    """
    from test_helpers import NON_EXISTENT_UUID
    ctx = basic_setup(api)
    resp = api.create_teller_request(ctx["drawer"]["id"], {
        "type": "FEE_WAIVER", "params": fee_waiver_params(NON_EXISTENT_UUID),
    }, ctx["teller_h"])
    validate_error(resp, "ERR_TRANSACTION_NOT_FOUND", 404)


def test_over_limit_withdrawal_via_approved_request(api):
    """PRD §3.5: "Execution posts that `CASH_WITHDRAWAL` with the
    per-transaction limit check set aside — all other rules, including
    available-funds and drawer-cash sufficiency, still apply at execution
    time."

    Design: Corner/endpoints/over_limit_withdrawal_via_approved_request
    """
    ctx = basic_setup(api, branch_overrides={"drawer_limit_cents": 100_000_000},
                      account_balance=100_000_000)
    get_success_data(api.buy_from_vault(ctx["drawer"]["id"], 1_000_000, ctx["teller_h"]))
    req = validate_success(api.create_teller_request(ctx["drawer"]["id"], {
        "type": "OVER_LIMIT_TRANSACTION",
        "params": over_limit_params(ctx["account"]["id"], 600_000),
    }, ctx["teller_h"]), 201)
    executed = validate_success(api.approve_teller_request(req["id"], HT))
    assert executed["status"] == "EXECUTED"
    txns = get_success_data(api.list_transactions(MGR, {"drawer_id": ctx["drawer"]["id"]}))
    assert txns[0]["type"] == "CASH_WITHDRAWAL"
    assert txns[0]["amount_cents"] == 600_000
    acct = validate_success(api.get_account(ctx["account"]["id"], MGR))
    assert acct["balance_cents"] == 99_400_000
    drawer = validate_success(api.get_drawer(ctx["drawer"]["id"], MGR))
    assert drawer["cash_balance_cents"] == 400_000
