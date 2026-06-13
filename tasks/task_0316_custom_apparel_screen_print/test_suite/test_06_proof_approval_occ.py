"""Optimistic-concurrency tests on proof approval: the happy path advances Order.version,
and a second approve carrying the now-stale expected_order_version is rejected (§2.9).
"""
from test_helpers import (
    validate_success,
    validate_error,
    setup_shop_catalog,
    create_draft_order,
    create_proof,
    submit_proof,
    api_client,
    TEST_USERS,
    make_customer_headers,
)

SM = TEST_USERS["shop_manager_headers"]


# ═══════════════════════════════════════════════════════════════════════════
# cross_cutting (corner) — happy OCC path
# ═══════════════════════════════════════════════════════════════════════════

def test_approve_with_correct_version_succeeds_and_bumps_order_version(api):
    """PRD §3.3: "Approval by the owning `Customer` moves the proof from `SUBMITTED` to
    `APPROVED` and, as a side effect, increments the parent `Order`'s `version` by one;
    approval is the OCC-guarded operation of §2.9 and requires `expected_order_version`
    to equal the order's live `version`".

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_approves
    """
    cat = setup_shop_catalog(with_sku=False)
    order = create_draft_order(cat["shop"]["id"], cat["customer"]["id"])
    order_v = order["version"]
    proof = create_proof(order["id"], title="A", art_hash="h1")
    submit_proof(order["id"], proof["id"])
    cust_headers = make_customer_headers(cat["customer"]["id"])

    approved = validate_success(
        api.approve_proof(order["id"], proof["id"], {"expected_order_version": order_v}, cust_headers),
        200,
    )
    assert approved["status"] == "APPROVED"
    order_after = validate_success(api.get_order(order["id"], SM), 200)
    assert order_after["version"] == order_v + 1


# ═══════════════════════════════════════════════════════════════════════════
# cross_cutting (corner) — stale version rejected
# ═══════════════════════════════════════════════════════════════════════════

def test_stale_expected_order_version_rejected(api):
    """PRD §2.9: "If `expected_order_version` does not equal the live `version` of that
    `Order` at the moment the approval is processed, the request is rejected with
    `ERR_STALE_ORDER_VERSION` and HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_proof_approve
    """
    cat = setup_shop_catalog(with_sku=False)
    order = create_draft_order(cat["shop"]["id"], cat["customer"]["id"])
    stale_v = order["version"]
    cust_headers = make_customer_headers(cat["customer"]["id"])

    # Two submitted proofs on one order.
    proof_a = create_proof(order["id"], title="A", art_hash="h1")
    submit_proof(order["id"], proof_a["id"])
    proof_b = create_proof(order["id"], title="B", art_hash="h1b")
    submit_proof(order["id"], proof_b["id"])

    # Approve A with the fresh version -> succeeds, bumps Order.version.
    validate_success(
        api.approve_proof(order["id"], proof_a["id"], {"expected_order_version": stale_v}, cust_headers),
        200,
    )
    # Approve B still carrying the now-stale version -> rejected.
    res = api.approve_proof(
        order["id"], proof_b["id"], {"expected_order_version": stale_v}, cust_headers
    )
    validate_error(res, "ERR_STALE_ORDER_VERSION", expected_status=412)
