"""Corner breadth tests — validations section: payment-target consistency,
range validation, and existence-before-state ordering.

Translates queue-B corner instances under section `validations`.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    create_customer,
    create_inventory_item,
    create_active_layaway_plan,
    create_quoted_custom_order,
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    api_client,
)
from test_helpers.factories import create_layaway_plan_payload

SA = TEST_USERS["sales_associate_headers"]
GS = TEST_USERS["goldsmith_headers"]
SM = TEST_USERS["store_manager_headers"]


def test_payment_target_mismatch_returns_error(api):
    """PRD §3.9: "Exactly the one foreign key matching `target_type` must be present and must
    reference an existing parent, and the other two must be absent; any other combination —
    wrong key populated, multiple keys populated, or the named parent missing — is rejected
    with `ERR_PAYMENT_TARGET_MISMATCH`."

    Design: Corner/validations/payment_target_mismatch_returns_error
    """
    # An ACTIVE layaway plan and a QUOTED custom order both exist.
    plan, customer_id, _ = create_active_layaway_plan(item_price_cents=200000, installment_count=4)
    order, _ = create_quoted_custom_order(
        customer_id=customer_id, description="Ring",
        estimated_materials_cents=100000, design_fee_cents=0,
    )
    # target_type=CUSTOM_ORDER but layaway_plan_id is also populated -> mismatch.
    res = api.create_payment(
        {"target_type": "CUSTOM_ORDER", "custom_order_id": order["id"],
         "layaway_plan_id": plan["id"], "amount_cents": 1000},
        SA,
    )
    validate_error(res, ApiErrorId.ERR_PAYMENT_TARGET_MISMATCH.value, expected_status=422)


def test_installment_count_out_of_range_returns_invalid_request(api):
    """PRD §3.5: "an `installment_count` that must be an integer from 2 to 24 inclusive."
    PRD §2.8: "then request-body well-formedness (`ERR_INVALID_REQUEST`, HTTP 422 — required
    fields present, enum values legal, integers within their declared ranges)".

    Design: Corner/validations/installment_count_out_of_range_returns_invalid_request
    """
    customer = create_customer(full_name="Bad Inst", email="bi@x.com", phone="555-1020")
    item = create_inventory_item(sku="BAD-INST", title="Ring", metal_karat="K18",
                                 list_price_cents=200000)
    res = api.create_layaway_plan(
        create_layaway_plan_payload(customer["id"], item["id"], installment_count=1), SA
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value, expected_status=422)


def test_existence_checked_before_state_on_unknown_repair_ticket(api):
    """PRD §2.8: "The system validates each request through a fixed priority pipeline; an
    earlier failing check determines the error and later checks are not reached."
    PRD §2.5: "that identifier is resolved first; if it names no existing record, the request
    fails with `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/validations/existence_path_before_state_repair_assess_unknown_id
    """
    res = api.assess_repair_ticket(
        NON_EXISTENT_UUID,
        {"parts_cents": 1000, "labor_cents": 1000, "expected_version": 1},
        GS,
    )
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value, expected_status=404)
