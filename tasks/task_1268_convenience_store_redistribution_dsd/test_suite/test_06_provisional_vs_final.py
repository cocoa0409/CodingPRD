"""Dual-variant invoice totals and credit exposure variants."""
import pytest

from test_helpers import (
    ADMIN,
    CREDIT,
    DRIVER,
    api_client,
    assign_order_to_manifest,
    begin_loading,
    close_manifest,
    create_delivery_exception_payload,
    get_order_line_id_for_product,
    get_success_data,
    publish_fuel_rate,
    setup_canonical_submitted_promoted_order,
    setup_manifest,
    validate_success,
)


def _drive_through_close(base, fuel_doe=3.75):
    manifest = setup_manifest()
    publish_fuel_rate(week_start_date="2026-05-25", doe_index_usd=fuel_doe)
    manifest = assign_order_to_manifest(manifest, base["order"])
    manifest = begin_loading(manifest)
    manifest = close_manifest(manifest)
    base["manifest"] = manifest
    base["order"] = get_success_data(api_client.get_purchase_order(base["order"]["id"], ADMIN))
    return base


def test_provisional_vs_final_invoice_totals(api, route_driver_headers, credit_manager_headers):
    """PRD §3.4: "The order's `provisional_total_cents` is then the merchandise
    subtotal minus the promo allowance, plus the pick fee, plus the minimum-drop
    fee, plus the tax-stamp cost; the fuel surcharge is excluded at submission
    because the rate week is not yet locked."
    PRD §3.6: "The order's `final_total_cents` is then computed on delivered
    quantities: delivered merchandise less delivered promo allowances — the
    same per-line half-up rounding rule applied to delivered line amounts —
    plus delivered pick fees, plus the tax-stamp cost carried unchanged from
    submission, plus the fuel surcharge stamped at manifest close."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_invoice_totals
    """
    base = setup_canonical_submitted_promoted_order()
    # Provisional: 63000 merch - 6000 promo + 1500 pick + 0 min-drop + 0 stamp
    assert base["order"]["provisional_total_cents"] == 58500
    _drive_through_close(base, fuel_doe=3.75)
    # Short 2 cases of P1 (line) BEFORE confirm
    p1_id = base["products"]["P1"]["id"]
    line_id = get_order_line_id_for_product(base["order"]["id"], p1_id, headers=ADMIN)
    get_success_data(api_client.create_delivery_exception(
        base["manifest"]["id"],
        create_delivery_exception_payload(
            order_id=base["order"]["id"],
            order_line_id=line_id,
            exception_type="SHORT",
            cases_qty=2,
            split_units_qty=0,
        ),
        route_driver_headers,
    ))
    resp = api_client.confirm_delivery(base["order"]["id"], route_driver_headers)
    invoice = validate_success(resp)
    # final: 48*1200 + 20*150 = 60600 merch; promo = round(57600*0.10) + round(3000*0)=5760
    # wait — promo applies to P1 only. P1 delivered merch = 48*1200=57600; promo = 5760.
    # Q1 line: no promo. pick = 48*12 + 20*45 = 576+900 = 1476. surcharge = 1463.
    # final = 60600 - 5760 + 1476 + 0 + 1463 = 57779
    assert invoice["invoiced_total_cents"] == 57779
    assert invoice["balance_cents"] == 57779
    assert base["order"]["provisional_total_cents"] != invoice["invoiced_total_cents"]


def test_provisional_excludes_fuel_surcharge(api):
    """PRD §3.4: "the fuel surcharge is excluded at submission because the rate
    week is not yet locked." The provisional total of the canonical promoted
    order is 58500 = 63000 - 6000 + 1500 + 0 + 0 with no fuel term.

    Design: Difficulty/dual_variant_calc/provisional_vs_final_invoice_totals
    """
    base = setup_canonical_submitted_promoted_order()
    order = base["order"]
    assert order["merch_subtotal_cents"] == 63000
    assert order["promo_allowance_cents"] == 6000
    assert order["pick_fee_cents"] == 1500
    assert order["min_drop_fee_cents"] == 0
    assert order["tax_stamp_cost_cents"] == 0
    assert order["provisional_total_cents"] == 58500


def test_forward_vs_aging_credit_exposure(api, credit_manager_headers):
    """PRD §2.9: "The `exposure_forward_cents` figure is forward-looking: it
    equals `ar_balance_cents` plus the sum of `provisional_total_cents` over
    all of the retailer's purchase orders in `SUBMITTED`, `ASSIGNED`, or
    `CLOSED` status — the pipeline of orders priced but not yet invoiced."
    PRD §2.9: "Alongside the forward figure, the system maintains a
    chronological accounts-receivable aging view used for reporting and
    past-due handling: invoice balances in `OPEN`, `PARTIALLY_PAID`, or
    `PAST_DUE`".

    Design: Difficulty/dual_variant_calc/forward_vs_aging_credit_exposure
    """
    base = setup_canonical_submitted_promoted_order()
    resp = api_client.get_credit_summary(base["retailer"]["id"], credit_manager_headers)
    data = validate_success(resp)
    assert data["exposure_forward_cents"] == 58500
    assert data["exposure_aging_current_cents"] == 0
    assert data["ar_balance_cents"] == 0


def test_forward_exposure_drops_after_invoice(api, credit_manager_headers, route_driver_headers):
    """PRD §2.9: "Pipeline orders enter the forward figure at submission and
    leave it when their invoice is created."

    Design: Difficulty/dual_variant_calc/forward_vs_aging_credit_exposure
    """
    base = setup_canonical_submitted_promoted_order()
    _drive_through_close(base, fuel_doe=3.75)
    get_success_data(api_client.confirm_delivery(base["order"]["id"], route_driver_headers))
    resp = api_client.get_credit_summary(base["retailer"]["id"], credit_manager_headers)
    data = validate_success(resp)
    # After invoicing: the order has left the pipeline; ar_balance = final total
    # = 63000 - 6000 + 1500 + 0 + 1463 = 59963; exposure_forward = ar + 0 = 59963.
    assert data["ar_balance_cents"] == 59963
    assert data["exposure_forward_cents"] == 59963
