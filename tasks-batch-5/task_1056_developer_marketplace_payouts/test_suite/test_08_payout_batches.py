"""Payout batches: window rules, the waterfall, approval, disbursement and retry."""
from test_helpers import (
    ApiErrorId,
    approve_batch,
    assert_payout_batch,
    assert_payout_waterfall_consistency,
    batch_lines,
    calculate_batch,
    create_payout_batch_payload,
    execute_refund_flow,
    lose_chargeback,
    only_line,
    open_batch,
    pay_batch,
    read_developer,
    record_and_capture,
    run_batch_to_paid,
    set_clock,
    set_payout_hold,
    set_tax_profile,
    setup_marketplace_with_live_app,
    single_line_purchase,
    submit_batch,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_new_batch_opens_with_zero_lines_and_zero_totals(api, finance_headers):
    """PRD 3.9: "A new batch opens at `OPEN` with `line_count`, `total_payable_cents`,
    `total_withholding_cents` and `total_reserve_cents` all 0."

    Design: Corner/state_machines/corner_payout_batch_created_in_open_state
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    payload = create_payout_batch_payload(
        payout_currency="USD", period_start="2026-07-01T00:00:00Z",
        period_end="2026-08-01T00:00:00Z",
    )
    data = validate_success(api.create_payout_batch(payload, finance_headers), 201)
    assert_payout_batch(data)
    assert data["status"] == "OPEN"
    assert data["line_count"] == 0
    assert data["total_payable_cents"] == 0
    assert data["total_withholding_cents"] == 0
    assert data["total_reserve_cents"] == 0


def test_batch_window_touching_the_previous_one_is_accepted(api, finance_headers):
    """PRD 3.9: "Windows that merely touch — where a previous batch's `period_end` is
    exactly the new batch's `period_start` — are accepted, since the half-open convention
    means no instant belongs to both."

    Design: Difficulty/resource_temporal_overlap/payout_batch_half_open_touching_window_accepted_overlap_rejected
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    open_batch(api, "USD", "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")

    payload = create_payout_batch_payload(
        payout_currency="USD", period_start="2026-08-01T00:00:00Z",
        period_end="2026-09-01T00:00:00Z",
    )
    data = validate_success(api.create_payout_batch(payload, finance_headers), 201)
    assert data["status"] == "OPEN"

    _rows, meta = validate_paginated(
        api.list_payout_batches(finance_headers, {"payout_currency": "USD"})
    )
    assert meta["total_count"] == 2


def test_batch_window_straddling_an_existing_one_is_rejected(api, finance_headers):
    """PRD 3.9: "`period_start` must fall strictly before `period_end`, and the window may
    not intersect the window of any existing batch in the same currency whose status is
    anything other than `FAILED`."
    PRD 3.9: "Any true intersection, or an inverted window, is rejected with
    `ERR_BATCH_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/payout_batch_half_open_touching_window_accepted_overlap_rejected
    """
    set_clock(api, "2026-07-01T00:00:00Z")
    open_batch(api, "USD", "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")
    open_batch(api, "USD", "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")

    payload = create_payout_batch_payload(
        payout_currency="USD", period_start="2026-07-15T00:00:00Z",
        period_end="2026-08-15T00:00:00Z",
    )
    response = api.create_payout_batch(payload, finance_headers)
    validate_error(response, ApiErrorId.ERR_BATCH_PERIOD_OVERLAP)
    assert response.status_code == 409

    _rows, meta = validate_paginated(
        api.list_payout_batches(finance_headers, {"payout_currency": "USD"})
    )
    assert meta["total_count"] == 2


def test_calculate_excludes_a_purchase_captured_outside_the_window(api, finance_headers):
    """PRD 3.9: "A developer's **eligible purchases** are those with `settlement_status`
    of `ACCRUED` whose `captured_at` falls at or after `period_start` and strictly before
    `period_end`, and whose pricing plan's `currency` equals the batch's
    `payout_currency`."
    PRD 3.9: "When no developer is eligible, the batch still reaches `CALCULATED` with
    `line_count` 0 and all three totals 0."

    Design: Corner/calculations/corner_payout_calculate_excludes_purchase_captured_outside_window
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 10000},
        app_overrides={"name": "Window", "category": "FINANCE"},
        developer_overrides={"legal_name": "Window Co", "email": "wc@x.test"},
    )
    batch = open_batch(api, "USD", "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")

    set_clock(api, "2026-08-15T00:00:00Z")
    purchase = record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-LATE",
        line_items=single_line_purchase(10000),
    )

    calculated = calculate_batch(api, batch["id"])
    assert calculated["status"] == "CALCULATED"
    assert calculated["line_count"] == 0
    assert calculated["total_payable_cents"] == 0
    assert batch_lines(api, batch["id"]) == []
    assert validate_success(
        api.get_purchase(purchase["id"], finance_headers)
    )["settlement_status"] == "ACCRUED"


def test_line_below_the_minimum_payout_is_held_and_carried_over(api):
    """PRD 3.9: "If that payable amount falls below the fifty-dollar minimum payout — five
    thousand cents — the line's `status` is `HELD_BELOW_MINIMUM`, its
    `payout_amount_cents` is 0, and its `carryover_added_cents` is the payable amount when
    positive and 0 when not, deferring the money into the next batch."
    PRD 3.9: "`total_reserve_cents` is the sum of `reserve_cents` over *all* lines in the
    batch regardless of status."

    Design: Corner/calculations/corner_payout_line_under_minimum_is_held_and_carried_over
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 6000},
        app_overrides={"name": "Small Fry", "category": "HEALTH"},
        developer_overrides={"legal_name": "Small Fry Co", "email": "sf2@x.test"},
    )
    record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-SMALL",
        line_items=single_line_purchase(6000),
    )
    batch = open_batch(api, "USD", "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")
    calculated = calculate_batch(api, batch["id"])

    assert calculated["line_count"] == 1
    assert calculated["total_payable_cents"] == 0
    assert calculated["total_reserve_cents"] == 210

    line = only_line(api, batch["id"])
    assert line["status"] == "HELD_BELOW_MINIMUM"
    assert line["gross_earnings_cents"] == 4200
    assert line["reserve_cents"] == 210
    assert line["payout_amount_cents"] == 0
    assert line["carryover_added_cents"] == 3990


def test_reserve_rounds_half_up_on_an_exact_half_cent(api):
    """PRD 3.9: "`reserve_cents` is a chargeback reserve of five percent — five hundred
    basis points — taken on `gross_earnings_cents` when that figure is positive and on
    zero when it is not, rounded half-up to a whole cent."
    PRD 2.6: "Wherever a computation produces a fractional number of cents, the result is
    rounded half-up to a whole cent: a value whose fractional part is exactly one half
    rounds away from zero to the next whole cent."

    Design: Corner/calculations/corner_reserve_uses_round_half_up_on_exact_half_cent
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 8643},
        app_overrides={"name": "Half Cent", "category": "DEVELOPER_TOOLS"},
        developer_overrides={"legal_name": "Half Cent Co", "email": "hc@x.test"},
    )
    captured = record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-HALF",
        line_items=single_line_purchase(8643),
    )
    assert captured["provisional_developer_net_cents"] == 6050

    batch = open_batch(api, "USD", "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")
    calculated = calculate_batch(api, batch["id"])
    assert calculated["total_reserve_cents"] == 303, "302.5 cents must round up to 303"
    assert calculated["total_payable_cents"] == 5747

    line = only_line(api, batch["id"])
    assert line["reserve_cents"] == 303
    assert line["payout_amount_cents"] == 5747


def test_approval_is_refused_while_a_payable_line_belongs_to_a_held_developer(
    api, admin_headers, finance_headers
):
    """PRD 3.9: "Approval is refused when any line in the batch whose status is `PAYABLE`
    belongs to a developer whose `payout_hold` is true, in which case the response is
    `ERR_DEVELOPER_PAYOUT_HELD`."

    Design: Corner/validations/corner_payout_approve_with_held_developer_returns_payout_held
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 20000},
        app_overrides={"name": "Held", "category": "FINANCE"},
        developer_overrides={"legal_name": "Held Co", "email": "hd@x.test"},
    )
    record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-HELD",
        line_items=single_line_purchase(20000),
    )
    batch = open_batch(api, "USD", "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")
    calculate_batch(api, batch["id"])
    submit_batch(api, batch["id"])

    held = set_payout_hold(api, ctx["developer_id"], True, "sanctions screening")
    assert held["payout_hold"] is True

    response = api.approve_payout_batch(batch["id"], admin_headers)
    validate_error(response, ApiErrorId.ERR_DEVELOPER_PAYOUT_HELD)
    assert response.status_code == 409

    after = validate_success(api.get_payout_batch(batch["id"], finance_headers))
    assert after["status"] == "PENDING_APPROVAL"
    assert after["approved_by_user_id"] is None


def test_failed_disbursement_can_be_retried(api, finance_headers):
    """PRD 3.9: "A `FAILED` disbursement instead moves the batch `APPROVED → FAILED`,
    stores the supplied `failure_reason`, and moves every `PAYABLE` line
    `PAYABLE → FAILED`; no ledger entry is created and no purchase's settlement dimension
    moves. Retry brings a failed batch back, `FAILED → PENDING_APPROVAL`, clearing
    `failure_reason` and returning every `FAILED` line `FAILED → PAYABLE` for a second
    approval and disbursement attempt."

    Design: Corner/state_machines/corner_payout_batch_retry_cycle_returns_failed_lines_to_payable
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 20000},
        app_overrides={"name": "Retry", "category": "DEVELOPER_TOOLS"},
        developer_overrides={"legal_name": "Retry Co", "email": "ry@x.test"},
    )
    purchase = record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-RETRY",
        line_items=single_line_purchase(20000),
    )
    batch = open_batch(api, "USD", "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")
    calculate_batch(api, batch["id"])
    submit_batch(api, batch["id"])
    approve_batch(api, batch["id"])

    failed = pay_batch(api, batch["id"], "FAILED", "bank rail unavailable")
    assert failed["status"] == "FAILED"
    assert failed["failure_reason"] == "bank rail unavailable"

    retried = validate_success(api.retry_payout_batch(batch["id"], finance_headers))
    assert retried["status"] == "PENDING_APPROVAL"
    assert retried["failure_reason"] is None

    line = only_line(api, batch["id"])
    assert line["status"] == "PAYABLE"
    assert line["payout_amount_cents"] == 13300
    assert validate_success(
        api.get_purchase(purchase["id"], finance_headers)
    )["settlement_status"] == "ACCRUED"


def _withholding_context(api):
    """A developer in backup withholding carrying a 7000-cent negative balance,
    with a fresh 100000-cent capture waiting in an August batch."""
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 10000},
        app_overrides={"name": "Falls", "category": "GAMES"},
        developer_overrides={"legal_name": "Waterfall Works", "email": "w@fall.test"},
    )
    set_tax_profile(api, ctx["developer_id"], False, "IRS B-notice: TIN mismatch")

    purchase_x = record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-X",
        line_items=single_line_purchase(10000),
    )
    batch1 = open_batch(api, "USD", "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")
    run_batch_to_paid(api, batch1["id"])

    lose_chargeback(api, purchase_x["id"], 10000, "CB-WF-1")
    assert read_developer(api, ctx["developer_id"])["negative_balance_cents"] == 7000

    set_clock(api, "2026-08-05T00:00:00Z")
    record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-Y",
        line_items=single_line_purchase(100000),
    )
    batch2 = open_batch(api, "USD", "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z")
    ctx["batch2_id"] = batch2["id"]
    return ctx


def test_withholding_is_taken_on_the_balance_after_recovery(api):
    """PRD 3.9: "`recovery_cents` is the smaller of two quantities: the balance after
    reserve when that balance is positive (and zero when it is not), and the developer's
    `negative_balance_cents`."
    PRD 3.9: "`withholding_cents` is 0 when the developer's `tax_id_provided` is true.
    Otherwise it is twenty-four percent — two thousand four hundred basis points — of the
    balance after recovery when that balance is positive and of zero when it is not,
    rounded half-up to a whole cent."

    Design: Difficulty/combinatorial_formula/backup_withholding_base_pinned_to_after_recovery_not_payable
    """
    ctx = _withholding_context(api)
    calculate_batch(api, ctx["batch2_id"])

    line = only_line(api, ctx["batch2_id"])
    assert line["gross_earnings_cents"] == 70000
    assert line["reserve_cents"] == 3500
    assert line["recovery_cents"] == 7000
    assert line["withholding_cents"] == 14280, (
        "24 percent of the 59500 balance after recovery, not of the 66500 after reserve"
    )


def test_payout_amount_is_the_balance_after_recovery_less_withholding(api):
    """PRD 3.9: "The waterfall then runs once per eligible developer, in a **pinned
    order**. It looks circular — withholding is a rate on what is payable, while payable
    is what remains after withholding — and the order below resolves it: withholding is
    always taken on the balance *after recovery*, never on the final payable amount."
    PRD 3.9: "The payable amount is the balance after recovery less `withholding_cents`."

    Design: Difficulty/combinatorial_formula/backup_withholding_base_pinned_to_after_recovery_not_payable
    """
    ctx = _withholding_context(api)
    calculate_batch(api, ctx["batch2_id"])

    line = only_line(api, ctx["batch2_id"])
    assert line["payout_amount_cents"] == 45220
    assert line["status"] == "PAYABLE"
    assert_payout_waterfall_consistency(line)


def _tier_boundary_context(api):
    """A developer whose second capture crosses the 1,000,000-cent tier breakpoint."""
    ctx = setup_marketplace_with_live_app(
        api,
        jurisdictions=[("US", 0, True), ("DE", 1900, True)],
        tiers=[("BASE", 0, 7000), ("SCALE", 1000000, 8500)],
        plan_overrides={"price_cents": 999},
        app_overrides={"name": "Acme Notes", "listed_countries": ["US", "DE"]},
        developer_overrides={"legal_name": "Acme Labs LLC", "email": "dev@acme.test"},
    )
    record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-BIG-1",
        line_items=[{"sku": "site-license", "unit_price_cents": 999000, "quantity": 1}],
    )
    ctx["p2"] = record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], buyer_country_code="DE",
        external_order_ref="ORD-DE-1",
        line_items=[
            {"sku": "seat-a", "unit_price_cents": 999, "quantity": 1},
            {"sku": "seat-b", "unit_price_cents": 999, "quantity": 1},
            {"sku": "seat-c", "unit_price_cents": 999, "quantity": 1},
        ],
    )
    batch = open_batch(api, "USD", "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")
    ctx["batch_id"] = batch["id"]
    return ctx


def test_boundary_crossing_capture_is_booked_at_the_lower_provisional_rate(api):
    """PRD 3.5: "Moving `AUTHORIZED → CAPTURED` stamps `captured_at` with the current
    logical clock and runs the revenue share in its **provisional** variant: the tier is
    selected from the developer's `lifetime_revenue_base_cents` *as it stands just before
    this capture is folded in*, so a purchase that itself crosses a tier boundary is
    booked at the lower rate."
    PRD 3.9: "Each eligible purchase's final net is its `revenue_base_cents` multiplied by
    `final_share_bps` and divided by ten thousand, rounded half-up to a whole cent, and
    `tier_trueup_cents` is the sum over the eligible purchases of that final net less the
    purchase's `provisional_developer_net_cents`."

    Design: Difficulty/dual_variant_calc/revenue_share_provisional_vs_final_on_tier_boundary_crossing_purchase
    """
    ctx = _tier_boundary_context(api)
    assert ctx["p2"]["provisional_share_bps"] == 7000
    assert ctx["p2"]["provisional_developer_net_cents"] == 1762

    calculated = calculate_batch(api, ctx["batch_id"])
    assert calculated["line_count"] == 1

    line = only_line(api, ctx["batch_id"])
    assert line["final_share_bps"] == 8500
    assert line["tier_trueup_cents"] == 150227


def test_final_variant_re_rates_the_whole_window_into_the_payout(api):
    """PRD 3.9: "Before the waterfall runs, the revenue share is re-evaluated in its
    **final** variant: for each developer, a single rate is selected once from that
    developer's `lifetime_revenue_base_cents` *as it stands at calculation time* — that
    is, after every capture in the window has already landed — and stored on the line as
    `final_share_bps`."
    PRD 3.9: "`gross_earnings_cents` is the sum of the final nets over the eligible
    purchases, plus the sum of `developer_tax_remittance_cents` over those same purchases,
    minus the sum of `developer_net_reversal_cents` over the executed refunds booked
    against those purchases, plus the developer's current `carryover_cents`."

    Design: Difficulty/dual_variant_calc/revenue_share_provisional_vs_final_on_tier_boundary_crossing_purchase
    """
    ctx = _tier_boundary_context(api)
    calculate_batch(api, ctx["batch_id"])

    line = only_line(api, ctx["batch_id"])
    assert line["gross_earnings_cents"] == 851289
    assert line["payout_amount_cents"] == 808725
    assert_payout_waterfall_consistency(line)


def test_disbursement_settles_the_purchase_while_the_payment_dimension_stays_put(
    api, finance_headers
):
    """PRD 3.9: "A `SUCCEEDED` disbursement moves the batch `APPROVED → PAID` and every
    `PAYABLE` line `PAYABLE → PAID`."
    PRD 3.9: "marks every swept ledger entry with `settled` true and its `payout_line_id`
    set to the paying line, and moves each swept purchase `ACCRUED → PAID` on its
    settlement dimension."
    PRD 3.6: "The settlement dimension is deliberately untouched by a refund — a partially
    refunded purchase remains `ACCRUED` — which is the clearest demonstration that the two
    dimensions move independently."

    Design: Difficulty/non_linear_state_machine/purchase_payment_and_settlement_dimensions_advance_independently
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 20000},
        app_overrides={"name": "Dim", "category": "DEVELOPER_TOOLS"},
        developer_overrides={"legal_name": "Parallel Dimensions Ltd", "email": "p@dim.test"},
    )
    purchase = record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-PARA",
        line_items=single_line_purchase(20000),
    )
    execute_refund_flow(api, purchase["id"], 4000)

    batch = open_batch(api, "USD", "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")
    calculated = calculate_batch(api, batch["id"])
    assert calculated["total_payable_cents"] == 10640

    submit_batch(api, batch["id"])
    approve_batch(api, batch["id"])
    paid = pay_batch(api, batch["id"], "SUCCEEDED")
    assert paid["status"] == "PAID"

    after = validate_success(api.get_purchase(purchase["id"], finance_headers))
    assert after["payment_status"] == "PARTIALLY_REFUNDED"
    assert after["settlement_status"] == "PAID"

    line = only_line(api, batch["id"])
    assert line["status"] == "PAID"
    assert line["payout_amount_cents"] == 10640
