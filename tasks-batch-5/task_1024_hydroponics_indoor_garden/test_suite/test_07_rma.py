"""Warranty returns (RMA): the review/info cyclic state machine, approval restock
that clears the reorder flag, invalid-transition lockdown, and the out-of-warranty
restocking-fee refund."""
import pytest

from test_helpers import (
    validate_success, validate_error, api_client,
    setup_rma_under_review, setup_shipped_retail_order, submit_rma,
    request_info_rma, provide_info_rma, approve_rma, set_clock,
    TEST_USERS,
)

ADMIN = TEST_USERS["store_admin_headers"]


# ─── Difficulty: non_linear_state_machine / review↔info cycle ──────────────
def test_provide_info_returns_to_under_review(api):
    """PRD §3.9: "From `UNDER_REVIEW` the administrator may request more
    information (optionally attaching a `note`), moving it
    `UNDER_REVIEW → INFO_REQUESTED`; the `Customer` then provides the requested
    information (again with an optional `note`), moving it
    `INFO_REQUESTED → UNDER_REVIEW`."

    Design: Difficulty/non_linear_state_machine/rma_review_info_cycle
    """
    customer, product, order, rma = setup_rma_under_review(warranty_months=12)
    request_info_rma(rma["id"])
    provided = provide_info_rma(rma["id"], customer["id"])
    assert provided["status"] == "UNDER_REVIEW"


def test_request_info_provide_info_cycle_repeats(api):
    """PRD §3.9: "This request-info/provide-info cycle may repeat any number of
    times."

    Design: Difficulty/non_linear_state_machine/rma_review_info_cycle
    """
    customer, product, order, rma = setup_rma_under_review(warranty_months=12)
    request_info_rma(rma["id"])
    provide_info_rma(rma["id"], customer["id"])
    request_info_rma(rma["id"])
    provided = provide_info_rma(rma["id"], customer["id"])
    assert provided["status"] == "UNDER_REVIEW"


# ─── Difficulty: transitive_cascade / approve restock clears reorder ───────
def _setup_rma_ready_for_restock():
    return setup_rma_under_review(
        quantity=3, stock=5, return_quantity=3,
        sku_code="LGT-2", name="Bar Light", category="LIGHTING",
        unit_price_cents=10000, warranty_months=12, reorder_threshold=4,
    )


def test_approve_within_warranty_full_refund(api):
    """PRD §3.9: "At approval the system sets `within_warranty` by testing whether
    the current logical-clock time is on or before the order's `shipped_at` plus
    the product's `warranty_months` times 30 days; a return at exactly that
    boundary instant still counts as within warranty."

    Design: Difficulty/transitive_cascade/rma_approve_restock_clears_reorder
    """
    customer, product, order, rma = _setup_rma_ready_for_restock()
    approved = approve_rma(rma["id"])
    assert approved["status"] == "APPROVED"
    assert approved["within_warranty"] is True


def test_approve_restock_clears_reorder_flag(api):
    """PRD §3.9: "Approval also restocks the goods by creating a new inventory lot
    on the returned `product_id` with `quantity_on_hand` equal to the
    `return_quantity` and `status` `ACTIVE`; the product then recomputes
    `total_available_units`, and if that rises back to or above the
    `reorder_threshold`, its `reorder_flag` flips to false."

    Design: Difficulty/transitive_cascade/rma_approve_restock_clears_reorder
    """
    customer, product, order, rma = _setup_rma_ready_for_restock()
    approve_rma(rma["id"])
    refetched = validate_success(api.get_product(product["id"], ADMIN))
    assert refetched["total_available_units"] == 5
    assert refetched["reorder_flag"] is False


# ─── Corner: state_machines / approve from SUBMITTED invalid ───────────────
def test_approve_submitted_rma_rejected(api):
    """PRD §3.9: "From `UNDER_REVIEW` the administrator ultimately either approves
    the RMA or rejects it (optionally with a `note`), and both `APPROVED` and
    `REJECTED` are terminal. Any of these transitions attempted from a state that
    does not permit it is rejected with `ERR_INVALID_STATE`."

    Design: Corner/state_machines/rma_approve_from_submitted_returns_invalid_state
    """
    customer, product, order = setup_shipped_retail_order(
        quantity=1, stock=20, sku_code="LGT-3", name="COB", category="LIGHTING",
        unit_price_cents=9000, warranty_months=12,
    )
    rma = submit_rma(order["id"], product["id"], 1, customer["id"], reason="dim")
    res = api.approve_rma(rma["id"], ADMIN)
    validate_error(res, "ERR_INVALID_STATE")


# ─── Corner: calculations / out-of-warranty restocking fee ─────────────────
def test_out_of_warranty_refund_applies_restock_fee(api):
    """PRD §3.9: "if the return is within warranty the refund is that full base
    value, while if it is out of warranty the refund is the base value reduced by a
    15 percent restocking fee — that is, 85 percent of the base — rounded half up
    to whole cents."

    Design: Corner/calculations/rma_refund_restock_fee_out_of_warranty
    """
    customer, product, order = setup_shipped_retail_order(
        quantity=2, stock=20, sku_code="ACC-3", name="Timer", category="ACCESSORY",
        unit_price_cents=10000, warranty_months=0,
    )
    set_clock("2026-08-01T00:00:00Z")
    rma = submit_rma(order["id"], product["id"], 2, customer["id"], reason="changed mind")
    from test_helpers import review_rma
    review_rma(rma["id"])
    approved = approve_rma(rma["id"])
    assert approved["within_warranty"] is False
    assert approved["refund_cents"] == 17000
