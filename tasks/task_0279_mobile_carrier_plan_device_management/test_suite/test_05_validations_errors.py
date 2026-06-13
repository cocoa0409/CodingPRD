"""Validation and error-path behavior: precedence under a single faithful
outcome, cross-entity state dependencies, temporal/resource overlaps, and the
corner-queue violation-to-error catalogue.

Translates difficulty queue (A) priority_pair_validation_conflict,
cross_entity_state_dependency, and resource_temporal_overlap instances, plus
corner queue (B) validations and errors instances.
"""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, make_subscriber_headers,
    create_addon_payload, create_installment_plan_payload, create_line_payload,
    create_usage_record_payload,
    setup_account_plan, setup_active_line, setup_active_line_on_open_cycle,
    set_clock, create_device, create_billing_cycle,
    SAMPLE_MISSING_UUID,
)
import test_helpers as H

CA = TEST_USERS["carrier_agent_headers"]
BS = TEST_USERS["billing_system_headers"]
PO = TEST_USERS["porting_ops_headers"]


# ─── Queue A: priority_pair_validation_conflict ───────────────────────────

def test_reconnect_active_line_on_delinquent_account_invalid_state(api):
    """PRD §3.4: "A reconnect is only defined from `SUSPENDED`, again failing
    with `ERR_INVALID_STATE` otherwise". PRD §3.4: "if the line was suspended for
    `NONPAYMENT`, reconnect is permitted only when the account's
    `wallet_credit_cents` is at least 0 and the account `status` is not
    `DELINQUENT`".

    Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_reconnect_invalid_state_wins
    """
    account, plan, line = setup_active_line(sim_type="PHYSICAL")  # never suspended
    validate_success(api.mark_delinquent(account["id"], {"delinquent": True}, BS), 200)

    res = api.reconnect_line(line["id"], CA)
    # Line is ACTIVE (not SUSPENDED): the state check is the only error that can
    # fire — the NONPAYMENT fiscal gate is unreachable without a NONPAYMENT suspend.
    validate_error(res, "ERR_INVALID_STATE")


def test_validate_missing_port_request_not_found(api):
    """PRD §2.4: "that identifier is validated for existence before the operation
    runs. When more than one identifier appears in a path, validation proceeds
    left to right and the first identifier that does not resolve to a stored
    entity produces `ERR_NOT_FOUND` (HTTP 404)."

    Design: Difficulty/priority_pair_validation_conflict/existence_vs_referential_port_not_found_wins
    """
    account, plan = setup_account_plan()  # account/line exist, port-request does not
    res = api.validate_port_request(SAMPLE_MISSING_UUID, {"account_pin": "0000"}, PO)
    validate_error(res, "ERR_NOT_FOUND")


# ─── Queue A: cross_entity_state_dependency ───────────────────────────────

def test_line_activate_blocked_by_retired_plan(api):
    """PRD §3.2: "the plan referenced by `plan_id` must still be `ACTIVE`, failing
    with `ERR_PLAN_RETIRED` otherwise". PRD §3.1: "retiring a plan moves it from
    `ACTIVE` to `RETIRED`, after which it can no longer back a new line."

    Design: Difficulty/cross_entity_state_dependency/line_activate_requires_plan_active
    """
    account, plan = setup_account_plan()
    line = H.provision_line(account["id"], plan["id"], sim_type="PHYSICAL")
    H.issue_sim(line["id"], sim_type="PHYSICAL")
    validate_success(api.retire_plan(plan["id"], CA), 200)

    res = api.activate_line(line["id"], CA)
    validate_error(res, "ERR_PLAN_RETIRED")


def test_line_reconnect_blocked_by_non_active_account(api):
    """PRD §3.4: "it additionally requires the owning account to be `ACTIVE`,
    failing with `ERR_ACCOUNT_NOT_ACTIVE` if the account is `DELINQUENT`."

    Design: Difficulty/cross_entity_state_dependency/line_reconnect_requires_account_active
    """
    account, plan, line = setup_active_line(sim_type="PHYSICAL")
    validate_success(api.suspend_line(line["id"], {"suspend_reason": "VOLUNTARY"}, CA), 200)
    validate_success(api.mark_delinquent(account["id"], {"delinquent": True}, BS), 200)

    res = api.reconnect_line(line["id"], CA)
    validate_error(res, "ERR_ACCOUNT_NOT_ACTIVE")


# ─── Queue A: resource_temporal_overlap ───────────────────────────────────

def test_daypass_addon_overlap_rejected(api):
    """PRD §3.8: "two `ROAMING_DAYPASS` add-ons on the same line must not overlap:
    their half-open day-ranges from `window_start` (inclusive) to `window_end`
    (exclusive) must not intersect, though exact adjacency where one ends
    precisely as the next begins is permitted. An overlap is rejected with
    `ERR_ADDON_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/daypass_addon_overlap_half_open_on_line
    """
    account, plan, line = setup_active_line(sim_type="PHYSICAL")
    sub = make_subscriber_headers(account["id"])
    validate_success(api.create_addon(
        create_addon_payload(line["id"], "ROAMING_DAYPASS",
                             "2026-06-10T00:00:00Z", "2026-06-15T00:00:00Z",
                             daily_fee_cents=1000), sub), 201)

    res = api.create_addon(
        create_addon_payload(line["id"], "ROAMING_DAYPASS",
                             "2026-06-12T00:00:00Z", "2026-06-16T00:00:00Z",
                             daily_fee_cents=1000), sub)
    validate_error(res, "ERR_ADDON_OVERLAP")


def test_portin_number_already_in_use_rejected(api):
    """PRD §3.7: "For a port-in, the requested `external_number` must not already
    be live on another line: if any line currently holds that number as a
    non-null `phone_number`, the request is rejected with `ERR_NUMBER_IN_USE`
    (HTTP 409)".

    Design: Difficulty/resource_temporal_overlap/portin_number_in_use_uniqueness_on_line_pool
    """
    account, plan, line_a = setup_active_line(sim_type="PHYSICAL")
    H.complete_port_in(account["id"], line_a["id"],
                       external_number="12025550111", account_pin="5555")
    line_b = H.provision_line(account["id"], plan["id"], sim_type="PHYSICAL")

    res = api.create_port_request(
        {"line_id": line_b["id"], "direction": "PORT_IN",
         "external_number": "12025550111", "donor_carrier": "OtherCo",
         "account_pin": "6666"},
        make_subscriber_headers(account["id"]))
    validate_error(res, "ERR_NUMBER_IN_USE")


# ─── Queue B: validations corners ─────────────────────────────────────────

def test_addon_window_end_before_start_rejected(api):
    """PRD §3.8: "The window must be well-formed: `window_end` must be strictly
    after `window_start`, and for a `ROAMING_DAYPASS` the window must span a whole
    number of UTC days; either violation is rejected with `ERR_INVALID_WINDOW`
    (HTTP 422)."

    Design: Corner/validations/invalid_addon_window_end_before_start
    """
    account, plan, line = setup_active_line(sim_type="PHYSICAL")
    res = api.create_addon(
        create_addon_payload(line["id"], "ROAMING_DAYPASS",
                             "2026-06-15T00:00:00Z", "2026-06-10T00:00:00Z",
                             daily_fee_cents=1000),
        make_subscriber_headers(account["id"]))
    validate_error(res, "ERR_INVALID_WINDOW")


def test_usage_outside_open_cycle_rejected(api):
    """PRD §3.9: "The `occurred_at` must fall inside an open billing cycle for the
    line's account — that is, at or after the cycle's `cycle_start` and strictly
    before its `cycle_end`, with the cycle in `OPEN` status; a usage event outside
    any open cycle is rejected with `ERR_USAGE_OUTSIDE_CYCLE` (HTTP 422)."

    Design: Corner/validations/usage_outside_open_cycle_rejected
    """
    account, plan, line, cycle = setup_active_line_on_open_cycle(
        clock_after_activate=None, sim_type="ESIM")
    res = api.create_usage_record(
        create_usage_record_payload(line["id"], usage_type="DATA",
                                    data_mb=100, occurred_at="2026-08-15T00:00:00Z"), CA)
    validate_error(res, "ERR_USAGE_OUTSIDE_CYCLE")


def test_eip_down_payment_exceeds_retail_rejected(api):
    """PRD §3.6: "the down payment must be strictly less than the device's retail
    price, meaning `down_payment_cents` is less than `retail_price_cents`; either
    failure is reported as `ERR_DEVICE_UNAVAILABLE` (HTTP 409)."

    Design: Corner/validations/eip_down_payment_exceeds_retail_rejected
    """
    account, plan, line = setup_active_line(sim_type="PHYSICAL")
    device = create_device(retail_price_cents=50000, stock_count=3)
    res = api.create_installment_plan(
        create_installment_plan_payload(line["id"], device["id"],
                                        term_months=12, down_payment_cents=60000), CA)
    validate_error(res, "ERR_DEVICE_UNAVAILABLE")


def test_close_cycle_before_end_rejected(api):
    """PRD §3.10: "only once the clock has reached the cycle's end, meaning
    current UTC is at or after `cycle_end` (otherwise `ERR_CYCLE_NOT_ENDED`, HTTP
    409)."

    Design: Corner/validations/close_cycle_before_end_rejected
    """
    account, plan = setup_account_plan()
    set_clock("2026-06-10T00:00:00Z")
    cycle = create_billing_cycle(account["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z")
    res = api.close_billing_cycle(cycle["id"], BS)
    validate_error(res, "ERR_CYCLE_NOT_ENDED")


# ─── Queue B: errors corners ──────────────────────────────────────────────

def test_activate_without_issued_sim_rejected(api):
    """PRD §3.2: "First, the line must already have a SIM assignment in `status`
    `ISSUED`; absent one, activation fails with `ERR_SIM_NOT_ISSUED` (HTTP 409)."

    Design: Corner/errors/error_sim_not_issued_on_activate_without_sim
    """
    account, plan = setup_account_plan()
    line = H.provision_line(account["id"], plan["id"], sim_type="PHYSICAL")  # no SIM issued
    res = api.activate_line(line["id"], CA)
    validate_error(res, "ERR_SIM_NOT_ISSUED")


def test_provision_line_with_unresolvable_plan_fk(api):
    """PRD §3.2: "the body foreign keys must resolve — an unresolvable `plan_id`
    yields `ERR_FK_NOT_FOUND`".

    Design: Corner/errors/error_fk_not_found_on_line_with_bad_plan
    """
    account = H.create_account()
    res = api.create_line(
        create_line_payload(account["id"], "00000000-0000-4000-8000-0000000000bb",
                            account["version"], sim_type="ESIM"), CA)
    validate_error(res, "ERR_FK_NOT_FOUND")


def test_eip_on_zero_stock_device_rejected(api):
    """PRD §3.6: "the device must have stock, meaning `stock_count` is greater
    than 0, and the down payment must be strictly less than the device's retail
    price, meaning `down_payment_cents` is less than `retail_price_cents`; either
    failure is reported as `ERR_DEVICE_UNAVAILABLE` (HTTP 409)." PRD §3.6:
    "Opening the EIP decrements the device's `stock_count` by one and recomputes
    the account's `total_eip_outstanding_cents`."

    Design: Corner/errors/error_device_unavailable_when_stock_zero
    """
    account, plan, line = setup_active_line(sim_type="PHYSICAL")
    device = create_device(retail_price_cents=80000, stock_count=1)
    validate_success(api.create_installment_plan(
        create_installment_plan_payload(line["id"], device["id"],
                                        term_months=12, down_payment_cents=8000), CA), 201)

    res = api.create_installment_plan(
        create_installment_plan_payload(line["id"], device["id"],
                                        term_months=12, down_payment_cents=8000), CA)
    validate_error(res, "ERR_DEVICE_UNAVAILABLE")
