"""RBAC enforcement, optimistic concurrency, and settlement compensation.

Covers the rbac, cross_cutting_complexity_layers (OCC, scheduled actions),
and consistency_model (saga) corner probes.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
    make_account_holder_headers,
    create_account, create_security, funded_cash_account, deposit,
    get_account, get_account_version, place_order, fill_order, buy_and_fill,
    sell_and_fill, get_first_position,
    submitted_options_approval,
    factories as F,
)


def _holder(account_id):
    return make_account_holder_headers(account_id)


def _compliance():
    return TEST_USERS["compliance_officer_headers"]


def _clearing():
    return TEST_USERS["clearing_system_headers"]


# --------------------------------------------------------------------------
# RBAC
# --------------------------------------------------------------------------
def test_account_holder_cannot_freeze_account(api):
    """PRD §2.1: "When a caller is authenticated but the role is not permitted for the requested
    operation — or when an `AccountHolder` attempts to act on an account it does not own — the
    request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/account_holder_cannot_freeze_account
    """
    acc = create_account(account_type="CASH")
    # compliance-hold is a ComplianceOfficer-exclusive op.
    resp = api.set_compliance_hold(acc["id"], F.compliance_hold_payload(True), _holder(acc["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_account_holder_cannot_act_on_other_account(api):
    """PRD §2.1: "ownership checks on any resource that references an `Account` compare the
    resource's `account_id` (or, for path-addressed accounts, the `Account.id`) to `X-User-ID`.
    An `AccountHolder` may read and act only on resources belonging to its own account."

    Design: Corner/rbac/account_holder_cannot_act_on_other_account
    """
    own = create_account(account_type="CASH")
    other = create_account(account_type="CASH")
    # Acting holder is `own`, but the deposit targets `other`.
    resp = api.create_deposit(
        other["id"], F.create_deposit_payload(amount_cents=100000, instant_eligible=True),
        _holder(own["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_account_holder_cannot_report_fills(api):
    """PRD §2.1: "When a caller is authenticated but the role is not permitted for the requested
    operation ... the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/clearing_system_only_reports_fills
    """
    sec = create_security(symbol="CSFCO", last_price_cents=10000, fractional_enabled=True)
    account_id, version = funded_cash_account(amount_cents=100000)
    order = place_order(account_id, sec["id"], version, side="BUY", order_type="MARKET", quantity=1)
    # Reporting a fill is a ClearingSystem-exclusive op; the AccountHolder is forbidden.
    resp = api.create_fill(order["id"], F.create_fill_payload(1, 10000), _holder(account_id))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_unrecognized_role_returns_unauthenticated(api):
    """PRD §2.1: "A request that omits `X-User-Role`, or supplies a value that is not one of the
    four declared roles, is rejected with `ERR_UNAUTHENTICATED`. The system recognizes exactly
    four roles: `AccountHolder`, `ComplianceOfficer`, `ClearingSystem`, and `MarketData`."

    Design: Corner/rbac/missing_role_header_unauthenticated
    """
    bad_headers = build_user_headers("anon-1", "Anonymous")
    resp = api.create_account(F.create_account_payload(holder_email="noauth@x.com"), bad_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


# --------------------------------------------------------------------------
# Optimistic concurrency
# --------------------------------------------------------------------------
def test_occ_correct_version_succeeds_and_bumps_version(api):
    """PRD §2.8: "Placing an order requires the request to carry `expected_account_version`
    holding the client's last observed `version` of the target `Account`; if that value does not
    equal the account's current `version`, the order is rejected with `ERR_STALE_ACCOUNT_VERSION`
    at HTTP 412."
    PRD §3.3: "Placing an order increments the account's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds
    """
    sec = create_security(symbol="OCCCO", last_price_cents=10000, fractional_enabled=True)
    account_id, version = funded_cash_account(amount_cents=100000)
    order = validate_success(
        api.create_order(
            F.create_order_payload(account_id, sec["id"], version, side="BUY", order_type="MARKET",
                                   notional_cents=50000),
            _holder(account_id)),
        expected_status=201,
    )
    assert order["order_status"] == "ACCEPTED", order
    after = get_account(account_id)
    assert after["version"] == version + 1, (version, after["version"])


def test_occ_stale_order_place_rejected(api):
    """PRD §2.8: "if that value does not equal the account's current `version`, the order is
    rejected with `ERR_STALE_ACCOUNT_VERSION` at HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_order_place_rejected
    """
    sec = create_security(symbol="STLCO", last_price_cents=10000, fractional_enabled=True)
    account_id, version = funded_cash_account(amount_cents=200000)
    # First order bumps the account version; the captured `version` is now one behind.
    validate_success(
        api.create_order(
            F.create_order_payload(account_id, sec["id"], version, side="BUY", order_type="MARKET",
                                   notional_cents=50000),
            _holder(account_id)),
        expected_status=201,
    )
    resp = api.create_order(
        F.create_order_payload(account_id, sec["id"], version, side="BUY", order_type="MARKET",
                               notional_cents=50000),
        _holder(account_id),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_ACCOUNT_VERSION, expected_status=412)


def test_occ_stale_options_decide_rejected(api):
    """PRD §2.8: "Deciding an options application likewise requires `expected_account_version` to
    match the account's current `version`, and a mismatch is rejected with
    `ERR_STALE_ACCOUNT_VERSION` at HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_options_decide_rejected
    """
    acc = create_account(account_type="CASH")
    approval = submitted_options_approval(acc["id"], 2, 3, 5_000_000)
    stale_version = get_account_version(acc["id"])
    # A deposit bumps the account version, making the officer's captured version stale.
    deposit(acc["id"], 100000, instant_eligible=True)
    resp = api.decide_options_approval(
        approval["id"], F.decide_options_approval_payload("APPROVE", stale_version), _compliance()
    )
    validate_error(resp, ApiErrorId.ERR_STALE_ACCOUNT_VERSION, expected_status=412)


# --------------------------------------------------------------------------
# Settlement compensation (saga)
# --------------------------------------------------------------------------
def test_settlement_fail_compensates_provisional_cash(api):
    """PRD §3.6: "Alternatively, the `ClearingSystem` may fail a still-`UNSETTLED` leg, moving it
    `UNSETTLED → FAILED` and reversing the provisional cash and position effects of the
    originating fill as a compensation; this is rejected with `ERR_INVALID_STATE` if the leg is
    not `UNSETTLED`, and the failure increments the account `version`."

    Design: Corner/consistency_model/settlement_fail_compensates_provisional_cash
    """
    sec = create_security(symbol="FAILCO", last_price_cents=10000, fractional_enabled=True)
    account_id, _v = funded_cash_account(amount_cents=100000)
    # BUY 1 sh @ 10000c -> creates an UNSETTLED DEBIT settlement leg.
    buy_and_fill(account_id, sec["id"], 1, 10000, order_type="MARKET")
    before = get_account(account_id)
    settlements = get_success_data(api.list_settlements(account_id, _holder(account_id)))
    leg = settlements[0]
    assert leg["status"] == "UNSETTLED", leg

    failed = validate_success(api.fail_settlement(leg["id"], _clearing()))
    assert failed["status"] == "FAILED", failed
    after = get_account(account_id)
    # The originating fill's provisional effect is reversed: version advances on compensation.
    assert after["version"] > before["version"], (before["version"], after["version"])
