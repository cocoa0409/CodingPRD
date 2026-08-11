"""Collecting money across two non-fungible streams, and the balances that re-open."""

from test_helpers import (
    ApiErrorId,
    assert_government_allocation_ceiling,
    assert_ledger_entry,
    assert_money_conservation,
    build_scenario,
    get_success_data,
    list_ledger_entries,
    new_applicant,
    new_catalog_item,
    new_order,
    order_version,
    quote,
    read_order,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import CASE_MANAGER, COMPLIANCE, SUBMITTER


def test_payment_waterfall_fills_the_government_bucket_before_the_service_bucket(api):
    """PRD §3.6: "Without an override, the amount is split by a two-step waterfall: the
    government remainder is the order's `government_fee_quoted_cents` minus its
    `collected_government_cents`, floored at 0; the government part of this payment is the
    smaller of `amount_cents` and that remainder; and the service part is whatever is left
    of `amount_cents`."
    PRD §3.6: "A `COLLECTION` ledger row with `reason` `CUSTOMER_PAYMENT` is appended for
    each part that is strictly positive — so an unsplit payment writes one row and a
    straddling payment writes two."
    PRD §3.6: "`PARTIALLY_COLLECTED` while `collected_cents` is strictly between 0 and
    `total_quoted_cents`"

    Design: Corner/calculations/corner_payment_allocation_fills_government_bucket_before_service
    """
    set_clock()
    catalog = new_catalog_item()
    order = new_order(catalog["id"])
    for i, name in enumerate(("Pay One", "Pay Two", "Pay Three")):
        new_applicant(order["id"], full_name=name, date_of_birth=f"199{i}-03-04")
    quoted = quote(order["id"])
    assert quoted["total_quoted_cents"] == 68250

    get_success_data(api.create_payment(order["id"], {"amount_cents": 50000}, CASE_MANAGER))

    stored = read_order(order["id"])
    assert stored["collected_government_cents"] == 48000, (
        f"the government bucket fills first, got {stored['collected_government_cents']}"
    )
    assert stored["collected_service_cents"] == 2000, (
        f"only the remainder reaches the SERVICE stream, got {stored['collected_service_cents']}"
    )
    assert stored["collected_cents"] == 50000
    assert stored["outstanding_cents"] == 50000, (
        "outstanding_cents rises by the full amount regardless of how the split fell"
    )
    assert stored["payment_status"] == "PARTIALLY_COLLECTED"
    assert_money_conservation(stored)
    assert_government_allocation_ceiling(stored)

    rows = list_ledger_entries(order["id"])
    collections = [r for r in rows if r["kind"] == "COLLECTION"]
    assert len(collections) == 2, f"a straddling payment writes two rows, got {len(collections)}"
    for row in collections:
        assert_ledger_entry(row)
        assert row["reason"] == "CUSTOMER_PAYMENT"
    assert {r["stream"] for r in collections} == {"GOVERNMENT", "SERVICE"}


def test_stream_override_may_not_push_the_government_bucket_past_its_quote(api):
    """PRD §3.6: "The override is the only way to break the per-stream ceiling of §2.11,
    and the system refuses to let it: if applying the override would leave
    `collected_government_cents` above `government_fee_quoted_cents`, the payment is
    rejected with `ERR_STREAM_ALLOCATION_INVALID` and no row is written."
    PRD §2.11: "The ordinary payment waterfall fills the government bucket only up to its
    remaining need and can therefore never overshoot; the optional `stream_override` field
    is the single mechanism capable of pushing `collected_government_cents` past
    `government_fee_quoted_cents`, and that attempt is refused at rung 31 with
    `ERR_STREAM_ALLOCATION_INVALID`."

    Design: Corner/validations/corner_stream_override_above_government_quote_rejected
    """
    set_clock()
    catalog = new_catalog_item()
    order = new_order(catalog["id"])
    new_applicant(order["id"], full_name="Stream Guard")
    quoted = quote(order["id"])
    assert quoted["government_fee_quoted_cents"] == 16000

    resp = api.create_payment(
        order["id"], {"amount_cents": 20000, "stream_override": "GOVERNMENT"}, CASE_MANAGER
    )
    validate_error(resp, ApiErrorId.ERR_STREAM_ALLOCATION_INVALID.value)

    stored = read_order(order["id"])
    assert stored["collected_government_cents"] == 0
    assert stored["collected_cents"] == 0
    assert stored["payment_status"] == "UNPAID"
    assert list_ledger_entries(order["id"]) == [], "the refused payment writes no LedgerEntry"


def test_order_summary_reports_conservation_and_custody_cardinality(api):
    """PRD §2.11: "The computed read reports `conservation_ok` as true exactly when the
    identity holds with zero tolerance in whole cents."
    PRD §2.11: "For every order, exactly **one** `CustodyEvent` row has `released_at` null;
    that single open row's `holder_type` equals the order's `custody_holder`; and no two
    custody events of the same order have overlapping intervals, where an interval runs
    from `acquired_at` inclusive to `released_at` exclusive. The computed summary reports
    `open_custody_count` (which must be 1) and `open_custody_holder`."

    Design: Corner/endpoints/corner_order_summary_reports_money_conservation_and_custody_cardinality
    """
    set_clock()
    catalog = new_catalog_item()
    order = new_order(catalog["id"])
    new_applicant(order["id"], full_name="Summary One")
    quote(order["id"])
    get_success_data(api.create_payment(order["id"], {"amount_cents": 26500}, CASE_MANAGER))

    summary = validate_success(api.get_order_summary(order["id"], COMPLIANCE))

    assert summary["collected_cents"] == 26500
    assert summary["outstanding_cents"] == 26500, (
        "nothing has been tendered, earned or refunded, so the whole balance is outstanding"
    )
    assert summary["conservation_ok"] is True
    assert summary["open_custody_count"] == 1
    assert summary["open_custody_holder"] == "APPLICANT"


def test_in_flight_upgrade_reopens_the_balance_and_blocks_submission_until_topped_up(api):
    """PRD §3.5: "The delta is the new subtotal minus the old subtotal, **plus a 2500-cent
    tier-upgrade administration fee**."
    PRD §3.9: "and finally funding at rung 37 — `outstanding_cents` must be at least
    `total_quoted_cents`, or the request is `ERR_BALANCE_OUTSTANDING` with HTTP 402."
    PRD §3.9: "A successful submission stamps `submitted_at` with the logical clock and
    `submitted_by_user_id` with the acting `X-User-ID`, computes and writes
    `effective_submission_date`, raises `furthest_stage_reached` to `SUBMITTED`, appends a
    `SERVICE`-stream `EARN` ledger row for exactly `service_fee_quoted_cents` with `reason`
    `SERVICE_RECOGNITION` — reducing `outstanding_cents` by that same amount and raising
    `service_earned_cents` by it"

    Design: Corner/errors/corner_error_balance_outstanding_after_in_flight_upgrade
    """
    scenario = build_scenario("ready")
    order_id = scenario["order_id"]

    upgraded = validate_success(
        api.change_service_level(
            order_id,
            {"service_level": "EXPEDITED", "expected_order_version": order_version(order_id)},
            CASE_MANAGER,
        )
    )
    # 7500 * 1.35 = 10125 new subtotal; old subtotal 10500 - 3000 handling = 7500;
    # delta 10125 - 7500 + 2500 = 5125, so 10500 + 5125 = 15625.
    assert upgraded["service_fee_quoted_cents"] == 15625
    assert upgraded["total_quoted_cents"] == 31625
    assert upgraded["payment_status"] == "PARTIALLY_COLLECTED", (
        "the money axis regresses without the workflow moving"
    )
    assert upgraded["workflow_status"] == "READY_FOR_SUBMISSION"

    refused = api.submit_order(order_id, SUBMITTER)
    validate_error(refused, ApiErrorId.ERR_BALANCE_OUTSTANDING.value)

    get_success_data(api.create_payment(order_id, {"amount_cents": 5125}, CASE_MANAGER))
    topped_up = read_order(order_id)
    assert topped_up["collected_cents"] == 31625
    assert topped_up["payment_status"] == "COLLECTED"

    submitted = validate_success(api.submit_order(order_id, SUBMITTER))
    assert submitted["workflow_status"] == "SUBMITTED"
    assert submitted["service_earned_cents"] == 15625, (
        "submission recognises exactly service_fee_quoted_cents as revenue"
    )
    assert submitted["outstanding_cents"] == 16000
    assert_money_conservation(submitted)
