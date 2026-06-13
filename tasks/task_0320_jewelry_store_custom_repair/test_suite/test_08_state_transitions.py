"""Corner breadth tests — state_machines section: invalid transitions, terminal-state
lockdown, and per-transition precondition enforcement.

Translates queue-B corner instances under section `state_machines`.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    create_quoted_custom_order,
    create_design_review_custom_order,
    create_design_review_with_revisions,
    create_assessed_repair_ticket,
    drive_repair_ticket_to_picked_up_no_parts,
    create_submitted_warranty_claim,
    create_special_order,
    create_delivered_special_order_item,
    create_draft_appraisal,
    create_customer,
    ApiErrorId,
    TEST_USERS,
    api_client,
)

SA = TEST_USERS["sales_associate_headers"]
GS = TEST_USERS["goldsmith_headers"]
SM = TEST_USERS["store_manager_headers"]


def test_quote_already_quoted_order_returns_invalid_state(api):
    """PRD §3.3: "A sales associate quotes the order, transitioning `DRAFT → QUOTED` (legal
    only from `DRAFT`)."

    Design: Corner/state_machines/quote_from_already_quoted_returns_invalid_state
    """
    order, _ = create_quoted_custom_order(
        description="Ring", estimated_materials_cents=100000, design_fee_cents=0
    )
    res = api.quote_custom_order(order["id"], {"expected_version": order["version"]}, SA)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_cancel_picked_up_repair_ticket_returns_invalid_state(api):
    """PRD §3.4: "a manager may cancel a ticket from any of `INTAKE`, `ASSESSED`,
    `AWAITING_PARTS`, `IN_REPAIR`, or `QC` (cancellation is forbidden once the ticket is
    `READY`, `PICKED_UP`, or already `CANCELLED`, yielding `ERR_INVALID_STATE`)."

    Design: Corner/state_machines/cancel_repair_from_picked_up_terminal_returns_invalid_state
    """
    ticket, _ = drive_repair_ticket_to_picked_up_no_parts(0, 5000, repair_kind="POLISH")
    assert ticket["status"] == "PICKED_UP"
    res = api.cancel_repair_ticket(ticket["id"], {"expected_version": ticket["version"]}, SM)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_order_parts_with_zero_parts_returns_no_parts_needed(api):
    """PRD §3.4: "this branch is permitted only when `parts_cents` is greater than 0, and
    ordering parts on a ticket that needs none is rejected with `ERR_NO_PARTS_NEEDED`."

    Design: Corner/state_machines/order_parts_with_zero_parts_returns_no_parts_needed
    """
    ticket, _ = create_assessed_repair_ticket(0, 9000, repair_kind="POLISH")
    res = api.order_parts_repair_ticket(ticket["id"], {"expected_version": ticket["version"]}, GS)
    validate_error(res, ApiErrorId.ERR_NO_PARTS_NEEDED.value, expected_status=409)


def test_warranty_approve_without_finalized_appraisal_returns_no_coverage(api):
    """PRD §3.8: "Approving transitions `SUBMITTED → APPROVED` and additionally requires
    proof of coverage: the covered inventory item must have a `FINALIZED` appraisal on file,
    and a claim on an un-appraised piece is rejected with `ERR_NO_COVERAGE`."

    Design: Corner/state_machines/warranty_approve_without_finalized_appraisal_returns_no_coverage
    """
    claim, _, _ = create_submitted_warranty_claim(defect_description="Crack")
    res = api.approve_warranty_claim(claim["id"], {"expected_version": claim["version"]}, SM)
    validate_error(res, ApiErrorId.ERR_NO_COVERAGE.value, expected_status=409)


def test_request_revision_at_cap_returns_max_revisions_reached(api):
    """PRD §3.3: "The loop is capped at 3 revisions: a revision request is permitted only
    while `revision_count` is below 3, so the fourth request — made when `revision_count`
    already equals 3 — is rejected with `ERR_MAX_REVISIONS_REACHED`."

    Design: Corner/state_machines/max_revisions_reached_returns_error
    """
    # Drive through 3 revision loops -> revision_count == 3, back in DESIGN_REVIEW.
    order, _ = create_design_review_with_revisions(
        3, deposit_cents=36000, description="Ring",
        estimated_materials_cents=100000, design_fee_cents=0,
    )
    assert order["revision_count"] == 3
    res = api.request_revision_custom_order(order["id"], {"expected_version": order["version"]}, SA)
    validate_error(res, ApiErrorId.ERR_MAX_REVISIONS_REACHED.value, expected_status=409)


def test_approve_design_empty_line_items_returns_error(api):
    """PRD §3.3: "The line items must be non-empty; an approval with empty line items is
    rejected with `ERR_LINE_ITEMS_REQUIRED`."

    Design: Corner/state_machines/approve_design_empty_line_items_returns_error
    """
    order, _ = create_design_review_custom_order(
        deposit_cents=36000, description="Ring",
        estimated_materials_cents=100000, design_fee_cents=0,
    )
    res = api.approve_design_custom_order(
        order["id"], {"line_items": [], "expected_version": order["version"]}, SA
    )
    validate_error(res, ApiErrorId.ERR_LINE_ITEMS_REQUIRED.value, expected_status=422)


def test_special_order_place_without_deposit_returns_deposit_required(api):
    """PRD §3.7: "Placing is legal only from `REQUESTED` and additionally requires that the
    deposit be satisfied — `deposit_paid_cents` must be at least `deposit_required_cents`; an
    under-funded order is rejected with `ERR_DEPOSIT_REQUIRED`."

    Design: Corner/state_machines/special_order_place_without_deposit_returns_deposit_required
    """
    order, _ = create_special_order(
        vendor_name="Acme", catalog_ref="C-1", quoted_price_cents=400000
    )
    res = api.place_special_order(order["id"], {"expected_version": order["version"]}, SA)
    validate_error(res, ApiErrorId.ERR_DEPOSIT_REQUIRED.value, expected_status=402)


def test_finalize_appraisal_on_sold_item_returns_item_sold(api):
    """PRD §3.2: "It additionally requires that the referenced inventory item is not `SOLD` —
    a sold piece can no longer be appraised for the store, and the attempt fails with
    `ERR_ITEM_SOLD`."

    Design: Corner/state_machines/appraisal_finalize_on_sold_item_returns_item_sold
    """
    # Create a SOLD item via a delivered special order, then book a DRAFT appraisal on it.
    _, sold_item_id = create_delivered_special_order_item(quoted_price_cents=300000, sku="SO-RCV")
    appraisal, _ = create_draft_appraisal(
        inventory_item_id=sold_item_id, appraiser_name="GIA-SOLD",
        appointment_start="2026-06-03T09:00:00Z", appointment_end="2026-06-03T09:30:00Z",
        market_value_cents=300000,
    )
    item = validate_success(api.get_inventory_item(sold_item_id, SM), 200)
    res = api.finalize_appraisal(
        appraisal["id"], {"expected_inventory_item_version": item["version"]}, SM
    )
    validate_error(res, ApiErrorId.ERR_ITEM_SOLD.value, expected_status=409)
