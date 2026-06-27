"""Account creation, buying-power variants (CASH vs MARGIN), instant credit.

Covers the Account-domain difficulty instance and the entity / consistency
corner probes.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_account_holder_headers,
    create_account, create_security, funded_cash_account, settled_margin_account,
    deposit, get_account, advance_clock,
    factories as F,
    INSTANT_CAP_CENTS,
)


def _holder(account_id):
    return make_account_holder_headers(account_id)


def test_cash_account_buying_power_is_settled_plus_instant_credit(api):
    """PRD §3.4: "For a `CASH` account, `buying_power_cents` equals `settled_cash_cents` plus
    `instant_credit_cents`, minus the sum of `reserved_buying_power_cents` over all live BUY
    orders; unsettled cash is never spendable in a cash account."

    Design: Difficulty/dual_variant_calc/buying_power_cash_vs_margin_divergence
    """
    account_id, _v = funded_cash_account(amount_cents=500000)
    acc = get_account(account_id)
    # CASH: settled_cash 0 + instant_credit 500000 (no live BUY) = 500000.
    assert acc["account_type"] == "CASH"
    assert acc["settled_cash_cents"] == 0, acc
    assert acc["buying_power_cents"] == 500000, acc


def test_margin_account_buying_power_is_two_times_excess(api):
    """PRD §3.4: "For a `MARGIN` account, the system takes the account equity, subtracts the
    maintenance requirement, multiplies that excess by the leverage multiplier of 2, floors the
    result at zero, and then subtracts the same sum of `reserved_buying_power_cents` over live
    BUY orders."

    Design: Difficulty/dual_variant_calc/buying_power_cash_vs_margin_divergence
    """
    account_id, _v = settled_margin_account(amount_cents=500000)
    acc = get_account(account_id)
    # MARGIN: equity 500000, no positions -> maintenance 0 -> 2*(500000-0) = 1000000.
    assert acc["account_type"] == "MARGIN"
    assert acc["account_equity_cents"] == 500000, acc
    assert acc["buying_power_cents"] == 1000000, acc


def test_create_account_returns_201_with_defaults(api):
    """PRD §2.9: "All of these default to their zero/false/`ACTIVE` baselines at account open:
    equity, all cash fields, buying power, and `day_trade_count` start at 0, `pdt_flagged`
    starts false, `options_level` starts at 0, and `trading_status` starts at `ACTIVE`."
    PRD §2.9: "is opened as one of two `account_type` values, `CASH` or `MARGIN`, defaulting to
    `CASH`."
    PRD §2.4: "`version` is an integer that starts at 1 on creation."

    Design: Corner/entities/create_account_returns_201_with_defaults
    """
    resp = api.create_account(F.create_account_payload(holder_email="new-defaults@x.com"),
                              TEST_USERS["account_holder_headers"])
    acc = validate_success(resp, expected_status=201)
    assert acc["account_type"] == "CASH", acc
    assert acc["trading_status"] == "ACTIVE", acc
    assert acc["options_level"] == 0, acc
    assert acc["buying_power_cents"] == 0, acc
    assert acc["version"] == 1, acc


def test_get_account_not_found_returns_404(api):
    """PRD §2.6: "the system validates the identifiers left-to-right and rejects the request
    with `ERR_NOT_FOUND` at the first identifier in the path that does not resolve to an
    existing resource."

    Design: Corner/entities/get_account_not_found_returns_404
    """
    resp = api.get_account("00000000-0000-0000-0000-000000000000",
                           TEST_USERS["compliance_officer_headers"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_create_account_missing_holder_email_returns_422(api):
    """PRD §2.7: "fourth, request well-formedness — required fields present, enum values legal,
    monetary amounts strictly positive ... else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/create_account_missing_holder_email_returns_422
    """
    resp = api.create_account({"account_type": "CASH"}, TEST_USERS["account_holder_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=422)


def test_immediate_buying_power_visible_in_same_request(api):
    """PRD §3.1: "When instant credit is requested, the system grants a provisional credit
    immediately ... `instant_credit_granted_cents` is set to the requested amount and the
    account's `instant_credit_cents` increases by that same amount."
    PRD §2.10: "every cascade completes synchronously within the triggering request, so a
    subsequent read observes a fully reconciled state."

    Design: Corner/consistency_model/immediate_buying_power_visible_in_same_request
    """
    acc = create_account(account_type="CASH")
    dep = validate_success(
        api.create_deposit(acc["id"], F.create_deposit_payload(amount_cents=75000, instant_eligible=True),
                           _holder(acc["id"])),
        expected_status=201,
    )
    assert dep["instant_credit_granted_cents"] == 75000, dep
    after = get_account(acc["id"])
    assert after["buying_power_cents"] == 75000, after


def test_deposit_settles_on_clock_advance(api):
    """PRD §3.1: "On the operator clock advance, any `PENDING` deposit whose `settles_on` is at
    or before the new clock instant transitions to `SETTLED`: the deposit's `amount_cents` is
    added to `settled_cash_cents`."

    Design: Corner/cross_cutting_complexity_layers/deposit_settles_on_clock_advance
    """
    acc = create_account(account_type="CASH")
    dep = validate_success(
        api.create_deposit(acc["id"], F.create_deposit_payload(amount_cents=100000, instant_eligible=False),
                           _holder(acc["id"])),
        expected_status=201,
    )
    advance_clock("2026-01-03T00:00:00Z")
    deposits = get_success_data(api.list_deposits(acc["id"], _holder(acc["id"])))
    settled = next(d for d in deposits if d["id"] == dep["id"])
    assert settled["status"] == "SETTLED", settled
    after = get_account(acc["id"])
    assert after["settled_cash_cents"] == 100000, after
