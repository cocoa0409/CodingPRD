"""Sales orders, channel gating, excise computation, and excise reports."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    TEST_USERS, api_client,
    create_license, create_order_payload, create_excise_report_payload,
    set_clock, setup_completed_packaging_run, assert_order,
)

CO = TEST_USERS["compliance_officer_headers"]
SR = TEST_USERS["sales_rep_headers"]


def _ship_order(product_id, run_id, units=5, price=1200,
                channel="TASTING_ROOM", state="NY"):
    order = validate_success(api_client.create_order(
        create_order_payload(product_id, run_id, channel=channel,
                             destination_state=state, units=units,
                             unit_price_cents=price), SR), 201)
    validate_success(api_client.confirm_order(order["id"], SR), 200)
    return validate_success(api_client.ship_order(order["id"], SR), 200)


# ─── Difficulty: combinatorial_formula / excise per-line rounding ───────────

def test_excise_report_sums_per_line_rounded_amounts(api):
    """PRD section 3.6: "The order's volume in liters is its `units` times the
    container size of the run's `package_format`; the `excise_tax_cents` is that
    liter figure times 22.6, rounded half up to whole cents on the line, and
    because each order carries a single line, per-line rounding then summation
    are the same thing here — but at report time the rule stands: round each
    order's excise first, then sum, never sum liters and round once."
    PRD section 3.7: "The `taxable_cents` sums each replayed order's
    `excise_tax_cents` — each already rounded to whole cents at confirmation —
    subtracting rather than adding for `RETURNED` orders; the `taxable_liters`
    likewise sums each order's `units` times its container size, subtracting
    for returns."

    Two shipped orders of 5 x BOTTLE_500ML: per-order excise is
    round_half_up(2.5 * 22.6) = round_half_up(56.5) = 57; the period total is
    57 + 57 = 114 cents (sum-first would wrongly give 113), liters 5.

    Design: Difficulty/combinatorial_formula/excise_per_line_rounding_then_sum
    """
    ctx = setup_completed_packaging_run(volume_liters=50, measured_brix=13.5,
                                        gravity_brix=5.0, target_abv_pct=4.7,
                                        extra_markets=["NY_SLA"])
    report = validate_success(api_client.create_excise_report(
        create_excise_report_payload(period_year=2026, period_month=10,
                                     regulator="TTB"), CO), 201)

    _ship_order(ctx["product"]["id"], ctx["run"]["id"])
    _ship_order(ctx["product"]["id"], ctx["run"]["id"])

    report_after = validate_success(api_client.get_excise_report(report["id"], CO), 200)
    assert report_after["taxable_cents"] == 114, "per-line rounding must be summed, not sum-then-round"
    assert report_after["taxable_liters"] == 5, "two orders of 5 x 0.500 L"


def test_order_level_excise_rounded_half_up_on_confirm(api):
    """PRD section 3.6: "the `excise_tax_cents` is that liter figure times 22.6,
    rounded half up to whole cents on the line"
    PRD section 3.6: "the order's `subtotal_cents` is the `units` multiplied by
    the `unit_price_cents`" and "The order's `total_cents` is the
    `subtotal_cents` plus the `excise_tax_cents`."

    One order of 5 x BOTTLE_500ML at 1200 cents: subtotal 6000, excise
    round_half_up(2.5 * 22.6) = 57, total 6057.

    Design: Difficulty/combinatorial_formula/excise_per_line_rounding_then_sum
    """
    ctx = setup_completed_packaging_run(volume_liters=50, measured_brix=13.5,
                                        gravity_brix=5.0, target_abv_pct=4.7,
                                        extra_markets=["NY_SLA"])
    order = validate_success(api_client.create_order(
        create_order_payload(ctx["product"]["id"], ctx["run"]["id"],
                             units=5, unit_price_cents=1200), SR), 201)
    assert_order(order)
    assert order["status"] == "DRAFT"
    assert order["subtotal_cents"] == 6000

    confirmed = validate_success(api_client.confirm_order(order["id"], SR), 200)
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["excise_tax_cents"] == 57, "round_half_up(56.5) on the line"
    assert confirmed["total_cents"] == 6057, "subtotal + excise"


# ─── Difficulty: cross_entity_state_dependency / order label gate ───────────

def test_order_confirm_requires_label_approved_for_destination_market(api):
    """PRD section 3.6: "The label gates of §3.4 then apply to the product and
    the destination state's regulator market (`NY_SLA` for New York, `VT_DLL`
    for Vermont, `MA_ABCC` for Massachusetts): the approval must be `APPROVED`,
    else `ERR_LABEL_NOT_APPROVED`, and unexpired for non-federal markets, else
    `ERR_LABEL_EXPIRED`."

    A club order shipping to Vermont with only a FEDERAL_TTB approval on the
    product is rejected at confirmation.

    Design: Difficulty/cross_entity_state_dependency/sales_order_confirm_requires_label_approved_for_market
    """
    ctx = setup_completed_packaging_run(volume_liters=50, target_abv_pct=5.0)
    create_license(kind="INTERSTATE_SHIPPER", license_number="LIC-VT",
                   scope_states=["VT", "NY"])
    order = validate_success(api_client.create_order(
        create_order_payload(ctx["product"]["id"], ctx["run"]["id"],
                             channel="CLUB_SUBSCRIPTION", destination_state="VT",
                             units=5, unit_price_cents=1500), SR), 201)

    res = api_client.confirm_order(order["id"], SR)
    validate_error(res, "ERR_LABEL_NOT_APPROVED")


def test_order_confirm_succeeds_with_destination_market_label(api):
    """PRD section 3.6: "The label gates of §3.4 then apply to the product and
    the destination state's regulator market (`NY_SLA` for New York, `VT_DLL`
    for Vermont, `MA_ABCC` for Massachusetts): the approval must be `APPROVED`"
    PRD section 3.6: "Interstate orders — club or wholesale shipments crossing
    state lines — owe the federal rate, with destination-state excise treated
    as reciprocal under the `INTERSTATE_SHIPPER` permit."

    With a VT_DLL approval in place, the same club order confirms and carries
    the federal-only excise: round_half_up(5 * 0.500 * 22.6) = 57.

    Design: Difficulty/cross_entity_state_dependency/sales_order_confirm_requires_label_approved_for_market
    """
    ctx = setup_completed_packaging_run(volume_liters=50, target_abv_pct=5.0,
                                        extra_markets=["VT_DLL"])
    create_license(kind="INTERSTATE_SHIPPER", license_number="LIC-VT2",
                   scope_states=["VT", "NY"])
    order = validate_success(api_client.create_order(
        create_order_payload(ctx["product"]["id"], ctx["run"]["id"],
                             channel="CLUB_SUBSCRIPTION", destination_state="VT",
                             units=5, unit_price_cents=1500), SR), 201)

    confirmed = validate_success(api_client.confirm_order(order["id"], SR), 200)
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["subtotal_cents"] == 7500
    assert confirmed["excise_tax_cents"] == 57
    assert confirmed["total_cents"] == 7557


# ─── Corner: validations / endpoints ────────────────────────────────────────

def test_return_window_expired_after_30_days(api):
    """PRD section 3.6: "A `SHIPPED` order may be returned within 30 days of
    `shipped_at` — a later attempt is rejected with `ERR_RETURN_WINDOW_EXPIRED`"
    PRD section 3.6: "From `CONFIRMED`, shipping moves the order to `SHIPPED`
    and stamps `shipped_at` on the logical clock".

    The order ships at 2026-10-20 on the logical clock; a return attempted 31
    days later is rejected.

    Design: Corner/validations/return_window_expired_after_30_days
    """
    ctx = setup_completed_packaging_run(volume_liters=50, target_abv_pct=5.0,
                                        extra_markets=["NY_SLA"])
    shipped = _ship_order(ctx["product"]["id"], ctx["run"]["id"],
                          units=2, price=1000)
    assert shipped["status"] == "SHIPPED", "Setup failed: order not SHIPPED"
    assert shipped["shipped_at"] is not None

    set_clock("2026-11-20T12:00:00Z")  # 31 days past the 2026-10-20 ship date
    res = api_client.return_order(shipped["id"], SR)
    validate_error(res, "ERR_RETURN_WINDOW_EXPIRED")


def test_duplicate_excise_report_rejected(api):
    """PRD section 3.7: "Only one `OPEN` report may exist for a given year,
    month, and regulator — a duplicate is rejected with
    `ERR_DUPLICATE_REPORT`."

    Design: Corner/validations/duplicate_excise_report_rejected
    """
    validate_success(api_client.create_excise_report(
        create_excise_report_payload(period_year=2026, period_month=10,
                                     regulator="TTB"), CO), 201)
    res = api_client.create_excise_report(
        create_excise_report_payload(period_year=2026, period_month=10,
                                     regulator="TTB"), CO)
    validate_error(res, "ERR_DUPLICATE_REPORT")


def test_list_orders_filter_by_channel(api):
    """PRD section 3.6: "The order list filters by `status`, `channel`,
    `destination_state`, `product_id`, and `packaging_run_id`."

    With no orders created, the channel-filtered list returns an empty page.

    Design: Corner/endpoints/list_orders_filter_by_channel
    """
    data, meta = validate_paginated(api.list_orders(SR, params={"channel": "TASTING_ROOM"}))
    assert data == []
    assert meta["total_count"] == 0
