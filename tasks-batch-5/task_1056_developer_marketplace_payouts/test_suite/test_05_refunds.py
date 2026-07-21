"""Refunds: filing guards, execution, the reversal split and the full-refund clamp."""
from test_helpers import (
    ApiErrorId,
    approve_refund,
    execute_refund_flow,
    ledger_entries,
    ledger_sum,
    lose_chargeback,
    read_developer,
    record_and_capture,
    request_refund,
    set_clock,
    setup_marketplace_with_live_app,
    single_line_purchase,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_refund_request_after_thirty_days_is_rejected(api, storefront_headers,
                                                       finance_headers):
    """PRD 3.6: "And the request must arrive while the logical clock is at or before the
    purchase's `captured_at` plus thirty days — exactly thirty days after capture is still
    in time, later is rejected with `ERR_REFUND_WINDOW_EXPIRED`."

    Design: Corner/validations/corner_refund_request_after_window_expired_returns_422
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 10000},
        app_overrides={"name": "Late Refund", "category": "HEALTH"},
        developer_overrides={"legal_name": "Late Refund Co", "email": "lr@x.test"},
    )
    purchase = record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-LATE-REF",
        line_items=single_line_purchase(10000),
    )
    set_clock(api, "2026-08-01T00:00:00Z")  # 31 days after capture

    response = api.request_refund(
        purchase["id"], {"amount_cents": 1000, "reason": "BUYER_REQUEST"}, storefront_headers
    )
    validate_error(response, ApiErrorId.ERR_REFUND_WINDOW_EXPIRED)
    assert response.status_code == 422

    _rows, meta = validate_paginated(
        api.list_refunds(finance_headers, {"purchase_id": purchase["id"]})
    )
    assert meta["total_count"] == 0


def test_refund_above_the_remaining_headroom_is_rejected(api, storefront_headers,
                                                          finance_headers):
    """PRD 3.6: "Finally, `amount_cents` may not exceed the purchase's `gross_cents` less
    its `refunded_gross_cents`, or the request is rejected with
    `ERR_REFUND_EXCEEDS_REMAINING`."
    PRD 3.6: "Execution then raises `refunded_gross_cents` by the refund's `amount_cents`
    and drives the payment dimension. If the resulting `refunded_gross_cents` is still
    below `gross_cents`, the purchase moves `CAPTURED → PARTIALLY_REFUNDED`."

    Design: Corner/validations/corner_refund_amount_above_remaining_returns_exceeds_remaining
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 10000},
        app_overrides={"name": "Excess", "category": "PRODUCTIVITY"},
        developer_overrides={"legal_name": "Excess Co", "email": "ex@x.test"},
    )
    purchase = record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-EXCESS",
        line_items=single_line_purchase(10000),
    )
    execute_refund_flow(api, purchase["id"], 4000)

    response = api.request_refund(
        purchase["id"], {"amount_cents": 6001, "reason": "BUYER_REQUEST"}, storefront_headers
    )
    validate_error(response, ApiErrorId.ERR_REFUND_EXCEEDS_REMAINING)
    assert response.status_code == 422

    after = validate_success(api.get_purchase(purchase["id"], finance_headers))
    assert after["refunded_gross_cents"] == 4000
    assert after["payment_status"] == "PARTIALLY_REFUNDED"

    _rows, meta = validate_paginated(
        api.list_refunds(finance_headers, {"purchase_id": purchase["id"]})
    )
    assert meta["total_count"] == 1


def test_charged_back_purchase_reports_the_state_error_not_the_headroom_error(
    api, storefront_headers, finance_headers
):
    """PRD 2.8: "When a single request would fail several checks, the rejection that is
    returned is fixed and not implementation-dependent. Checks are evaluated in the
    following order, and the first one that fails determines the response:"
    PRD 2.8: "Where a transition additionally requires the owning account to be `ACTIVE`,
    that check follows immediately (`ERR_DEVELOPER_NOT_ACTIVE`), then the refundability
    check on a purchase (`ERR_PURCHASE_NOT_REFUNDABLE`)."
    PRD 2.8: "Fiscal and remaining business checks. Refund headroom
    (`ERR_REFUND_EXCEEDS_REMAINING`), then pricing-period coherence
    (`ERR_INVALID_PRICING`), then the tax-identity precondition on verification
    (`ERR_TAX_ID_REQUIRED`), then the uniqueness of an annual form
    (`ERR_TAX_FORM_EXISTS`) and of a jurisdiction (`ERR_JURISDICTION_EXISTS`)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_refund_request_on_charged_back_purchase
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 10000},
        app_overrides={"name": "Prio", "category": "FINANCE"},
        developer_overrides={"legal_name": "Priority Labs", "email": "p@prio.test"},
    )
    purchase = record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-PRIO",
        line_items=single_line_purchase(10000),
    )
    lose_chargeback(api, purchase["id"], 10000, "CB-PRIO-1")

    # 99999 also breaches the refund headroom; the state check must win.
    response = api.request_refund(
        purchase["id"], {"amount_cents": 99999, "reason": "BUYER_REQUEST"}, storefront_headers
    )
    validate_error(response, ApiErrorId.ERR_PURCHASE_NOT_REFUNDABLE)
    assert response.status_code == 409

    _rows, meta = validate_paginated(
        api.list_refunds(finance_headers, {"purchase_id": purchase["id"]})
    )
    assert meta["total_count"] == 0


def test_charged_back_purchase_rejects_even_a_within_headroom_refund(
    api, storefront_headers, finance_headers
):
    """PRD 3.6: "The purchase's `payment_status` must be `CAPTURED` or
    `PARTIALLY_REFUNDED`; a purchase that is `AUTHORIZED`, `VOIDED`, already fully
    `REFUNDED` or `CHARGED_BACK` is not refundable and the request is rejected with
    `ERR_PURCHASE_NOT_REFUNDABLE`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_refund_request_on_charged_back_purchase
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 10000},
        app_overrides={"name": "Prio", "category": "FINANCE"},
        developer_overrides={"legal_name": "Priority Labs", "email": "p@prio.test"},
    )
    purchase = record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-PRIO-2",
        line_items=single_line_purchase(10000),
    )
    lose_chargeback(api, purchase["id"], 10000, "CB-PRIO-2")

    # 1000 is comfortably inside the headroom, so only the state check can fire.
    response = api.request_refund(
        purchase["id"], {"amount_cents": 1000, "reason": "BUYER_REQUEST"}, storefront_headers
    )
    validate_error(response, ApiErrorId.ERR_PURCHASE_NOT_REFUNDABLE)
    assert response.status_code == 409

    _rows, meta = validate_paginated(
        api.list_refunds(finance_headers, {"purchase_id": purchase["id"]})
    )
    assert meta["total_count"] == 0


def test_approved_refund_cannot_execute_once_the_purchase_is_charged_back(
    api, finance_headers
):
    """PRD 3.6: "Execution moves an approved refund `APPROVED → EXECUTED` and is the point
    at which money actually reverses. It re-checks refundability: the linked purchase's
    `payment_status` must still be `CAPTURED` or `PARTIALLY_REFUNDED`, or the execution is
    rejected with `ERR_PURCHASE_NOT_REFUNDABLE`."

    Design: Difficulty/cross_entity_state_dependency/refund_execute_gated_on_purchase_payment_status
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 10000},
        app_overrides={"name": "GR App", "category": "FINANCE"},
        developer_overrides={"legal_name": "Gate Refunds", "email": "gr@gate.test"},
    )
    purchase = record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-GR",
        line_items=single_line_purchase(10000),
    )
    refund = request_refund(api, purchase["id"], 5000)
    approve_refund(api, refund["id"])
    lose_chargeback(api, purchase["id"], 10000, "CB-GR-1")

    response = api.execute_refund(refund["id"], finance_headers)
    validate_error(response, ApiErrorId.ERR_PURCHASE_NOT_REFUNDABLE)
    assert response.status_code == 409

    assert validate_success(api.get_refund(refund["id"], finance_headers))["status"] == "APPROVED"
    assert validate_success(
        api.get_purchase(purchase["id"], finance_headers)
    )["refunded_gross_cents"] == 0


def test_approved_refund_executes_while_the_purchase_is_still_captured(api, finance_headers):
    """PRD 3.6: "`FinanceOps` decides a requested refund with an `outcome` of `APPROVED`
    or `DENIED` and an optional `note`, moving it `REQUESTED → APPROVED` or
    `REQUESTED → DENIED` and stamping `decided_by_user_id` with the acting `X-User-ID`."
    PRD 3.6: "In every case a ledger entry of `entry_type` `REFUND_REVERSAL` is written
    whose `amount_cents` is the negative of `developer_net_reversal_cents`, the
    developer's `unpaid_accrual_cents` is recomputed, and the risk score is recomputed."

    Design: Difficulty/cross_entity_state_dependency/refund_execute_gated_on_purchase_payment_status
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 10000},
        app_overrides={"name": "GR App", "category": "FINANCE"},
        developer_overrides={"legal_name": "Gate Refunds", "email": "gr@gate.test"},
    )
    purchase = record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-GR-OK",
        line_items=single_line_purchase(10000),
    )
    refund = request_refund(api, purchase["id"], 5000)
    approved = approve_refund(api, refund["id"])
    assert approved["status"] == "APPROVED"
    assert approved["decided_by_user_id"] == "fin-1"

    executed = validate_success(api.execute_refund(refund["id"], finance_headers))
    assert executed["status"] == "EXECUTED"
    assert executed["developer_net_reversal_cents"] == 3500

    after = validate_success(api.get_purchase(purchase["id"], finance_headers))
    assert after["payment_status"] == "PARTIALLY_REFUNDED"
    assert after["refunded_gross_cents"] == 5000

    reversals = ledger_entries(api, purchase_id=purchase["id"],
                               entry_type="REFUND_REVERSAL")
    assert len(reversals) == 1
    assert reversals[0]["amount_cents"] == -3500


def test_partial_refund_leaves_the_settlement_dimension_untouched(api, finance_headers):
    """PRD 3.6: "The settlement dimension is deliberately untouched by a refund — a
    partially refunded purchase remains `ACCRUED` — which is the clearest demonstration
    that the two dimensions move independently."
    PRD 3.6: "The ordinary branch, taken when this refund does *not* close out the
    purchase, computes `tax_reversal_cents` as the refund's `amount_cents` multiplied by
    the jurisdiction's `vat_rate_bps` and divided by the sum of ten thousand and that
    rate, rounded half-up to a whole cent."

    Design: Difficulty/non_linear_state_machine/purchase_payment_and_settlement_dimensions_advance_independently
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 20000},
        app_overrides={"name": "Dim", "category": "DEVELOPER_TOOLS"},
        developer_overrides={"legal_name": "Parallel Dimensions Ltd", "email": "p@dim.test"},
    )
    purchase = record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-PARA-A",
        line_items=single_line_purchase(20000),
    )
    assert purchase["provisional_developer_net_cents"] == 14000

    executed = execute_refund_flow(api, purchase["id"], 4000)
    assert executed["developer_net_reversal_cents"] == 2800

    after = validate_success(api.get_purchase(purchase["id"], finance_headers))
    assert after["payment_status"] == "PARTIALLY_REFUNDED"
    assert after["settlement_status"] == "ACCRUED"


def test_full_refund_clamp_reverses_the_exact_provisional_net(api, finance_headers):
    """PRD 3.6: "In that case the closing refund absorbs every remaining cent rather than
    recomputing proportionally: `tax_reversal_cents` is the purchase's `tax_cents` less
    the sum of `tax_reversal_cents` over all previously executed refunds on that purchase,
    and `developer_net_reversal_cents` is the purchase's
    `provisional_developer_net_cents` less the sum of `developer_net_reversal_cents` over
    all previously executed refunds on that purchase."

    Design: Difficulty/compensating_invariant/full_refund_closes_per_purchase_ledger_sum_at_zero
    """
    ctx = setup_marketplace_with_live_app(
        api,
        jurisdictions=[("US", 0, True), ("DE", 1900, True)],
        plan_overrides={"price_cents": 999},
        app_overrides={"name": "Clamp", "listed_countries": ["US", "DE"]},
        developer_overrides={"legal_name": "Clamp Works", "email": "c@clamp.test"},
    )
    purchase = record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], buyer_country_code="DE",
        external_order_ref="ORD-CLAMP",
        line_items=[
            {"sku": "seat-a", "unit_price_cents": 999, "quantity": 1},
            {"sku": "seat-b", "unit_price_cents": 999, "quantity": 1},
            {"sku": "seat-c", "unit_price_cents": 999, "quantity": 1},
        ],
    )
    assert purchase["provisional_developer_net_cents"] == 1762

    executed = execute_refund_flow(api, purchase["id"], 2997)
    assert executed["tax_reversal_cents"] == 480
    assert executed["developer_net_reversal_cents"] == 1762

    after = validate_success(api.get_purchase(purchase["id"], finance_headers))
    assert after["payment_status"] == "REFUNDED"
    assert after["refunded_gross_cents"] == 2997


def test_full_refund_closes_the_per_purchase_ledger_at_zero(api):
    """PRD 3.6: "This is what makes the per-purchase ledger close at exactly zero: once
    the closing refund has executed, the `amount_cents` of every ledger entry attached to
    that purchase sums to 0, and `refunded_gross_cents` equals `gross_cents`."
    PRD 2.9: "`unpaid_accrual_cents` is recomputed after every ledger movement as the sum
    of `amount_cents` over that developer's `LedgerEntry` rows whose `settled` flag is
    false"

    Design: Difficulty/compensating_invariant/full_refund_closes_per_purchase_ledger_sum_at_zero
    """
    ctx = setup_marketplace_with_live_app(
        api,
        jurisdictions=[("US", 0, True), ("DE", 1900, True)],
        plan_overrides={"price_cents": 999},
        app_overrides={"name": "Clamp", "listed_countries": ["US", "DE"]},
        developer_overrides={"legal_name": "Clamp Works", "email": "c@clamp.test"},
    )
    purchase = record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], buyer_country_code="DE",
        external_order_ref="ORD-CLAMP-2",
        line_items=[
            {"sku": "seat-a", "unit_price_cents": 999, "quantity": 1},
            {"sku": "seat-b", "unit_price_cents": 999, "quantity": 1},
            {"sku": "seat-c", "unit_price_cents": 999, "quantity": 1},
        ],
    )
    execute_refund_flow(api, purchase["id"], 2997)

    assert ledger_sum(api, purchase_id=purchase["id"]) == 0, (
        "the full-refund clamp must close the per-purchase ledger at exactly zero"
    )
    assert read_developer(api, ctx["developer_id"])["unpaid_accrual_cents"] == 0
