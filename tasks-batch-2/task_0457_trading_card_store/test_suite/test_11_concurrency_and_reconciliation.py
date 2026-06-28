"""Optimistic-concurrency on release allocation (success increments version, stale
version rejected) and derived-field reconciliation (pre-order deposit debits store
credit through an append-only ledger row).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_customer, create_release_product, create_requested_pre_order,
    create_pre_order_payload,
    ApiErrorId, TEST_USERS, make_customer_headers,
)

SM = TEST_USERS["store_manager_headers"]


def test_allocate_with_correct_version_succeeds_and_bumps_version(api):
    """PRD §2.7: "A request to allocate a pre-order must carry
    `expected_release_product_version`, a non-optional field whose value is the
    `version` of the target `ReleaseProduct` that the client last observed."
    PRD §3.3: "When allocation succeeds, the pre-order moves to `ALLOCATED`, the
    release's `quantity_allocated` increases by the requested quantity, and the
    release product's `version` increments by one."

    Design: Corner/cross_cutting_complexity_layers/occ_allocate_success_increments_version
    """
    cust = create_customer("OCC OK", "occok@x.com", credit_cents=5000)
    rp = create_release_product(title="OCC Box", allocation_pool=10,
                                unit_price_cents=1000, deposit_required_cents=500)
    v0 = rp["version"]
    po = create_requested_pre_order(cust, rp, requested_quantity=2, deposit_paid_cents=500)
    allocated = validate_success(
        api.allocate_pre_order(po["id"], {"expected_release_product_version": v0}, SM),
        200)
    assert allocated["status"] == "ALLOCATED"
    rp_after = validate_success(api.get_release_product(rp["id"], SM), 200)
    assert rp_after["quantity_allocated"] == 2
    assert rp_after["version"] == v0 + 1


def test_allocate_with_stale_version_rejected(api):
    """PRD §2.7: "If that value does not equal the release product's current
    `version` — which happens when another writer has allocated against the same
    release product since the client last read it, advancing its version — the
    allocation is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_allocate_stale_version_conflict
    """
    ca = create_customer("OCC A", "occa@x.com", credit_cents=5000)
    cb = create_customer("OCC B", "occb@x.com", credit_cents=5000)
    rp = create_release_product(title="Stale Box", allocation_pool=10,
                                unit_price_cents=1000, deposit_required_cents=500)
    v0 = rp["version"]
    po_a = create_requested_pre_order(ca, rp, requested_quantity=1, deposit_paid_cents=500)
    po_b = create_requested_pre_order(cb, rp, requested_quantity=1, deposit_paid_cents=500)
    # First allocation advances the release version past v0.
    validate_success(
        api.allocate_pre_order(po_a["id"], {"expected_release_product_version": v0}, SM),
        200)
    # Second allocation still carrying v0 is stale.
    res = api.allocate_pre_order(po_b["id"], {"expected_release_product_version": v0}, SM)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION)


def test_preorder_deposit_debits_store_credit(api):
    """PRD §3.3: "Creation appends a ledger row with `reason` `PREORDER_DEPOSIT` and
    `delta_cents` equal to the negated `deposit_paid_cents`, then recomputes the
    customer's balance, and computes the pre-order's `priority_score`."

    Design: Corner/cross_cutting_complexity_layers/preorder_deposit_debits_store_credit
    """
    cust = create_customer("Dep Cust", "dep@x.com", credit_cents=6000)
    rp = create_release_product(title="Dep Box", allocation_pool=10,
                                unit_price_cents=1000, deposit_required_cents=1000)
    po = create_requested_pre_order(cust, rp, requested_quantity=1, deposit_paid_cents=1000)
    assert po["deposit_paid_cents"] == 1000
    cust_after = validate_success(api.get_customer(cust["id"], SM), 200)
    assert cust_after["store_credit_balance_cents"] == 5000
