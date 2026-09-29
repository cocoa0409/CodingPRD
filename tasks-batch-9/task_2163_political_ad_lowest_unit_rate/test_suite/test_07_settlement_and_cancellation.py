"""Settlement movements, the stale-view guard, and the cancellation compensating pair."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    air_spot,
    assert_rebate_entry,
    hourly_spots,
    list_rebates,
    make_advertiser_agent_headers,
    payment_payload,
    read_order,
    read_spot,
    reject_order,
    set_clock,
    setup_candidate_order,
    setup_issue_order,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
OFFICER_BETA = TEST_USERS["officer_beta_headers"]


def test_charge_with_the_wrong_amount_is_refused_and_the_exact_amount_settles(api):
    """PRD §3.6: "The amount must settle the invoice exactly: it must equal
    `net_due_cents` minus `paid_cents` plus `refunded_cents`."
    PRD §3.6: "Either amount being off by even a single cent is refused with
    `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 422). A cleared `CHARGE` adds `amount_cents` to
    `paid_cents` and advances the settlement dimension `INVOICED → PAID`; a cleared
    `REFUND` adds `amount_cents` to `refunded_cents` and advances it `REFUND_DUE →
    REFUNDED`, closing the money invariant under which what the advertiser has paid net
    of refunds equals what the order is due."

    Design: Corner/validations/payment_with_the_wrong_amount_rejected_and_the_exact_outstanding_charge_succeeds
    """
    built = setup_issue_order(
        call_sign="WAMT-TV",
        market_code="DMA-131",
        station_overrides={
            "licensee_name": "Amount Match Media",
            "political_file_posting_deadline_hours": 24,
            "daily_political_seconds_cap": 300,
        },
        spots=hourly_spots(1),
        accept=True,
    )
    order, advertiser = built["order"], built["advertiser"]
    headers = make_advertiser_agent_headers(advertiser["id"])
    observed_version = order["version"]

    validate_error(
        api.record_payment(
            order["id"], payment_payload("CHARGE", 99999, observed_version), headers
        ),
        ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH,
    )
    assert read_order(order["id"], advertiser["id"])["paid_cents"] == 0

    settled = validate_success(
        api.record_payment(
            order["id"], payment_payload("CHARGE", 100000, observed_version), headers
        )
    )
    assert settled["payment_status"] == "PAID"
    assert settled["paid_cents"] == 100000
    assert settled["refunded_cents"] == 0


def test_refund_recorded_before_any_rebate_is_refused(api):
    """PRD §3.6: "A `REFUND` requires the settlement state to be `REFUND_DUE`, or it
    fails with `ERR_REFUND_NOT_DUE` (HTTP 409), and its amount must equal `paid_cents`
    minus `refunded_cents` minus `net_due_cents`."

    Design: Corner/validations/refund_before_any_rebate_rejected_as_refund_not_due
    """
    built = setup_issue_order(
        call_sign="WRFD-TV",
        market_code="DMA-132",
        station_overrides={
            "licensee_name": "Refund Gate Media",
            "political_file_posting_deadline_hours": 24,
            "daily_political_seconds_cap": 300,
        },
        spots=hourly_spots(1),
        charge_amount_cents=100000,
    )
    order, advertiser = built["order"], built["advertiser"]
    headers = make_advertiser_agent_headers(advertiser["id"])
    assert order["payment_status"] == "PAID"

    validate_error(
        api.record_payment(
            order["id"], payment_payload("REFUND", 100000, order["version"]), headers
        ),
        ApiErrorId.ERR_REFUND_NOT_DUE,
    )

    refreshed = read_order(order["id"], advertiser["id"])
    assert refreshed["payment_status"] == "PAID"
    assert refreshed["refunded_cents"] == 0
    _rows, meta = validate_paginated(api.list_rebates(ADMIN, params={"order_id": order["id"]}))
    assert meta["total_count"] == 0


def test_settlement_carrying_a_stale_order_version_is_refused(api):
    """PRD §2.6: "Such a request must carry `expected_order_version`, a non-optional
    field holding the `version` of the target `CommercialOrder` as the client last read
    it. If that value does not equal the order's current `version`, the request is
    rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/stale_expected_order_version_rejects_the_settlement_payment
    """
    built = setup_issue_order(
        call_sign="WOCO-TV",
        market_code="DMA-144",
        station_overrides={
            "licensee_name": "Order Version Media",
            "political_file_posting_deadline_hours": 24,
            "daily_political_seconds_cap": 300,
        },
        spots=hourly_spots(1),
        accept=True,
    )
    order, advertiser = built["order"], built["advertiser"]
    headers = make_advertiser_agent_headers(advertiser["id"])
    current_version = order["version"]

    validate_error(
        api.record_payment(
            order["id"], payment_payload("CHARGE", 100000, current_version - 1), headers
        ),
        ApiErrorId.ERR_STALE_ORDER_VERSION,
    )

    refreshed = read_order(order["id"], advertiser["id"])
    assert refreshed["paid_cents"] == 0
    assert refreshed["payment_status"] == "INVOICED"
    assert refreshed["version"] == current_version


def _rejected_order():
    built = setup_issue_order(
        call_sign="WPRI-TV",
        market_code="DMA-119",
        station_overrides={
            "licensee_name": "Priority Media LLC",
            "political_file_posting_deadline_hours": 24,
            "daily_political_seconds_cap": 300,
        },
        classification=None,
        spots=hourly_spots(1),
        submit=True,
    )
    built["order"] = reject_order(
        built["order"]["id"], "Inventory unavailable in requested window"
    )
    return built


def test_payment_against_a_rejected_order_reports_the_lifecycle_error(api):
    """PRD §3.6: "A `CHARGE` requires the order's lifecycle state to be one of
    `ACCEPTED`, `SUSPENDED`, `RUNNING` or `COMPLETED` — anything earlier or terminal
    fails with `ERR_ORDER_NOT_ACCEPTED` (HTTP 409) — and requires the settlement state
    to be `INVOICED`."
    PRD §2.9: "6. **Lifecycle state.** The state-position checks —
    `ERR_ADVERTISER_NOT_IN_REVIEW`, `ERR_ORDER_NOT_DRAFT`, `ERR_ORDER_NOT_SUBMITTED`,
    `ERR_ORDER_NOT_ACCEPTED`, `ERR_ORDER_TERMINAL`, `ERR_SPOT_NOT_SCHEDULED`,
    `ERR_FILE_ENTRY_ALREADY_POSTED`, `ERR_EO_REQUEST_NOT_OPEN`,
    `ERR_COMPLAINT_NOT_OPEN`, `ERR_REFUND_NOT_DUE` — in that order."
    PRD §2.9: "11. **Fiscal rules.** `ERR_PAYMENT_TERMS_NOT_PERMITTED`, then
    `ERR_PAYMENT_AMOUNT_MISMATCH`, then `ERR_ORDER_NOT_PAID`."

    Design: Difficulty/priority_pair_validation_conflict/state_error_outranks_fiscal_error_on_payment_against_rejected_order
    """
    built = _rejected_order()
    order, advertiser = built["order"], built["advertiser"]
    headers = make_advertiser_agent_headers(advertiser["id"])

    assert order["status"] == "REJECTED"
    assert order["net_due_cents"] == 0, "an amount of 999999 cannot possibly match"

    response = api.record_payment(
        order["id"], payment_payload("CHARGE", 999999, order["version"]), headers
    )
    validate_error(response, ApiErrorId.ERR_ORDER_NOT_ACCEPTED)
    assert response.json()["data"]["error_id"] != "ERR_PAYMENT_AMOUNT_MISMATCH", (
        "the lifecycle rung is evaluated before the fiscal rung"
    )


def test_payment_refused_on_the_lifecycle_rung_leaves_the_settlement_dimension_untouched(api):
    """PRD §3.6: "A `CHARGE` requires the order's lifecycle state to be one of
    `ACCEPTED`, `SUSPENDED`, `RUNNING` or `COMPLETED` — anything earlier or terminal
    fails with `ERR_ORDER_NOT_ACCEPTED` (HTTP 409) — and requires the settlement state
    to be `INVOICED`."
    PRD §3.5: "A `REJECT` decision is the branch sibling of `ACCEPT` and its effects are
    entirely disjoint from them: no determination is computed, no cap is applied, no
    political file entry is filed, and nothing is invoiced."

    Design: Difficulty/priority_pair_validation_conflict/state_error_outranks_fiscal_error_on_payment_against_rejected_order
    """
    built = _rejected_order()
    order, advertiser = built["order"], built["advertiser"]
    headers = make_advertiser_agent_headers(advertiser["id"])

    validate_error(
        api.record_payment(
            order["id"], payment_payload("CHARGE", 999999, order["version"]), headers
        ),
        ApiErrorId.ERR_ORDER_NOT_ACCEPTED,
    )

    refreshed = read_order(order["id"], advertiser["id"])
    assert refreshed["paid_cents"] == 0
    assert refreshed["payment_status"] == "UNBILLED"
    assert refreshed["status"] == "REJECTED"


def _paid_candidate_order():
    return setup_candidate_order(
        call_sign="WCSH-TV",
        market_code="DMA-455",
        station_overrides={
            "licensee_name": "Cash Balance Broadcasting",
            "political_file_posting_deadline_hours": 24,
            "daily_political_seconds_cap": 300,
        },
        spots=hourly_spots(1),
        charge_amount_cents=100000,
    )


def test_cancelling_a_paid_order_writes_the_whole_rebate_and_moves_to_refund_due(api):
    """PRD §3.6: "Cancelling records the supplied string in the order's
    `rejection_reason` field, sets every spot still `SCHEDULED` to `CANCELLED` with its
    `charged_rate_cents` zeroed, and recomputes `spot_count`, `gross_charge_cents`,
    `agency_commission_cents` and `net_due_cents`."
    PRD §3.6: "The money comparison then runs exactly as in the preemption cascade: take
    `paid_cents` minus `refunded_cents` minus the new `net_due_cents`, and if it exceeds
    `rebate_total_cents`, write one rebate ledger entry with `reason` `ORDER_CANCELLED`
    for the excess only, refresh `rebate_total_cents`, and move the settlement dimension
    to `REFUND_DUE` — from `PAID` if it was there, and staying in `REFUND_DUE` if it was
    already there."

    Design: Difficulty/compensating_invariant/cancel_then_refund_conserves_order_cash_balance_against_net_due
    """
    built = _paid_candidate_order()
    order, advertiser, spot = built["order"], built["advertiser"], built["spots"][0]
    assert order["paid_cents"] == 100000
    assert order["net_due_cents"] == 100000

    cancelled = validate_success(
        api.cancel_order(
            order["id"],
            {"cancellation_reason": "Campaign withdrew the flight"},
            make_advertiser_agent_headers(advertiser["id"]),
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["payment_status"] == "REFUND_DUE"
    assert cancelled["gross_charge_cents"] == 0
    assert cancelled["net_due_cents"] == 0
    assert cancelled["rebate_total_cents"] == 100000

    cancelled_spot = read_spot(spot["id"])
    assert cancelled_spot["status"] == "CANCELLED"
    assert cancelled_spot["charged_rate_cents"] == 0

    entries = list_rebates(order_id=order["id"])
    assert len(entries) == 1
    assert_rebate_entry(entries[0])
    assert entries[0]["amount_cents"] == 100000
    assert entries[0]["reason"] == "ORDER_CANCELLED"


def test_refund_after_cancellation_closes_the_cash_balance_against_net_due(api):
    """PRD §3.6: "A `REFUND` requires the settlement state to be `REFUND_DUE`, or it
    fails with `ERR_REFUND_NOT_DUE` (HTTP 409), and its amount must equal `paid_cents`
    minus `refunded_cents` minus `net_due_cents`."
    PRD §3.6: "a cleared `REFUND` adds `amount_cents` to `refunded_cents` and advances
    it `REFUND_DUE → REFUNDED`, closing the money invariant under which what the
    advertiser has paid net of refunds equals what the order is due."

    Design: Difficulty/compensating_invariant/cancel_then_refund_conserves_order_cash_balance_against_net_due
    """
    built = _paid_candidate_order()
    order, advertiser = built["order"], built["advertiser"]
    headers = make_advertiser_agent_headers(advertiser["id"])

    before = read_order(order["id"], advertiser["id"])
    assert before["paid_cents"] - before["refunded_cents"] == before["net_due_cents"], (
        "the cash balance already matches net_due before the compensating pair"
    )

    cancelled = validate_success(
        api.cancel_order(
            order["id"], {"cancellation_reason": "Campaign withdrew the flight"}, headers
        )
    )

    refunded = validate_success(
        api.record_payment(
            order["id"], payment_payload("REFUND", 100000, cancelled["version"]), headers
        )
    )
    assert refunded["payment_status"] == "REFUNDED"
    assert refunded["paid_cents"] == 100000
    assert refunded["refunded_cents"] == 100000
    assert refunded["net_due_cents"] == 0
    assert refunded["paid_cents"] - refunded["refunded_cents"] == refunded["net_due_cents"], (
        "the compensating pair leaves zero drift on the ledger"
    )


def test_cancelling_an_already_cancelled_order_is_refused(api):
    """PRD §3.6: "It applies to any order in `DRAFT`, `SUBMITTED`, `ACCEPTED`,
    `SUSPENDED` or `RUNNING`; an order already `REJECTED`, `COMPLETED` or `CANCELLED` is
    refused with `ERR_ORDER_TERMINAL` (HTTP 409)."

    Design: Corner/state_machines/cancel_on_an_already_cancelled_order_rejected_as_terminal
    """
    built = setup_issue_order(
        call_sign="WTRM-TV",
        market_code="DMA-107",
        station_overrides={"licensee_name": "Terminal Media Group"},
        classification=None,
        spots=hourly_spots(1),
    )
    order, advertiser, spot = built["order"], built["advertiser"], built["spots"][0]
    headers = make_advertiser_agent_headers(advertiser["id"])

    validate_success(
        api.cancel_order(
            order["id"], {"cancellation_reason": "Buyer withdrew before submission"}, headers
        )
    )

    validate_error(
        api.cancel_order(
            order["id"], {"cancellation_reason": "Duplicate cancellation attempt"}, headers
        ),
        ApiErrorId.ERR_ORDER_TERMINAL,
    )

    assert read_order(order["id"], advertiser["id"])["status"] == "CANCELLED"
    assert read_spot(spot["id"])["status"] == "CANCELLED"
    _rows, meta = validate_paginated(api.list_rebates(ADMIN, params={"order_id": order["id"]}))
    assert meta["total_count"] == 0, "nothing had been paid, so no rebate is owed"


def _running_candidate_order():
    built = setup_candidate_order(
        call_sign="WPAR-TV",
        market_code="DMA-233",
        station_overrides={
            "licensee_name": "Parallel Media Group",
            "political_file_posting_deadline_hours": 24,
            "daily_political_seconds_cap": 300,
        },
        spots=hourly_spots(2, air_date="2026-08-10"),
        accept=True,
    )
    set_clock("2026-08-10T12:00:00Z")
    air_spot(built["spots"][0]["id"])
    built["order"] = read_order(built["order"]["id"], built["advertiser"]["id"])
    return built


def test_airing_advances_the_lifecycle_while_the_settlement_dimension_stands_still(api):
    """PRD §3.6: "An accepted order carries two state dimensions that advance
    independently of one another."
    PRD §3.6: "If this is the order's first airing — recognisable because `first_air_at`
    is still null — the order advances `ACCEPTED → RUNNING` and stamps `first_air_at`
    with the logical clock."

    Design: Difficulty/non_linear_state_machine/order_lifecycle_and_settlement_dimensions_advance_independently
    """
    built = _running_candidate_order()
    order = built["order"]

    assert order["status"] == "RUNNING"
    assert order["payment_status"] == "INVOICED", (
        "the settlement dimension does not move when a spot airs"
    )
    assert order["first_air_at"] == "2026-08-10T12:00:00.000Z"
    assert order["paid_cents"] == 0
    assert order["net_due_cents"] == 200000


def test_settlement_advances_to_paid_while_the_lifecycle_stays_running(api):
    """PRD §3.6: "The two never gate each other structurally: an order that is
    `SUSPENDED`, `RUNNING` or `COMPLETED` may sit at any of `INVOICED`, `PAID` or
    `REFUND_DUE`."
    PRD §3.6: "A cleared `CHARGE` adds `amount_cents` to `paid_cents` and advances the
    settlement dimension `INVOICED → PAID`; a cleared `REFUND` adds `amount_cents` to
    `refunded_cents` and advances it `REFUND_DUE → REFUNDED`, closing the money
    invariant under which what the advertiser has paid net of refunds equals what the
    order is due."

    Design: Difficulty/non_linear_state_machine/order_lifecycle_and_settlement_dimensions_advance_independently
    """
    built = _running_candidate_order()
    order, advertiser = built["order"], built["advertiser"]

    settled = validate_success(
        api.record_payment(
            order["id"],
            payment_payload("CHARGE", 200000, order["version"]),
            make_advertiser_agent_headers(advertiser["id"]),
        )
    )
    assert settled["payment_status"] == "PAID"
    assert settled["paid_cents"] == 200000
    assert settled["status"] == "RUNNING", (
        "settling the invoice does not move the lifecycle dimension"
    )
    assert settled["first_air_at"] == "2026-08-10T12:00:00.000Z"
