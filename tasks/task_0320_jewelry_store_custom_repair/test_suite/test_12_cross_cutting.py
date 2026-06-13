"""Corner breadth tests — cross_cutting_complexity_layers and consistency_model:
optimistic concurrency (stale and missing version), derived-field reconciliation,
and immediate consistency.

Translates queue-B corner instances under sections
`cross_cutting_complexity_layers` and `consistency_model`.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    create_inventory_item,
    create_customer,
    create_layaway_plan,
    create_quoted_custom_order,
    post_ledger_entry,
    ApiErrorId,
    TEST_USERS,
    api_client,
)
from test_helpers.factories import create_custom_order_payload

SA = TEST_USERS["sales_associate_headers"]
SM = TEST_USERS["store_manager_headers"]


def test_occ_stale_version_on_appraisal_finalize_returns_412(api):
    """PRD §2.7: "If another writer has finalized a competing appraisal — legitimately
    becoming the item's latest replacement value and advancing the item's `version` — since
    the client last read the item, the finalize is rejected with `ERR_STALE_VERSION`
    (HTTP 412), because this writer's view of the item is stale."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_on_appraisal_finalize_returns_412
    """
    item = create_inventory_item(sku="OCC-1", title="Ring", metal_karat="K18",
                                 list_price_cents=500000)
    item_v0 = item["version"]
    apr_a = validate_success(
        api.create_appraisal(
            {"inventory_item_id": item["id"], "appraiser_name": "OCC-A",
             "appointment_start": "2026-06-07T09:00:00Z",
             "appointment_end": "2026-06-07T09:30:00Z", "market_value_cents": 500000},
            SM,
        ),
        201,
    )
    apr_b = validate_success(
        api.create_appraisal(
            {"inventory_item_id": item["id"], "appraiser_name": "OCC-B",
             "appointment_start": "2026-06-07T11:00:00Z",
             "appointment_end": "2026-06-07T11:30:00Z", "market_value_cents": 520000},
            SM,
        ),
        201,
    )
    # A finalizes against v0 (succeeds, bumps the item version).
    validate_success(
        api.finalize_appraisal(apr_a["id"], {"expected_inventory_item_version": item_v0}, SM), 200
    )
    # B finalizes against the now-stale v0 -> 412.
    res = api.finalize_appraisal(apr_b["id"], {"expected_inventory_item_version": item_v0}, SM)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)


def test_occ_version_required_missing_on_quote_returns_422(api):
    """PRD §2.7: "If a mutation that requires a version field omits it entirely, the request
    fails with `ERR_VERSION_REQUIRED` (HTTP 422)."
    PRD §3.3: "Quoting requires the order's `expected_version`."

    Design: Corner/cross_cutting_complexity_layers/occ_version_required_missing_on_quote_returns_422
    """
    customer = create_customer(full_name="Ver Req", email="vr@x.com", phone="555-1025")
    order = validate_success(
        api.create_custom_order(
            create_custom_order_payload(customer["id"], description="Ring",
                                        estimated_materials_cents=100000, design_fee_cents=0),
            SA,
        ),
        201,
    )
    res = api.quote_custom_order(order["id"], {}, SA)
    validate_error(res, ApiErrorId.ERR_VERSION_REQUIRED.value, expected_status=422)


def test_derived_field_deposit_paid_reconciles_and_auto_advances(api):
    """PRD §3.3: "The moment that accumulated deposit reaches or exceeds
    `deposit_required_cents`, the system itself advances the order `QUOTED → DEPOSIT_PAID`
    and refreshes `deposit_paid_cents` and `balance_due_cents`; no explicit call drives this
    transition."

    Design: Corner/cross_cutting_complexity_layers/derived_field_deposit_paid_reconciles_after_payment
    """
    # est 200000 marked up 20% = 240000 + fee 50000 = 290000 provisional; deposit 30% = 87000.
    # The design index pays 90000 (>= deposit_required) to trigger the advance.
    order, _ = create_quoted_custom_order(
        description="Ring", estimated_materials_cents=200000, design_fee_cents=50000
    )
    validate_success(
        api.create_payment(
            {"target_type": "CUSTOM_ORDER", "custom_order_id": order["id"], "amount_cents": 90000},
            SA,
        ),
        201,
    )
    order_after = validate_success(api.get_custom_order(order["id"], SA), 200)
    assert order_after["deposit_paid_cents"] == 90000
    assert order_after["status"] == "DEPOSIT_PAID"


def test_immediate_consistency_balance_visible_same_request(api):
    """PRD §2.9: "The balance starts at 0 for a new customer and is recomputed from the full
    ledger on every ledger write".
    PRD §3.1: "the fetch returns the freshly computed store-credit balance."

    Design: Corner/consistency_model/immediate_consistency_balance_visible_same_request
    """
    customer = create_customer(full_name="Imm Diate", email="id2@x.com", phone="555-1027")
    post_ledger_entry(customer["id"], "CREDIT", 25000, reason="MANUAL_ADJUSTMENT")
    customer_after = validate_success(api.get_customer(customer["id"], SA), 200)
    assert customer_after["store_credit_balance_cents"] == 25000
