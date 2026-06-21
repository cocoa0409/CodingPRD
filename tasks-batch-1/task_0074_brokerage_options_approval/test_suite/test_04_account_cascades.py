"""Account restrict/close cascades and cross-entity state-dependency tests."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    open_and_activate_account, accept_order, draft_order, open_position,
    submit_options_approval, request_acat, validate_acat, get_account,
    CO_SUBMITTER, HOLDER, CUST,
)


def test_restrict_cancels_order_releases_notional_recomputes_buying_power(api):
    """PRD §3.2: "every `Order` on the account currently in `DRAFT`,
    `ACCEPTED`, or `PARTIALLY_FILLED` is transitioned to `CANCELLED`". PRD §3.2:
    "When the cancelled orders had reserved notional, that notional is released
    back to buying power as described in §3.5, and the account's buying power is
    recomputed."

    cash 1000000, an ACCEPTED LIMIT order reserving 600000 (buying_power 400000);
    restrict cancels it and buying_power returns to 1000000.

    Design: Difficulty/transitive_cascade/restrict_cancels_order_releases_notional_recomputes_buying_power
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    ord_ = accept_order(acct["id"], symbol="ACME", instrument_type="EQUITY", side="BUY",
                        order_type="LIMIT", quantity=6, limit_price_cents=100_000)
    assert get_account(acct["id"])["buying_power_cents"] == 400_000

    resp = api.restrict_account(acct["id"], CO_SUBMITTER)
    data = validate_success(resp)
    assert data["status"] == "RESTRICTED"

    order_after = validate_success(api.get_order(ord_["id"], HOLDER))
    assert order_after["status"] == "CANCELLED"
    assert validate_success(api.get_account(acct["id"], CO_SUBMITTER))["buying_power_cents"] == 1_000_000


def test_restrict_rejects_pending_options_approval_cascade(api):
    """PRD §3.2: "every `OptionsApproval` on the account currently in `DRAFT` or
    `SUBMITTED` is transitioned to `REJECTED` with its `rejection_reason` set to
    the literal string `ACCOUNT_RESTRICTED`".

    Design: Corner/state_machines/restrict_rejects_pending_options_approval_cascade
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    oa1 = submit_options_approval(acct["id"], 1)

    resp = api.restrict_account(acct["id"], CO_SUBMITTER)
    data = validate_success(resp)
    assert data["status"] == "RESTRICTED"

    oa_after = validate_success(api.get_options_approval(oa1["id"], CO_SUBMITTER))
    assert oa_after["status"] == "REJECTED"
    assert oa_after["rejection_reason"] == "ACCOUNT_RESTRICTED"


def test_order_accept_requires_account_active(api):
    """PRD §3.5: "Acceptance is where the heaviest validation lives, and the
    checks are evaluated in this order. First, the parent account must be
    `ACTIVE`, otherwise `ERR_ACCOUNT_NOT_ACTIVE`."

    A DRAFT order created while ACTIVE; after the account is RESTRICTED a fresh
    accept (the order itself is cancelled by the restrict cascade, but the rule
    under test is the account-active precondition) — here we create a new DRAFT
    order after restriction and accept it.

    Design: Difficulty/cross_entity_state_dependency/order_accept_requires_account_active
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    api.restrict_account(acct["id"], CO_SUBMITTER)
    # New DRAFT order on the now-RESTRICTED account.
    ord_ = draft_order(acct["id"], symbol="ACME", instrument_type="EQUITY", side="BUY",
                       order_type="LIMIT", quantity=1, limit_price_cents=1_000)
    resp = api.accept_order(ord_["id"], HOLDER)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value)


def test_account_close_blocked_by_open_position(api):
    """PRD §3.2: "there must be no `Position` on the account in `OPEN` status,
    otherwise the close is rejected with `ERR_OPEN_POSITIONS`".

    Design: Difficulty/cross_entity_state_dependency/account_close_blocked_by_open_position
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    open_position(acct["id"], symbol="ACME", instrument_type="EQUITY",
                  quantity=10, market_value_cents=1_000_000)
    resp = api.close_account(acct["id"], CO_SUBMITTER)
    validate_error(resp, ApiErrorId.ERR_OPEN_POSITIONS.value)


def test_account_close_blocked_by_pending_transfer(api):
    """PRD §3.2: "and there must be no `AcatTransfer` on the account in
    `REQUESTED` or `VALIDATED` status, otherwise `ERR_PENDING_TRANSFER`."

    Design: Corner/state_machines/account_close_blocked_by_pending_transfer
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    request_acat(acct["id"], direction="IN", transfer_value_cents=100_000)
    resp = api.close_account(acct["id"], CO_SUBMITTER)
    validate_error(resp, ApiErrorId.ERR_PENDING_TRANSFER.value)


def test_acat_settle_on_non_active_account(api):
    """PRD §3.10: "A `Custodian` then settles a `VALIDATED` transfer, moving it
    to `SETTLED`, but only while the parent account is `ACTIVE`, otherwise
    `ERR_ACCOUNT_NOT_ACTIVE`."

    A VALIDATED IN transfer whose account is then RESTRICTED cannot settle.

    Design: Corner/errors/error_acat_settle_on_non_active_account
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    t = validate_acat(acct["id"], direction="IN", transfer_value_cents=100_000)
    api.restrict_account(acct["id"], CO_SUBMITTER)
    resp = api.settle_acat_transfer(t["id"], CUST)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value)


def test_restrict_releases_notional_to_buying_power(api):
    """PRD §3.2: "When the cancelled orders had reserved notional, that notional
    is released back to buying power as described in §3.5, and the account's
    buying power is recomputed."

    A second restrict-cascade assertion focused on buying-power restoration: an
    ACCEPTED order reserving 300000 (buying_power 700000) is cancelled by
    restrict and buying_power returns to 1000000.

    Design: Difficulty/transitive_cascade/restrict_cancels_order_releases_notional_recomputes_buying_power
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    accept_order(acct["id"], symbol="XYZ", instrument_type="EQUITY", side="BUY",
                 order_type="LIMIT", quantity=3, limit_price_cents=100_000)
    assert get_account(acct["id"])["buying_power_cents"] == 700_000
    validate_success(api.restrict_account(acct["id"], CO_SUBMITTER))
    assert validate_success(api.get_account(acct["id"], CO_SUBMITTER))["buying_power_cents"] == 1_000_000


def test_order_accept_blocked_when_account_closed(api):
    """PRD §3.5: "First, the parent account must be `ACTIVE`, otherwise
    `ERR_ACCOUNT_NOT_ACTIVE`."

    A DRAFT order on an account that is then CLOSED cannot be accepted —
    the account-active precondition fails with ERR_ACCOUNT_NOT_ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/order_accept_requires_account_active
    """
    acct = open_and_activate_account(cash_balance_cents=1_000_000)
    ord_ = draft_order(acct["id"], symbol="ACME", instrument_type="EQUITY", side="BUY",
                       order_type="LIMIT", quantity=1, limit_price_cents=1_000)
    validate_success(api.close_account(acct["id"], CO_SUBMITTER))
    resp = api.accept_order(ord_["id"], HOLDER)
    validate_error(resp, ApiErrorId.ERR_ACCOUNT_NOT_ACTIVE.value)


def test_account_close_blocked_by_open_option_position(api):
    """PRD §3.2: "there must be no `Position` on the account in `OPEN` status,
    otherwise the close is rejected with `ERR_OPEN_POSITIONS`".

    An OPEN OPTION position (distinct from the EQUITY case) likewise blocks
    close with ERR_OPEN_POSITIONS.

    Design: Difficulty/cross_entity_state_dependency/account_close_blocked_by_open_position
    """
    acct = open_and_activate_account(cash_balance_cents=100_000_000)
    open_position(acct["id"], symbol="OPT", instrument_type="OPTION",
                  quantity=1, market_value_cents=700_000)
    resp = api.close_account(acct["id"], CO_SUBMITTER)
    validate_error(resp, ApiErrorId.ERR_OPEN_POSITIONS.value)
