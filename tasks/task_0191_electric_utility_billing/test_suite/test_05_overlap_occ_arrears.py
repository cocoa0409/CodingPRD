"""Temporal-overlap, optimistic-concurrency, and arrears-variant compliance:
half-open bill-period overlap (adjacency allowed), fixed-hour meter-read slot
overlap, the stale-account-version OCC guard on bill issuance, and the two
arrears-recompute variants (cumulative-on-clock vs instantaneous-on-payment).
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
)
from test_helpers.fixtures import (
    OPERATOR,
    create_active_tariff,
    open_account,
    add_meter,
    import_reads,
    create_draft_bill,
    issue_bill_with_occ_data,
    set_clock,
    setup_issued_bill,
    pay_account_data,
    reads_for_2636,
    _iso,
)



# ===========================================================================
# Queue A — resource_temporal_overlap (bill period, half-open)
# ===========================================================================
def test_overlapping_bill_period_rejected(api):
    """PRD §3.3: "the half-open window `[period_start, period_end)` must not
    overlap any existing non-void bill for the same account; a zero-or-negative
    period or an overlapping period is rejected with `ERR_BILL_PERIOD_OVERLAP`."

    A second bill [2026-01-15, 2026-02-15) overlapping an existing
    [2026-01-01, 2026-02-01) bill is rejected.

    Design: Difficulty/resource_temporal_overlap/bill_period_overlap_half_open_no_buffer
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    create_draft_bill(
        account["id"], "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z",
        "2026-02-20T00:00:00Z")
    res = api.create_bill({
        "account_id": account["id"],
        "period_start": "2026-01-15T00:00:00Z",
        "period_end": "2026-02-15T00:00:00Z",
        "due_date": "2026-03-05T00:00:00Z",
    }, OPERATOR)
    validate_error(res, "ERR_BILL_PERIOD_OVERLAP", expected_status=409)


def test_adjacent_bill_period_accepted(api):
    """PRD §3.3: "the half-open window `[period_start, period_end)` must not
    overlap any existing non-void bill for the same account; a zero-or-negative
    period or an overlapping period is rejected with `ERR_BILL_PERIOD_OVERLAP`."

    An adjacent bill [2026-02-01, 2026-03-01) abutting an existing
    [2026-01-01, 2026-02-01) bill is accepted — under half-open semantics the
    shared 2026-02-01 instant belongs only to the second window.

    Design: Difficulty/resource_temporal_overlap/bill_period_overlap_half_open_no_buffer
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    create_draft_bill(
        account["id"], "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z",
        "2026-02-20T00:00:00Z")
    res = api.create_bill({
        "account_id": account["id"],
        "period_start": "2026-02-01T00:00:00Z",
        "period_end": "2026-03-01T00:00:00Z",
        "due_date": "2026-03-20T00:00:00Z",
    }, OPERATOR)
    bill = validate_success(res, 201)
    assert bill["status"] == "DRAFT", bill["status"]


# ===========================================================================
# Queue A — resource_temporal_overlap (meter read, fixed hour slot)
# ===========================================================================
def test_duplicate_meter_read_slot_rejected(api):
    """PRD §3.2: "A new read's interval must not duplicate or overlap an existing
    read for the same meter; an overlapping read is rejected with
    `ERR_READ_OVERLAP`."

    A duplicate [16:00, 17:00) slot on a meter that already has that read is
    rejected.

    Design: Difficulty/resource_temporal_overlap/meter_read_interval_overlap_fixed_hour_slots
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    meter = add_meter(account["id"])
    import_reads(meter["id"], [
        (_iso("2026-01-05", 16), _iso("2026-01-05", 17), 2.0, 0.0),
    ])
    res = api.create_meter_read({
        "meter_id": meter["id"],
        "interval_start": "2026-01-05T16:00:00Z",
        "interval_end": "2026-01-05T17:00:00Z",
        "import_kwh": 3.0,
        "export_kwh": 0.0,
    }, OPERATOR)
    validate_error(res, "ERR_READ_OVERLAP", expected_status=409)


def test_adjacent_meter_read_slot_accepted(api):
    """PRD §3.2: "A new read's interval must not duplicate or overlap an existing
    read for the same meter; an overlapping read is rejected with
    `ERR_READ_OVERLAP`."

    An adjacent [17:00, 18:00) slot abutting an existing [16:00, 17:00) read is
    accepted — fixed one-hour slots that merely touch do not overlap.

    Design: Difficulty/resource_temporal_overlap/meter_read_interval_overlap_fixed_hour_slots
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    meter = add_meter(account["id"])
    import_reads(meter["id"], [
        (_iso("2026-01-05", 16), _iso("2026-01-05", 17), 2.0, 0.0),
    ])
    res = api.create_meter_read({
        "meter_id": meter["id"],
        "interval_start": "2026-01-05T17:00:00Z",
        "interval_end": "2026-01-05T18:00:00Z",
        "import_kwh": 1.0,
        "export_kwh": 0.0,
    }, OPERATOR)
    validate_success(res, 201)


# ===========================================================================
# Queue A — dual_variant_calc (arrears: cumulative-on-clock vs instantaneous)
# ===========================================================================
def test_arrears_cumulative_on_clock_then_instantaneous_on_payment(api):
    """PRD §2.8: "This arrears evaluation runs in two situations — immediately
    after a payment waterfall, where it reads the post-allocation set of unpaid
    bills so that a clearing payment can return the account to `CURRENT` in a
    single step; and whenever the system clock is advanced, where the same unpaid
    set is re-aged against the later `current_utc`, so an account can cross into
    `IN_ARREARS` purely from the passage of time."

    Same unpaid bill drives both variants: advancing the clock to day 45 flips
    the account to IN_ARREARS (cumulative-on-clock), then a clearing payment
    drops it straight back to CURRENT in one step (instantaneous-on-payment).

    Design: Difficulty/dual_variant_calc/arrears_age_instantaneous_vs_cumulative_on_account
    """
    scene = setup_issued_bill(
        read_tuples=reads_for_2636(), due_date="2026-01-01T00:00:00Z",
        clock="2026-01-01T00:00:00Z")
    account_id = scene["account"]["id"]
    set_clock("2026-02-15T00:00:00Z")  # 45 days -> IN_ARREARS
    acct1 = get_success_data(api.get_account(account_id, OPERATOR))
    assert acct1["financial_status"] == "IN_ARREARS", acct1["financial_status"]
    pay_account_data(account_id, 2636)  # full clear
    acct2 = get_success_data(api.get_account(account_id, OPERATOR))
    assert acct2["financial_status"] == "CURRENT", acct2["financial_status"]
    bill = get_success_data(api.get_bill(scene["bill"]["id"], OPERATOR))
    assert bill["status"] == "PAID", bill["status"]


def test_arrears_cumulative_clock_delinquent_then_partial_pay_stays_past_due(api):
    """PRD §2.8: "whenever the system clock is advanced, where the same unpaid set
    is re-aged against the later `current_utc`, so an account can cross into
    `IN_ARREARS` purely from the passage of time."
    PRD §2.8: "immediately after a payment waterfall, where it reads the
    post-allocation set of unpaid bills so that a clearing payment can return the
    account to `CURRENT` in a single step"
    PRD §3.5: "a bill whose `amount_paid_cents` is greater than zero but below
    its `total_due_cents` becomes `PARTIALLY_PAID`."

    Cumulative-on-clock advances the same unpaid bill to DELINQUENT at 10 days
    past due; the instantaneous-on-payment recompute after a partial 1000 payment
    (bill still PARTIALLY_PAID, still past due) leaves the account DELINQUENT
    rather than CURRENT.

    Design: Difficulty/dual_variant_calc/arrears_age_instantaneous_vs_cumulative_on_account
    """
    scene = setup_issued_bill(
        read_tuples=reads_for_2636(), due_date="2026-01-01T00:00:00Z",
        clock="2026-01-01T00:00:00Z")
    account_id = scene["account"]["id"]
    set_clock("2026-01-11T00:00:00Z")  # 10 days past due -> DELINQUENT
    acct1 = get_success_data(api.get_account(account_id, OPERATOR))
    assert acct1["financial_status"] == "DELINQUENT", acct1["financial_status"]
    pay_account_data(account_id, 1000)  # partial — bill stays past due
    bill = get_success_data(api.get_bill(scene["bill"]["id"], OPERATOR))
    assert bill["status"] == "PARTIALLY_PAID", bill["status"]
    acct2 = get_success_data(api.get_account(account_id, OPERATOR))
    assert acct2["financial_status"] == "DELINQUENT", acct2["financial_status"]


# ===========================================================================
# Queue B — cross_cutting_complexity_layers (OCC stale version)
# ===========================================================================
def test_occ_fresh_version_succeeds_then_stale_rejected(api):
    """PRD §2.10: "Bill issuance requires the request body to carry
    `expected_account_version` holding the client's last observed `version` of
    the target bill's account. If that value does not match the account's current
    `version` — because some other writer has advanced the account since the
    client read it — issuance is rejected with `ERR_STALE_ACCOUNT_VERSION` at
    HTTP 412."

    Issuing bill1 with the matching version succeeds and bumps account.version;
    issuing bill2 with the now-stale prior version is rejected at 412 and bill2
    stays DRAFT.

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds_then_stale_rejected
    """
    tariff = create_active_tariff()
    account = open_account(tariff["id"])
    meter = add_meter(account["id"])
    import_reads(meter["id"], reads_for_2636("2026-01-05"))
    import_reads(meter["id"], reads_for_2636("2026-02-05"))
    bill1 = create_draft_bill(
        account["id"], "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z",
        "2026-02-20T00:00:00Z")
    bill2 = create_draft_bill(
        account["id"], "2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z",
        "2026-03-20T00:00:00Z")
    acct_pre = get_success_data(api.get_account(account["id"], OPERATOR))
    stale_version = acct_pre["version"]
    validate_success(
        api.issue_bill(bill1["id"], {"expected_account_version": stale_version}, OPERATOR),
        200)
    res = api.issue_bill(
        bill2["id"], {"expected_account_version": stale_version}, OPERATOR)
    validate_error(res, "ERR_STALE_ACCOUNT_VERSION", expected_status=412)
    still = get_success_data(api.get_bill(bill2["id"], OPERATOR))
    assert still["status"] == "DRAFT", still["status"]
