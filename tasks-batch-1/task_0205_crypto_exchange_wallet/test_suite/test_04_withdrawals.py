"""Withdrawal whitelist, screening, travel-rule hold, daily ceiling, and the
reject/resubmit cycle with its compensating balance invariant."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, make_trader_headers, make_compliance_headers,
    assert_withdrawal, assert_balance_partition_reconciles, find_balance,
    ApiErrorId,
    set_clock, create_btc_asset, create_eth_asset, create_account, create_account_at_tier,
    create_and_credit_deposit, add_withdrawal_address, add_and_activate_address,
    get_account_version, submit_withdrawal, screen_to, screen_result,
)

OP = TEST_USERS["operator_headers"]


# ===========================================================================
# Difficulty / non_linear_state_machine — reject then resubmit cycle
# ===========================================================================
def _btc_account_with_active_address(clock_base, activate_clock, email, full_name,
                                     chain="0xW", deposit_amount=1.0):
    set_clock(clock_base)
    create_btc_asset()
    acc = create_account_at_tier("TIER_2", email=email, full_name=full_name)
    acc_id = acc["id"]
    create_and_credit_deposit(acc_id, "BTC", deposit_amount, 30000,
                              required_confirmations=1)
    addr = add_and_activate_address(acc_id, "BTC", chain_address=chain,
                                    activate_clock=activate_clock)
    return acc_id, addr["id"]


def test_withdrawal_reject_then_resubmit_creates_fresh_submitted(api):
    """PRD §3.6: "A rejected withdrawal may be resubmitted through a fresh submission
    carrying `replaces_withdrawal_id`, producing a new `SUBMITTED` withdrawal and
    re-entering the cycle."
    PRD §3.6: "A `REJECT` result is permitted while the withdrawal is in `SCREENING`
    or `TRAVEL_RULE_HOLD`, moves it to `REJECTED`"

    Design: Difficulty/non_linear_state_machine/withdrawal_reject_resubmit_cycle
    """
    acc_id, addr_id = _btc_account_with_active_address(
        "2026-05-01T00:00:00Z", "2026-05-02T01:00:00Z", "cyc@x.com", "Cyc",
        chain="0xCYC")
    wd1 = submit_withdrawal(acc_id, addr_id, 0.05)
    screen_to(wd1["id"], "co-7")
    screen_result(wd1["id"], "REJECT", "co-7")
    # resubmit
    wd2 = submit_withdrawal(acc_id, addr_id, 0.05, replaces_withdrawal_id=wd1["id"])
    trader = make_trader_headers(acc_id)
    wd1_final = validate_success(api.get_withdrawal(wd1["id"], trader))
    assert wd1_final["status"] == "REJECTED"
    assert wd2["status"] == "SUBMITTED"
    assert wd2["replaces_withdrawal_id"] == wd1["id"]


def test_withdrawal_resubmit_re_holds_funds(api):
    """PRD §3.6: "A `REJECT` result is permitted while the withdrawal is in
    `SCREENING` or `TRAVEL_RULE_HOLD`, moves it to `REJECTED`, and releases the held
    funds by moving the `amount` plus `network_fee` from `held_amount` back to
    `available_amount`."
    PRD §3.6: "submitting it moves the requested `amount` plus the asset's
    `network_fee` from `available_amount` into `held_amount`."

    Design: Difficulty/non_linear_state_machine/withdrawal_reject_resubmit_cycle
    """
    acc_id, addr_id = _btc_account_with_active_address(
        "2026-05-01T00:00:00Z", "2026-05-02T01:00:00Z", "cyc2@x.com", "Cyc2",
        chain="0xCYC2")
    wd1 = submit_withdrawal(acc_id, addr_id, 0.05)
    screen_to(wd1["id"], "co-7")
    screen_result(wd1["id"], "REJECT", "co-7")
    submit_withdrawal(acc_id, addr_id, 0.05, replaces_withdrawal_id=wd1["id"])
    trader = make_trader_headers(acc_id)
    bals, _ = validate_paginated(api.list_balances(trader, params={"account_id": acc_id, "asset": "BTC"}))
    btc = find_balance(bals, "BTC")
    # amount 0.05 + network_fee 0.0001 re-held after resubmit
    assert btc["held_amount"] == pytest.approx(0.0501, abs=1e-9)


# ===========================================================================
# Difficulty / cross_entity_state_dependency — withdrawal requires ACTIVE address
# ===========================================================================
def test_withdrawal_against_pending_hold_address_rejected(api):
    """PRD §3.6: "The target address must itself be `ACTIVE` and past its
    `activates_at`, or the request is rejected with `ERR_ADDRESS_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/withdrawal_requires_address_active
    """
    set_clock("2026-12-01T00:00:00Z")
    create_btc_asset()
    acc = create_account_at_tier("TIER_1", email="ce1@x.com", full_name="CE1")
    acc_id = acc["id"]
    create_and_credit_deposit(acc_id, "BTC", 1.0, 30000, required_confirmations=1)
    # add address but do NOT activate (still PENDING_HOLD inside the 24h window)
    addr = add_withdrawal_address(acc_id, "BTC", chain_address="0xCE")
    resp = api.create_withdrawal(
        {"account_id": acc_id, "withdrawal_address_id": addr["id"], "amount": 0.01},
        make_trader_headers(acc_id))
    validate_error(resp, ApiErrorId.ERR_ADDRESS_NOT_ACTIVE.value)


def test_withdrawal_against_active_address_succeeds(api):
    """PRD §3.5: "A `Trader` activates an address once the hold has elapsed, moving
    it along `PENDING_HOLD → ACTIVE`; this is defined only when the address is
    `PENDING_HOLD` and the current clock is at or after the address's `activates_at`."
    PRD §3.6: "A new withdrawal begins with a `status` of `SUBMITTED`"

    Design: Difficulty/cross_entity_state_dependency/withdrawal_requires_address_active
    """
    acc_id, addr_id = _btc_account_with_active_address(
        "2026-12-01T00:00:00Z", "2026-12-02T01:00:00Z", "ce1b@x.com", "CE1B",
        chain="0xCE1B")
    wd = submit_withdrawal(acc_id, addr_id, 0.01)
    assert wd["status"] == "SUBMITTED"
    assert_withdrawal(wd)


# ===========================================================================
# Difficulty / resource_temporal_overlap — half-open address hold window
# ===========================================================================
def test_address_hold_overlap_inside_window_rejected(api):
    """PRD §3.5: "adding an address for a triple of `account_id`, `asset`, and
    `chain_address` is rejected with `ERR_ADDRESS_HOLD_OVERLAP` while a non-removed
    row for that same triple is still inside its twenty-four-hour hold window. The
    hold window is half-open from the existing row's `created_at` up to but not
    including its `activates_at`: if the current clock falls at or after `created_at`
    and strictly before `activates_at`, the windows overlap and the add is rejected"

    Design: Difficulty/resource_temporal_overlap/whitelist_address_halfopen_hold_overlap
    """
    set_clock("2027-01-01T00:00:00Z")
    create_btc_asset()
    acc = create_account_at_tier("TIER_1", email="ov1@x.com", full_name="OV1")
    acc_id = acc["id"]
    trader = make_trader_headers(acc_id)
    v1 = get_account_version(acc_id, trader)
    validate_success(api.create_withdrawal_address(
        {"account_id": acc_id, "asset": "BTC", "chain_address": "0xDUP",
         "label": "first", "expected_account_version": v1}, trader), 201)
    # advance clock to inside the 24h window (12h)
    set_clock("2027-01-01T12:00:00Z")
    v2 = get_account_version(acc_id, trader)
    resp = api.create_withdrawal_address(
        {"account_id": acc_id, "asset": "BTC", "chain_address": "0xDUP",
         "label": "dup", "expected_account_version": v2}, trader)
    validate_error(resp, ApiErrorId.ERR_ADDRESS_HOLD_OVERLAP.value)


def test_address_hold_overlap_at_activates_at_allowed(api):
    """PRD §3.5: "once the current clock reaches `activates_at`, the window no longer
    overlaps and an add for the same triple is allowed."
    PRD §3.5: "A new address is created with a `status` of `PENDING_HOLD` and an
    `activates_at` set to its `created_at` plus twenty-four hours"

    Design: Difficulty/resource_temporal_overlap/whitelist_address_halfopen_hold_overlap
    """
    set_clock("2027-01-01T00:00:00Z")
    create_btc_asset()
    acc = create_account_at_tier("TIER_1", email="ov1b@x.com", full_name="OV1B")
    acc_id = acc["id"]
    trader = make_trader_headers(acc_id)
    v1 = get_account_version(acc_id, trader)
    validate_success(api.create_withdrawal_address(
        {"account_id": acc_id, "asset": "BTC", "chain_address": "0xDUP2",
         "label": "first", "expected_account_version": v1}, trader), 201)
    # at exactly activates_at (created_at + 24h) the half-open window no longer contains the point
    set_clock("2027-01-02T00:00:00Z")
    v2 = get_account_version(acc_id, trader)
    resp = api.create_withdrawal_address(
        {"account_id": acc_id, "asset": "BTC", "chain_address": "0xDUP2",
         "label": "second", "expected_account_version": v2}, trader)
    data = validate_success(resp, 201)
    assert data["status"] == "PENDING_HOLD"


# ===========================================================================
# Difficulty / priority_pair_validation_conflict — CLEAR on travel-rule-required
# ===========================================================================
def test_clear_on_travel_rule_required_returns_travel_rule_required(api):
    """PRD §3.6: "attempting `CLEAR` on a withdrawal whose notional meets the
    travel-rule threshold is rejected with `ERR_TRAVEL_RULE_REQUIRED`, because such a
    withdrawal must route through a hold and a filed record instead."

    Design: Difficulty/priority_pair_validation_conflict/travel_rule_required_beats_daily_limit_safety_vs_fiscal
    """
    set_clock("2026-10-01T00:00:00Z")
    create_btc_asset()
    acc = create_account_at_tier("TIER_2", email="tr1@x.com", full_name="TR1")
    acc_id = acc["id"]
    create_and_credit_deposit(acc_id, "BTC", 1.0, 30000, required_confirmations=1)
    addr = add_and_activate_address(acc_id, "BTC", chain_address="0xTR",
                                    activate_clock="2026-10-02T01:00:00Z")
    # 0.1 BTC at spot 40000 -> notional 4000 (>= 3000), requires_travel_rule true
    wd = submit_withdrawal(acc_id, addr["id"], 0.1)
    assert wd["requires_travel_rule"] is True
    screen_to(wd["id"], "co-9")
    co = make_compliance_headers("co-9")
    resp = api.screen_result(wd["id"], {"result": "CLEAR"}, co)
    validate_error(resp, ApiErrorId.ERR_TRAVEL_RULE_REQUIRED.value)


def test_travel_rule_required_withdrawal_stays_screening_after_clear_rejection(api):
    """PRD §2.10: "a transition attempted from a state where it is not defined is
    rejected with `ERR_INVALID_STATE`"
    PRD §3.6: "attempting `CLEAR` on a withdrawal whose notional meets the
    travel-rule threshold is rejected with `ERR_TRAVEL_RULE_REQUIRED`, because such a
    withdrawal must route through a hold and a filed record instead."

    Design: Difficulty/priority_pair_validation_conflict/travel_rule_required_beats_daily_limit_safety_vs_fiscal
    """
    set_clock("2026-10-01T00:00:00Z")
    create_btc_asset()
    acc = create_account_at_tier("TIER_2", email="tr1b@x.com", full_name="TR1B")
    acc_id = acc["id"]
    create_and_credit_deposit(acc_id, "BTC", 1.0, 30000, required_confirmations=1)
    addr = add_and_activate_address(acc_id, "BTC", chain_address="0xTRB",
                                    activate_clock="2026-10-02T01:00:00Z")
    wd = submit_withdrawal(acc_id, addr["id"], 0.1)
    screen_to(wd["id"], "co-9")
    co = make_compliance_headers("co-9")
    api.screen_result(wd["id"], {"result": "CLEAR"}, co)
    trader = make_trader_headers(acc_id)
    after = validate_success(api.get_withdrawal(wd["id"], trader))
    assert after["status"] == "SCREENING"


# ===========================================================================
# Difficulty / compensating_invariant — reject conserves BTC total holdings
# ===========================================================================
def test_withdrawal_submit_moves_available_to_held(api):
    """PRD §3.6: "submitting it moves the requested `amount` plus the asset's
    `network_fee` from `available_amount` into `held_amount`."
    PRD §2.6: "The `total_amount` is the sum of `available_amount`,
    `reserved_amount`, and `held_amount`"

    Design: Difficulty/compensating_invariant/withdrawal_reject_conserves_asset_total_holdings
    """
    acc_id, addr_id = _btc_account_with_active_address(
        "2027-04-01T00:00:00Z", "2027-04-02T01:00:00Z", "ci2a@x.com", "CI2A",
        chain="0xCI2A")
    wd = submit_withdrawal(acc_id, addr_id, 0.5)
    screen_to(wd["id"], "co-15")
    trader = make_trader_headers(acc_id)
    bals, _ = validate_paginated(api.list_balances(trader, params={"account_id": acc_id, "asset": "BTC"}))
    btc = find_balance(bals, "BTC")
    assert btc["held_amount"] == pytest.approx(0.5001, abs=1e-9)
    assert btc["available_amount"] == pytest.approx(0.4999, abs=1e-9)
    assert btc["total_amount"] == pytest.approx(1.0, abs=1e-9)
    assert_balance_partition_reconciles(btc)


def test_withdrawal_reject_restores_total_holdings(api):
    """PRD §3.6: "A `REJECT` result is permitted while the withdrawal is in
    `SCREENING` or `TRAVEL_RULE_HOLD`, moves it to `REJECTED`, and releases the held
    funds by moving the `amount` plus `network_fee` from `held_amount` back to
    `available_amount`."
    PRD §2.6: "the `total_amount` is the sum of `available_amount`,
    `reserved_amount`, and `held_amount`"

    Design: Difficulty/compensating_invariant/withdrawal_reject_conserves_asset_total_holdings
    """
    acc_id, addr_id = _btc_account_with_active_address(
        "2027-04-01T00:00:00Z", "2027-04-02T01:00:00Z", "ci2b@x.com", "CI2B",
        chain="0xCI2B")
    wd = submit_withdrawal(acc_id, addr_id, 0.5)
    screen_to(wd["id"], "co-15")
    screen_result(wd["id"], "REJECT", "co-15")
    trader = make_trader_headers(acc_id)
    bals, _ = validate_paginated(api.list_balances(trader, params={"account_id": acc_id, "asset": "BTC"}))
    btc = find_balance(bals, "BTC")
    assert btc["held_amount"] == pytest.approx(0.0, abs=1e-9)
    assert btc["available_amount"] == pytest.approx(1.0, abs=1e-9)
    assert btc["total_amount"] == pytest.approx(1.0, abs=1e-9)
    assert_balance_partition_reconciles(btc)


# ===========================================================================
# Corner / state_machines — terminal COMPLETED lockdown
# ===========================================================================
def test_withdrawal_completed_cannot_be_rebroadcast(api):
    """PRD §3.6: "The `status` field ranges over `SUBMITTED`, `SCREENING`,
    `TRAVEL_RULE_HOLD`, `APPROVED`, `BROADCAST`, `COMPLETED`, and `REJECTED`;
    `COMPLETED` and `REJECTED` are terminal."
    PRD §2.10: "a transition attempted from a state where it is not defined is
    rejected with `ERR_INVALID_STATE`"

    Design: Corner/state_machines/withdrawal_terminal_completed_lockdown
    """
    set_clock("2027-05-01T00:00:00Z")
    create_btc_asset()
    acc = create_account_at_tier("TIER_1", email="wt@x.com", full_name="WT")
    acc_id = acc["id"]
    create_and_credit_deposit(acc_id, "BTC", 1.0, 30000, required_confirmations=1)
    addr = add_and_activate_address(acc_id, "BTC", chain_address="0xWT",
                                    activate_clock="2027-05-02T01:00:00Z")
    # 0.01 BTC notional 400 (below travel rule)
    wd = submit_withdrawal(acc_id, addr["id"], 0.01)
    screen_to(wd["id"], "co-21")
    screen_result(wd["id"], "CLEAR", "co-21")
    validate_success(api.broadcast_withdrawal(wd["id"], OP))
    validate_success(api.confirm_onchain_withdrawal(wd["id"], OP))
    resp = api.broadcast_withdrawal(wd["id"], OP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner / state_machines — activate before hold elapsed
# ===========================================================================
def test_address_activate_before_hold_elapsed_invalid_state(api):
    """PRD §3.5: "A `Trader` activates an address once the hold has elapsed, moving
    it along `PENDING_HOLD → ACTIVE`; this is defined only when the address is
    `PENDING_HOLD` and the current clock is at or after the address's `activates_at`."

    Design: Corner/state_machines/address_activate_before_hold_elapsed_returns_invalid_state
    """
    set_clock("2027-06-01T00:00:00Z")
    create_btc_asset()
    acc = create_account(email="ah@x.com", full_name="AH")
    acc_id = acc["id"]
    addr = add_withdrawal_address(acc_id, "BTC", chain_address="0xAH")
    # only 1h of the 24h hold elapsed
    set_clock("2027-06-01T01:00:00Z")
    resp = api.activate_withdrawal_address(addr["id"], make_trader_headers(acc_id))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Corner / calculations — daily withdrawal limit aggregate blocks second
# ===========================================================================
def test_daily_withdrawal_limit_blocks_second(api):
    """PRD §3.7: "A new withdrawal is admitted only when that running used total plus
    the new withdrawal's `notional_usd` is at most the ceiling for the account's
    tier. The ceilings are 0 USD at `TIER_0`, 1,000 USD at `TIER_1`, 50,000 USD at
    `TIER_2`, and 1,000,000 USD at `TIER_3`"

    Design: Corner/calculations/daily_withdrawal_limit_aggregate_blocks_second
    """
    set_clock("2027-09-02T08:00:00Z")
    create_btc_asset()
    acc = create_account_at_tier("TIER_1", email="dwl@x.com", full_name="DWL")
    acc_id = acc["id"]
    create_and_credit_deposit(acc_id, "BTC", 1.0, 30000, required_confirmations=1)
    addr = add_and_activate_address(acc_id, "BTC", chain_address="0xDW",
                                    activate_clock="2027-09-03T08:00:00Z")
    # first 0.02 BTC -> notional 800 succeeds
    submit_withdrawal(acc_id, addr["id"], 0.02)
    # second same-day 0.02 BTC -> 800 + 800 = 1600 > 1000 ceiling
    resp = api.create_withdrawal(
        {"account_id": acc_id, "withdrawal_address_id": addr["id"], "amount": 0.02},
        make_trader_headers(acc_id))
    validate_error(resp, ApiErrorId.ERR_DAILY_LIMIT_EXCEEDED.value)


# ===========================================================================
# Corner / validations — below minimum withdrawal
# ===========================================================================
def test_withdrawal_below_min_rejected(api):
    """PRD §3.6: "The requested amount must be at least the asset's
    `min_withdrawal_amount`, or the request is rejected with
    `ERR_BELOW_MIN_WITHDRAWAL`."

    Design: Corner/validations/withdrawal_below_min_rejected
    """
    set_clock("2027-10-01T00:00:00Z")
    create_btc_asset()
    acc = create_account_at_tier("TIER_1", email="bm@x.com", full_name="BM")
    acc_id = acc["id"]
    create_and_credit_deposit(acc_id, "BTC", 1.0, 30000, required_confirmations=1)
    addr = add_and_activate_address(acc_id, "BTC", chain_address="0xBM",
                                    activate_clock="2027-10-02T01:00:00Z")
    resp = api.create_withdrawal(
        {"account_id": acc_id, "withdrawal_address_id": addr["id"], "amount": 0.00005},
        make_trader_headers(acc_id))
    validate_error(resp, ApiErrorId.ERR_BELOW_MIN_WITHDRAWAL.value)


# ===========================================================================
# Corner / validations — resubmit pointing at a non-REJECTED withdrawal
# ===========================================================================
def test_resubmit_non_rejected_target_invalid(api):
    """PRD §3.6: "when a `replaces_withdrawal_id` is supplied it must reference a
    `REJECTED` withdrawal of the same account and the same address; a mismatch on
    either count is rejected with `ERR_RESUBMIT_TARGET_INVALID`."

    Design: Corner/validations/resubmit_non_rejected_target_invalid
    """
    set_clock("2027-11-01T00:00:00Z")
    create_btc_asset()
    acc = create_account_at_tier("TIER_1", email="rs@x.com", full_name="RS")
    acc_id = acc["id"]
    create_and_credit_deposit(acc_id, "BTC", 1.0, 30000, required_confirmations=1)
    addr = add_and_activate_address(acc_id, "BTC", chain_address="0xRS",
                                    activate_clock="2027-11-02T01:00:00Z")
    wd_open = submit_withdrawal(acc_id, addr["id"], 0.01)  # stays SUBMITTED
    resp = api.create_withdrawal(
        {"account_id": acc_id, "withdrawal_address_id": addr["id"], "amount": 0.01,
         "replaces_withdrawal_id": wd_open["id"]},
        make_trader_headers(acc_id))
    validate_error(resp, ApiErrorId.ERR_RESUBMIT_TARGET_INVALID.value)


# ===========================================================================
# Corner / rbac — segregation of duties (same officer screens + files)
# ===========================================================================
def test_segregation_of_duties_same_officer_filing_rejected(api):
    """PRD §3.6: "Filing is permitted only when the filing officer's `X-User-ID`
    differs from the `X-User-ID` of the officer who screened that same withdrawal; a
    maker-checker collision where the same user both screened and files is rejected
    with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/rbac/segregation_of_duties_same_officer_excluded
    """
    set_clock("2028-02-01T00:00:00Z")
    create_btc_asset()
    acc = create_account_at_tier("TIER_2", email="sod@x.com", full_name="SOD")
    acc_id = acc["id"]
    create_and_credit_deposit(acc_id, "BTC", 1.0, 30000, required_confirmations=1)
    addr = add_and_activate_address(acc_id, "BTC", chain_address="0xSOD",
                                    activate_clock="2028-02-02T01:00:00Z")
    # 0.1 BTC notional 4000 -> travel rule; screen+HOLD by co-A
    wd = submit_withdrawal(acc_id, addr["id"], 0.1)
    screen_to(wd["id"], "co-A")
    screen_result(wd["id"], "HOLD", "co-A")
    # same officer co-A tries to file the travel-rule record
    co_a = make_compliance_headers("co-A")
    resp = api.file_travel_rule_record(
        wd["id"],
        {"originator_name": "SOD User", "beneficiary_name": "Bene",
         "beneficiary_vasp": "VASP-1"},
        co_a)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)
