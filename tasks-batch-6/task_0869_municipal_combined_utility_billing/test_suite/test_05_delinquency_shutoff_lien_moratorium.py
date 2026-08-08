"""Delinquency aging, shutoff scheduling/execution, moratorium coverage and overlap,
lien transfer, and payment-driven recovery."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS,
    set_clock, add_reading, add_meter, open_account,
    setup_account_with_water_bill, setup_paid_bill,
    setup_delinquent_account, setup_delinquent_with_scheduled_shutoff, setup_pending_lien,
    make_payment,
    moratorium_window_payload, lien_transfer_payload, shutoff_order_payload, reading_payload,
)

BS = TEST_USERS["billing_specialist_headers"]
CO = TEST_USERS["collections_officer_headers"]
MT = TEST_USERS["meter_tech_headers"]


# ---------------------------------------------------------------------------
# boundary_precision_check / mark_delinquent_grace_boundary_21_days
# ---------------------------------------------------------------------------
def test_mark_delinquent_before_21_day_grace_rejected(api):
    """PRD §3.6: "A collections officer marks a bill delinquent only when it is not yet
    `PAID`, is currently `CURRENT`, and at least 21 days have elapsed since its `due_date`
    as measured against the logical clock. Marking too early — before the 21-day grace has
    fully elapsed — is refused with `ERR_NOT_YET_DELINQUENT`".

    Design: Difficulty/boundary_precision_check/mark_delinquent_grace_boundary_21_days
    """
    ctx = setup_account_with_water_bill(api, reading_value=9500)  # due 2026-05-21
    set_clock(api, "2026-06-10T00:00:00Z")  # 20 days past due
    validate_error(api.mark_delinquent(ctx["bill"]["id"], CO), "ERR_NOT_YET_DELINQUENT")


def test_mark_delinquent_at_21_day_boundary_succeeds(api):
    """PRD §3.6: "at least 21 days have elapsed since its `due_date`".
    PRD §3.6: "A successful mark moves the bill `CURRENT → DELINQUENT`, bubbles the account
    `ACTIVE → DELINQUENT`".

    Design: Difficulty/boundary_precision_check/mark_delinquent_grace_boundary_21_days
    """
    ctx = setup_account_with_water_bill(api, reading_value=9500)  # due 2026-05-21
    set_clock(api, "2026-06-11T00:00:00Z")  # exactly 21 days past due
    bill = validate_success(api.mark_delinquent(ctx["bill"]["id"], CO))
    assert bill["collection_status"] == "DELINQUENT"


# ---------------------------------------------------------------------------
# state_machines / mark_delinquent_paid_bill_returns_bill_already_paid (corner)
# ---------------------------------------------------------------------------
def test_mark_delinquent_on_paid_bill_rejected(api):
    """PRD §3.6: "attempting to mark an already-`PAID` bill is refused with
    `ERR_BILL_ALREADY_PAID`."

    Design: Corner/state_machines/mark_delinquent_paid_bill_returns_bill_already_paid
    """
    ctx = setup_paid_bill(api, reading_value=9500, amount_cents=4640, method="CARD")
    set_clock(api, "2026-06-11T00:00:00Z")
    validate_error(api.mark_delinquent(ctx["bill"]["id"], CO), "ERR_BILL_ALREADY_PAID")


# ---------------------------------------------------------------------------
# validations / reading_regression_returns_422 (corner)
# ---------------------------------------------------------------------------
def test_actual_reading_below_latest_rejected(api):
    """PRD §3.2: "a new `ACTUAL` reading's `reading_value` must be at least as large as the
    meter's latest existing `reading_value` — dials do not run backward — and a regression
    is rejected with `ERR_READING_REGRESSION`."

    Design: Corner/validations/reading_regression_returns_422
    """
    account = open_account(api, account_holder_name="Reg Rex")
    meter = add_meter(api, account["id"], "WATER")
    add_reading(api, meter["id"], 9500, "ACTUAL", "2026-04-15T00:00:00Z")
    resp = api.create_reading(meter["id"], reading_payload(8000, "ACTUAL", "2026-05-15T00:00:00Z"), MT)
    validate_error(resp, "ERR_READING_REGRESSION")


# ---------------------------------------------------------------------------
# validations / shutoff_schedule_without_delinquency_returns_409 (corner)
# ---------------------------------------------------------------------------
def test_schedule_shutoff_on_non_delinquent_account_rejected(api):
    """PRD §3.6: "Scheduling requires the account to be `DELINQUENT` with a positive
    delinquent balance; otherwise the request is refused with `ERR_NO_DELINQUENT_BALANCE`."

    Design: Corner/validations/shutoff_schedule_without_delinquency_returns_409
    """
    account = open_account(api, account_holder_name="Fresh Fred")
    resp = api.create_shutoff_order(account["id"], shutoff_order_payload("2026-06-15T00:00:00Z"), CO)
    validate_error(resp, "ERR_NO_DELINQUENT_BALANCE")


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / shutoff_execute_depends_on_moratorium_window
# ---------------------------------------------------------------------------
def test_shutoff_execute_blocked_by_covering_moratorium(api):
    """PRD §3.6: "if an `ACTIVE` moratorium window — either a `SYSTEM`-scoped window or an
    `ACCOUNT`-scoped window for this account — covers the order's `scheduled_date`, the
    execution is refused with `ERR_MORATORIUM_ACTIVE`. A moratorium covers a date when its
    closed range from `start_date` through `end_date`, inclusive of both ends, contains the
    scheduled date."

    Design: Difficulty/cross_entity_state_dependency/shutoff_execute_depends_on_moratorium_window
    """
    ctx = setup_delinquent_with_scheduled_shutoff(api, reading_value=9500,
                                                  scheduled_date="2026-06-15T00:00:00Z")
    validate_success(api.create_moratorium_window(
        moratorium_window_payload("SYSTEM", "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z", "WEATHER"), CO), 201)
    validate_error(api.execute_shutoff(ctx["shutoff"]["id"], MT), "ERR_MORATORIUM_ACTIVE")


def test_shutoff_execute_outside_moratorium_succeeds(api):
    """PRD §3.6: "A permitted execution moves the order `SCHEDULED → EXECUTED`, transitions
    the account `DELINQUENT → SHUTOFF`, and removes the account's water and electric meters
    (`ACTIVE → REMOVED`)."

    Design: Difficulty/cross_entity_state_dependency/shutoff_execute_depends_on_moratorium_window
    """
    ctx = setup_delinquent_with_scheduled_shutoff(api, reading_value=9500,
                                                  scheduled_date="2026-07-15T00:00:00Z")
    validate_success(api.create_moratorium_window(
        moratorium_window_payload("SYSTEM", "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z", "WEATHER"), CO), 201)
    order = validate_success(api.execute_shutoff(ctx["shutoff"]["id"], MT))
    assert order["status"] == "EXECUTED"
    account = validate_success(api.get_account(ctx["account"]["id"], BS))
    assert account["status"] == "SHUTOFF"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / lien_certify_depends_on_account_status
# ---------------------------------------------------------------------------
def test_lien_certify_transitions_account_and_bills(api):
    """PRD §3.9: "posting to tax then advances `CERTIFIED → TRANSFERRED`, moves the account
    to `LIEN_TRANSFERRED`, and moves the account's delinquent bills `collection_status`
    `DELINQUENT → IN_LIEN`."

    Design: Difficulty/cross_entity_state_dependency/lien_certify_depends_on_account_status
    """
    ctx = setup_pending_lien(api, reading_value=18000, tax_parcel_ref="PARCEL-17")
    lien = validate_success(api.certify_lien(ctx["lien"]["id"], CO))
    assert lien["status"] == "TRANSFERRED"
    account = validate_success(api.get_account(ctx["account"]["id"], BS))
    assert account["status"] == "LIEN_TRANSFERRED"
    bill = validate_success(api.get_bill(ctx["bill"]["id"], BS))
    assert bill["collection_status"] == "IN_LIEN"


def test_lien_certify_snapshots_delinquent_balance(api):
    """PRD §3.9: "On certification the transfer's `amount_cents` snapshots the account's
    current delinquent balance and the transfer advances `PENDING → CERTIFIED`".

    Design: Difficulty/cross_entity_state_dependency/lien_certify_depends_on_account_status
    """
    ctx = setup_pending_lien(api, reading_value=18000, tax_parcel_ref="PARCEL-17")
    lien = validate_success(api.certify_lien(ctx["lien"]["id"], CO))
    assert lien["amount_cents"] == 10690


# ---------------------------------------------------------------------------
# validations / lien_initiate_below_min_arrears_returns_409 (corner)
# ---------------------------------------------------------------------------
def test_lien_initiate_below_minimum_arrears_rejected(api):
    """PRD §3.9: "initiation requires the account's `delinquent_balance_cents` to be at
    least 10,000 cents, otherwise `ERR_INSUFFICIENT_ARREARS`."

    Design: Corner/validations/lien_initiate_below_min_arrears_returns_409
    """
    ctx = setup_delinquent_account(api, reading_value=9500)  # delinquent balance 4640
    resp = api.create_lien_transfer(ctx["account"]["id"], lien_transfer_payload("PARCEL-114"), CO)
    validate_error(resp, "ERR_INSUFFICIENT_ARREARS")


# ---------------------------------------------------------------------------
# resource_temporal_overlap / moratorium_window_overlap_closed_with_adjacency
# ---------------------------------------------------------------------------
def test_touching_system_moratorium_rejected(api):
    """PRD §3.6: "a new `SYSTEM` window may not overlap or even touch an existing `ACTIVE`
    `SYSTEM` window: treated as closed date ranges, two system windows conflict whenever they
    share any day — including the case where one ends on the very day the other begins — and
    such a conflict is refused with `ERR_MORATORIUM_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/moratorium_window_overlap_closed_with_adjacency
    """
    validate_success(api.create_moratorium_window(
        moratorium_window_payload("SYSTEM", "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z", "WEATHER"), CO), 201)
    resp = api.create_moratorium_window(
        moratorium_window_payload("SYSTEM", "2026-06-30T00:00:00Z", "2026-07-15T00:00:00Z", "WEATHER"), CO)
    validate_error(resp, "ERR_MORATORIUM_OVERLAP")


def test_gap_system_moratorium_accepted(api):
    """PRD §3.6: "a new `SYSTEM` window may not overlap or even touch an existing `ACTIVE`
    `SYSTEM` window: treated as closed date ranges, two system windows conflict whenever they
    share any day".

    Design: Difficulty/resource_temporal_overlap/moratorium_window_overlap_closed_with_adjacency
    """
    validate_success(api.create_moratorium_window(
        moratorium_window_payload("SYSTEM", "2026-06-01T00:00:00Z", "2026-06-30T00:00:00Z", "WEATHER"), CO), 201)
    resp = api.create_moratorium_window(
        moratorium_window_payload("SYSTEM", "2026-07-01T00:00:00Z", "2026-07-31T00:00:00Z", "WEATHER"), CO)
    validate_success(resp, 201)


# ---------------------------------------------------------------------------
# consistency_model / payment_clears_delinquency_cancels_shutoff_immediately (corner)
# ---------------------------------------------------------------------------
def test_payment_clearing_delinquency_cancels_shutoff_and_reactivates(api):
    """PRD §3.5: "When a payment reduces the account's `delinquent_balance_cents` to 0, any
    `SCHEDULED` shutoff order for the account is cancelled and the account recovers —
    `DELINQUENT → ACTIVE`, or `SHUTOFF → ACTIVE` with its previously removed water and
    electric meters restored from `REMOVED` back to `ACTIVE`."

    Design: Corner/consistency_model/payment_clears_delinquency_cancels_shutoff_immediately
    """
    ctx = setup_delinquent_with_scheduled_shutoff(api, reading_value=9500,
                                                  scheduled_date="2026-06-20T00:00:00Z")
    make_payment(api, ctx["account"]["id"], 4640, "ACH")
    account = validate_success(api.get_account(ctx["account"]["id"], BS))
    assert account["status"] == "ACTIVE"
    assert account["delinquent_balance_cents"] == 0
    shutoff, _ = validate_paginated(api.list_shutoff_orders(ctx["account"]["id"], CO))
    order = [o for o in shutoff if o["id"] == ctx["shutoff"]["id"]][0]
    assert order["status"] == "CANCELLED"
    bill = validate_success(api.get_bill(ctx["bill"]["id"], BS))
    assert bill["collection_status"] == "CURRENT"
