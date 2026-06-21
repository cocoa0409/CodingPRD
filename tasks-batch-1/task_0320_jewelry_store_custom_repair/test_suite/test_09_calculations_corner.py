"""Corner breadth tests — calculations section: replacement value, latest-appraised
value, store-credit balance, repair totals, and layaway installment sizing.

Translates queue-B corner instances under section `calculations`.
"""
import pytest
from test_helpers import (
    validate_success,
    create_inventory_item,
    create_customer,
    create_assessed_repair_ticket,
    create_layaway_plan,
    post_ledger_entry,
    TEST_USERS,
    api_client,
)

SA = TEST_USERS["sales_associate_headers"]
GS = TEST_USERS["goldsmith_headers"]
SM = TEST_USERS["store_manager_headers"]


def test_replacement_value_default_factor(api):
    """PRD §3.2: "its `replacement_value_cents` is computed as the `market_value_cents`
    multiplied by the `replacement_factor`, rounded half up to whole cents."
    PRD §3.2: "The replacement factor is a multiplier in the range 1.00 to 2.00 inclusive;
    when omitted it defaults to 1.30."

    Design: Corner/calculations/insurance_replacement_value_default_factor
    """
    item = create_inventory_item(sku="REPL-1", title="Ring", metal_karat="K18",
                                 list_price_cents=1000000)
    appraisal = validate_success(
        api.create_appraisal(
            {"inventory_item_id": item["id"], "appraiser_name": "GIA-R",
             "appointment_start": "2026-06-04T09:00:00Z",
             "appointment_end": "2026-06-04T09:30:00Z", "market_value_cents": 1000000},
            SM,
        ),
        201,
    )
    assert appraisal["replacement_value_cents"] == 1300000


def test_replacement_value_custom_factor(api):
    """PRD §3.2: "its `replacement_value_cents` is computed as the `market_value_cents`
    multiplied by the `replacement_factor`, rounded half up to whole cents."

    Design: Corner/calculations/insurance_replacement_value_custom_factor
    """
    item = create_inventory_item(sku="REPL-2", title="Ring", metal_karat="K18",
                                 list_price_cents=800000)
    appraisal = validate_success(
        api.create_appraisal(
            {"inventory_item_id": item["id"], "appraiser_name": "GIA-R2",
             "appointment_start": "2026-06-05T09:00:00Z",
             "appointment_end": "2026-06-05T09:30:00Z", "market_value_cents": 800000,
             "replacement_factor": 1.50},
            SM,
        ),
        201,
    )
    assert appraisal["replacement_value_cents"] == 1200000


def test_finalize_sets_item_latest_appraised_value(api):
    """PRD §3.2: "On success the system assigns the `document_number` as the string `APR-`
    followed by the next zero-padded sequential number for the store, recomputes the item's
    `latest_appraised_value_cents`".
    PRD §3.2: "The item's `latest_appraised_value_cents` is defined as the
    `replacement_value_cents` of the item's most recent `FINALIZED` appraisal".

    Design: Corner/calculations/finalize_sets_item_latest_appraised_value
    """
    item = create_inventory_item(sku="REPL-3", title="Ring", metal_karat="K18",
                                 list_price_cents=1000000)
    appraisal = validate_success(
        api.create_appraisal(
            {"inventory_item_id": item["id"], "appraiser_name": "GIA-R3",
             "appointment_start": "2026-06-06T09:00:00Z",
             "appointment_end": "2026-06-06T09:30:00Z", "market_value_cents": 1000000},
            SM,
        ),
        201,
    )
    finalized = validate_success(
        api.finalize_appraisal(
            appraisal["id"], {"expected_inventory_item_version": item["version"]}, SM
        ),
        200,
    )
    assert finalized["status"] == "FINALIZED"
    item_after = validate_success(api.get_inventory_item(item["id"], SM), 200)
    assert item_after["latest_appraised_value_cents"] == 1300000


def test_store_credit_balance_credit_minus_debit(api):
    """PRD §2.9: "which is defined as the exact sum of `amount_cents` over every
    `CreditLedgerEntry` for that customer whose `direction` is `CREDIT`, minus the exact sum
    of `amount_cents` over every entry whose `direction` is `DEBIT`."

    Design: Corner/calculations/store_credit_balance_credit_minus_debit
    """
    customer = create_customer(full_name="Led Ger", email="lg@x.com", phone="555-1015")
    post_ledger_entry(customer["id"], "CREDIT", 153000, reason="MANUAL_ADJUSTMENT")
    post_ledger_entry(customer["id"], "DEBIT", 50000, reason="PURCHASE")
    customer_after = validate_success(api.get_customer(customer["id"], SM), 200)
    assert customer_after["store_credit_balance_cents"] == 103000


def test_repair_total_no_rush_zero_surcharge(api):
    """PRD §3.4: "For a non-warranty ticket, if `rush` is false the `rush_surcharge_cents`
    is 0".
    PRD §3.4: "the `total_cents` is the subtotal plus the surcharge."

    Design: Corner/calculations/repair_total_no_rush_zero_surcharge
    """
    ticket, _ = create_assessed_repair_ticket(8000, 15000, repair_kind="CLASP_REPAIR", rush=False)
    assert ticket["rush_surcharge_cents"] == 0
    assert ticket["total_cents"] == 23000


def test_repair_rush_tier_boundary_50001_high(api):
    """PRD §3.4: "and 30 percent when the subtotal exceeds 50000 cents (so a subtotal of
    exactly 50000 cents takes the 20-percent tier, and 50001 cents takes the 30-percent
    tier)."

    Design: Corner/calculations/repair_rush_tier_boundary_50001_high
    """
    ticket, _ = create_assessed_repair_ticket(20001, 30000, repair_kind="STONE_RESET", rush=True)
    assert ticket["rush_surcharge_cents"] == 15000
    assert ticket["total_cents"] == 65001


def test_layaway_installment_amount_floor_with_remainder(api):
    """PRD §3.5: "The `down_payment_cents` is 20 percent of the snapshot price, rounded half
    up. The remaining amount after the down payment is divided by the `installment_count`
    using floor (truncation) to give the `installment_amount_cents`, with the final
    installment absorbing any remainder so the schedule collects exactly the snapshot price."

    Design: Corner/calculations/layaway_installment_amount_floor_with_remainder
    """
    plan, _, item = create_layaway_plan(item_price_cents=600000, installment_count=6)
    activated = validate_success(
        api.activate_layaway_plan(
            plan["id"], {"expected_inventory_item_version": item["version"]}, SA
        ),
        200,
    )
    assert activated["down_payment_cents"] == 120000
    assert activated["installment_amount_cents"] == 80000
