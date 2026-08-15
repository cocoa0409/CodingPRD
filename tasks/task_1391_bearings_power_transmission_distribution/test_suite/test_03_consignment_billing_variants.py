"""Consignment consumption billing: CONSUMPTION_FIFO vs MONTHLY_SNAPSHOT."""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_product, create_branch, create_customer, create_branch_stock,
    create_agreement, report_consumption, invoice_consumption,
    publish_price_file, set_clock, get_agreement, get_customer,
    make_customer_plant_headers,
    ApiErrorId, TEST_USERS,
)

ADMIN = TEST_USERS["system_admin_headers"]
MANAGER = TEST_USERS["branch_manager_headers"]


def _setup_dual_variant_agreements():
    """PA/PB list 4000; A1 FIFO (pinned 4000), A2 MONTHLY_SNAPSHOT (pinned 4000);
    both products 4000->5000 EFFECTIVE 2026-08-20; qty-3 consumptions at 08-22."""
    set_clock("2026-08-05T10:00:00Z")
    pa = create_product(sku="BRG-6308", list_price_cents=4000)
    pb = create_product(sku="BRG-6410", list_price_cents=4000)
    branch = create_branch(code="DAL-02")
    customer = create_customer(name="Lone Star Plant")
    create_branch_stock(branch["id"], pa["id"], on_hand_qty=500)
    create_branch_stock(branch["id"], pb["id"], on_hand_qty=500)
    a1 = create_agreement(customer["id"], branch["id"], pa["id"],
                          consigned_qty=10, billing_variant="CONSUMPTION_FIFO")
    a2 = create_agreement(customer["id"], branch["id"], pb["id"],
                          consigned_qty=10, billing_variant="MONTHLY_SNAPSHOT")
    publish_price_file(pa["id"], 5000, "2026-08-20T00:00:00Z")
    publish_price_file(pb["id"], 5000, "2026-08-20T00:00:00Z")
    set_clock("2026-08-22T10:00:00Z")
    cons1 = report_consumption(a1["id"], 3, customer["id"])
    cons2 = report_consumption(a2["id"], 3, customer["id"])
    return {"pa": pa, "pb": pb, "branch": branch, "customer": customer,
            "a1": a1, "a2": a2, "cons1": cons1, "cons2": cons2}


def test_consumption_fifo_bills_agreement_pinned_price(api):
    """PRD §3.5: "Under `CONSUMPTION_FIFO`, `unit_price_cents` is the
    agreement's `pinned_unit_price_cents` — the price at agreement creation —
    and later list changes never affect it."

    Design: Difficulty/dual_variant_calc/consignment_fifo_vs_monthly_snapshot_billing
    """
    ctx = _setup_dual_variant_agreements()
    invoiced = validate_success(
        api.invoice_consumption(ctx["cons1"]["id"], MANAGER), 200)
    assert invoiced["unit_price_cents"] == 4000, (
        f"FIFO bills the agreement-pinned 4000; got {invoiced['unit_price_cents']}")
    assert invoiced["billed_amount_cents"] == 12000
    agreement = get_agreement(ctx["a1"]["id"])
    assert agreement["remaining_qty"] == 7, (
        f"10 consigned - 3 consumed = 7 remaining; got {agreement['remaining_qty']}")


def test_monthly_snapshot_bills_list_price_at_report_month_end(api):
    """PRD §3.5: "Under `MONTHLY_SNAPSHOT`, the unit price is the list price
    effective at the last instant of the UTC calendar month containing
    `reported_at`, found via the price-file history (the `EFFECTIVE` file with
    the greatest `effective_at` not after month-end, else the product's creation
    list price); a mid-month price increase between agreement creation and
    month-end therefore yields a different billed amount than `CONSUMPTION_FIFO`
    for identical consumption data."
    PRD §3.5: "the consumption moves to `INVOICED`, and the customer's
    `open_receivables_cents` grows by the billed amount."

    Design: Difficulty/dual_variant_calc/consignment_fifo_vs_monthly_snapshot_billing
    """
    ctx = _setup_dual_variant_agreements()
    invoice_consumption(ctx["cons1"]["id"])
    invoiced2 = validate_success(
        api.invoice_consumption(ctx["cons2"]["id"], MANAGER), 200)
    assert invoiced2["unit_price_cents"] == 5000, (
        f"SNAPSHOT bills the list price effective at 2026-08-31 month-end "
        f"(5000 EFFECTIVE since 08-20); got {invoiced2['unit_price_cents']}")
    assert invoiced2["billed_amount_cents"] == 15000
    customer = get_customer(ctx["customer"]["id"])
    assert customer["open_receivables_cents"] == 27000, (
        f"12000 FIFO + 15000 SNAPSHOT = 27000; got {customer['open_receivables_cents']}")
    assert get_agreement(ctx["a2"]["id"])["remaining_qty"] == 7


def test_snapshot_billing_anchors_report_month_end_not_invoice_date(api):
    """PRD §3.5: "Under `MONTHLY_SNAPSHOT`, the unit price is the list price
    effective at the last instant of the UTC calendar month containing
    `reported_at`, found via the price-file history (the `EFFECTIVE` file with
    the greatest `effective_at` not after month-end, else the product's creation
    list price)".

    Design: Corner/calculations/snapshot_billing_anchors_report_month_end_not_invoice_date
    """
    set_clock("2026-08-05T10:00:00Z")
    product = create_product(sku="BRG-6023", list_price_cents=4000)
    branch = create_branch(code="SNP-13")
    customer = create_customer(name="Snapshot Plant")
    create_branch_stock(branch["id"], product["id"], on_hand_qty=50)
    agreement = create_agreement(customer["id"], branch["id"], product["id"],
                                 consigned_qty=10, billing_variant="MONTHLY_SNAPSHOT")
    publish_price_file(product["id"], 5000, "2026-09-01T00:00:00Z")
    set_clock("2026-08-22T10:00:00Z")
    consumption = report_consumption(agreement["id"], 3, customer["id"])
    set_clock("2026-09-05T10:00:00Z")  # price file now EFFECTIVE
    invoiced = validate_success(
        api.invoice_consumption(consumption["id"], MANAGER), 200)
    assert invoiced["unit_price_cents"] == 4000, (
        f"month-end of report month (2026-08-31) predates the 2026-09-01 "
        f"increase; expected 4000, got {invoiced['unit_price_cents']}")
    assert invoiced["billed_amount_cents"] == 12000
