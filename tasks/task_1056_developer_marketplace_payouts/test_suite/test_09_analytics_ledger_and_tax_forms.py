"""The ledger, listing analytics, the developer summary and the annual 1099."""
from test_helpers import (
    ApiErrorId,
    assert_ledger_entry,
    assert_payout_waterfall_consistency,
    calculate_batch,
    create_tax_form_payload,
    create_verified_developer,
    developer_summary,
    execute_refund_flow,
    ledger_entries,
    make_developer_headers,
    only_line,
    open_batch,
    record_and_capture,
    record_purchase,
    run_batch_to_paid,
    setup_marketplace_with_live_app,
    single_line_purchase,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_ledger_entries_expose_no_version_or_updated_at(api):
    """PRD 2.4: "Three resource types are deliberately immutable reference data or
    append-only records and therefore carry **only** `id` and `created_at` — they expose
    neither `updated_at` nor `version`, and those two fields must be absent from their
    representations entirely: `TaxJurisdiction`, `RevenueShareTier` and `LedgerEntry`."
    PRD 3.10: "Entries may be read individually, listed marketplace-wide or listed for a
    single developer, filtered by `developer_id`, `purchase_id`, `payout_line_id`,
    `entry_type` and `settled`."

    Design: Corner/entities/corner_ledger_entry_has_no_version_and_no_write_endpoint
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 10000},
        app_overrides={"name": "Books", "category": "FINANCE"},
        developer_overrides={"legal_name": "Immutable Books", "email": "ib@x.test"},
    )
    purchase = record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-IMM",
        line_items=single_line_purchase(10000),
    )

    entries = ledger_entries(api, purchase_id=purchase["id"], entry_type="ACCRUAL")
    assert len(entries) == 1
    entry = entries[0]
    assert entry["amount_cents"] == 7000
    assert_ledger_entry(entry)
    assert "version" not in entry
    assert "updated_at" not in entry


def test_developer_summary_reports_the_ledger_position(api):
    """PRD 3.2: "The account exposes a computed summary read reporting `developer_id`,
    `unpaid_accrual_cents`, `negative_balance_cents`, `carryover_cents`,
    `lifetime_revenue_base_cents`, `risk_score`, `risk_variant` and `payout_hold` — the
    ledger position and risk posture in one place."
    PRD 2.9: "`unpaid_accrual_cents` is recomputed after every ledger movement as the sum
    of `amount_cents` over that developer's `LedgerEntry` rows whose `settled` flag is
    false"

    Design: Corner/endpoints/corner_developer_summary_computed_read_matches_ledger
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 10000},
        app_overrides={"name": "Summary", "category": "PRODUCTIVITY"},
        developer_overrides={"legal_name": "Summary Co", "email": "sm@x.test"},
    )
    record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-SUM",
        line_items=single_line_purchase(10000),
    )

    summary = developer_summary(
        api, ctx["developer_id"], make_developer_headers(ctx["developer_id"])
    )
    assert summary["developer_id"] == ctx["developer_id"]
    assert summary["unpaid_accrual_cents"] == 7000
    assert summary["lifetime_revenue_base_cents"] == 10000
    assert summary["carryover_cents"] == 0
    assert summary["payout_hold"] is False


def test_analytics_rolls_up_a_partially_refunded_purchase(api):
    """PRD 3.10: "The roll-up reports the `app_id` alongside `gross_cents`, `tax_cents`,
    `revenue_base_cents` and `refunded_gross_cents` as the sums of the like-named purchase
    fields, `developer_net_cents` as the sum of `provisional_developer_net_cents`,
    `unit_count` as the total of `quantity` across every line item of every scored
    purchase, and `refund_rate_bps` as the summed `refunded_gross_cents` multiplied by ten
    thousand and divided by the summed `gross_cents`, rounded half-up to a whole number."

    Design: Corner/calculations/corner_app_analytics_rollup_with_captured_and_partially_refunded_purchase
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 20000},
        app_overrides={"name": "Analytics", "category": "PRODUCTIVITY"},
        developer_overrides={"legal_name": "Analytics Co", "email": "an@x.test"},
    )
    purchase = record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-AN",
        line_items=single_line_purchase(20000),
    )
    execute_refund_flow(api, purchase["id"], 4000)

    data = validate_success(
        api.get_app_analytics(ctx["app_id"], make_developer_headers(ctx["developer_id"]))
    )
    assert data["gross_cents"] == 20000
    assert data["developer_net_cents"] == 14000
    assert data["refunded_gross_cents"] == 4000
    assert data["unit_count"] == 1
    assert data["refund_rate_bps"] == 2000


def test_analytics_with_no_captured_purchase_reports_zero_refund_rate(api,
                                                                      storefront_headers):
    """PRD 3.10: "When the summed `gross_cents` is 0 the refund rate is reported as 0
    rather than raising a division error, so a listing with no captured purchase yields
    every field 0."

    Design: Difficulty/boundary_precision_check/app_analytics_with_no_captured_purchase_returns_zero_refund_rate
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 1500},
        app_overrides={"name": "Empty", "category": "HEALTH"},
        developer_overrides={"legal_name": "Empty Set Inc", "email": "e@empty.test"},
    )
    record_purchase(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-AUTH-ONLY",
        line_items=single_line_purchase(1500, quantity=2),
    )
    voided = record_purchase(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-VOIDED",
        line_items=single_line_purchase(1500),
    )
    validate_success(api.void_purchase(voided["id"], storefront_headers))

    data = validate_success(
        api.get_app_analytics(ctx["app_id"], make_developer_headers(ctx["developer_id"]))
    )
    assert data["gross_cents"] == 0
    assert data["refund_rate_bps"] == 0
    assert data["unit_count"] == 0


def test_authorized_and_voided_purchases_never_enter_the_roll_up(api, storefront_headers,
                                                                  finance_headers):
    """PRD 3.10: "A listing's sales roll-up is computed on demand from that listing's
    purchases whose `payment_status` is `CAPTURED`, `PARTIALLY_REFUNDED`, `REFUNDED` or
    `CHARGED_BACK`; purchases still `AUTHORIZED` and purchases `VOIDED` are excluded."

    Design: Difficulty/boundary_precision_check/app_analytics_with_no_captured_purchase_returns_zero_refund_rate
    """
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 1500},
        app_overrides={"name": "Empty", "category": "HEALTH"},
        developer_overrides={"legal_name": "Empty Set Inc", "email": "e@empty.test"},
    )
    authorized = record_purchase(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-AUTH-ONLY-2",
        line_items=single_line_purchase(1500, quantity=2),
    )
    voided = record_purchase(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-VOIDED-2",
        line_items=single_line_purchase(1500),
    )
    validate_success(api.void_purchase(voided["id"], storefront_headers))

    assert validate_success(
        api.get_purchase(authorized["id"], finance_headers)
    )["payment_status"] == "AUTHORIZED"
    assert validate_success(
        api.get_purchase(voided["id"], finance_headers)
    )["payment_status"] == "VOIDED"

    data = validate_success(
        api.get_app_analytics(ctx["app_id"], make_developer_headers(ctx["developer_id"]))
    )
    assert data["tax_cents"] == 0
    assert data["revenue_base_cents"] == 0
    assert data["developer_net_cents"] == 0
    assert data["refunded_gross_cents"] == 0


def _threshold_context(api):
    """A single paid line worth exactly the sixty-thousand-cent reporting threshold."""
    ctx = setup_marketplace_with_live_app(
        api,
        plan_overrides={"price_cents": 90226},
        app_overrides={"name": "Thresh", "category": "DEVELOPER_TOOLS"},
        developer_overrides={"legal_name": "Threshold Tools", "email": "t@thresh.test"},
    )
    record_and_capture(
        api, ctx["app_id"], ctx["plan_id"], external_order_ref="ORD-THRESH",
        line_items=single_line_purchase(90226),
    )
    batch = open_batch(api, "USD", "2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z")
    ctx["batch_id"] = batch["id"]
    return ctx


def test_payout_line_lands_exactly_on_the_reporting_threshold(api):
    """PRD 3.9: "`total_payable_cents` is the sum of `payout_amount_cents` over lines
    whose status is `PAYABLE`, `total_withholding_cents` is the sum of
    `withholding_cents` over those same `PAYABLE` lines, and `total_reserve_cents` is the
    sum of `reserve_cents` over *all* lines in the batch regardless of status."
    PRD 3.9: "`withholding_cents` is 0 when the developer's `tax_id_provided` is true."

    Design: Difficulty/boundary_precision_check/form_1099_reportable_exactly_at_threshold_is_issuable
    """
    ctx = _threshold_context(api)
    calculated = calculate_batch(api, ctx["batch_id"])
    assert calculated["total_payable_cents"] == 60000

    line = only_line(api, ctx["batch_id"])
    assert line["gross_earnings_cents"] == 63158
    assert line["reserve_cents"] == 3158
    assert line["withholding_cents"] == 0
    assert line["payout_amount_cents"] == 60000
    assert_payout_waterfall_consistency(line)


def test_form_reportable_exactly_at_the_threshold_is_issuable(api, admin_headers):
    """PRD 3.10: "`reportable_cents` is the sum over those lines of `payout_amount_cents`
    plus `withholding_cents` — the gross reportable payout before backup withholding was
    taken — and `withheld_cents` is the sum of `withholding_cents` alone.
    `threshold_cents` records the six-hundred-dollar reporting threshold applied, that is,
    sixty thousand cents. The form's `status` is `ISSUABLE` when `reportable_cents` is
    greater than or equal to that threshold — exactly sixty thousand cents is issuable —
    and `NOT_REQUIRED` otherwise."

    Design: Difficulty/boundary_precision_check/form_1099_reportable_exactly_at_threshold_is_issuable
    """
    ctx = _threshold_context(api)
    run_batch_to_paid(api, ctx["batch_id"])

    payload = create_tax_form_payload(ctx["developer_id"], tax_year=2026)
    form = validate_success(api.create_tax_form(payload, admin_headers), 201)
    assert form["reportable_cents"] == 60000
    assert form["status"] == "ISSUABLE"
    assert form["withheld_cents"] == 0
    assert form["threshold_cents"] == 60000


def test_second_form_for_the_same_developer_and_year_is_rejected(api, admin_headers):
    """PRD 3.10: "The annual form is generated by a `PlatformAdmin` naming a
    `developer_id` and a `tax_year`, and at most one form may exist per developer and year
    — a second attempt is rejected with `ERR_TAX_FORM_EXISTS`."
    PRD 3.10: "The roll-up considers only that developer's payout lines whose status is
    `PAID` and whose owning batch's `period_start` falls within the named `tax_year` as a
    UTC calendar year; lines that are `PAYABLE`, `HELD_BELOW_MINIMUM`, `HELD_DEVELOPER` or
    `FAILED` are excluded entirely."

    Design: Corner/validations/corner_duplicate_tax_form_for_same_year_returns_conflict
    """
    developer = create_verified_developer(
        api, legal_name="Form Co", email="fm@x.test", country_code="US"
    )
    first = validate_success(
        api.create_tax_form(create_tax_form_payload(developer["id"], tax_year=2026),
                            admin_headers),
        201,
    )
    assert first["reportable_cents"] == 0
    assert first["status"] == "NOT_REQUIRED"

    response = api.create_tax_form(
        create_tax_form_payload(developer["id"], tax_year=2026), admin_headers
    )
    validate_error(response, ApiErrorId.ERR_TAX_FORM_EXISTS)
    assert response.status_code == 409

    _rows, meta = validate_paginated(
        api.list_tax_forms(admin_headers, {"developer_id": developer["id"]})
    )
    assert meta["total_count"] == 1
