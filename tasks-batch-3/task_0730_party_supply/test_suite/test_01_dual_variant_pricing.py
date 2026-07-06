"""Difficulty rule 1 — dual-variant calculations across different entity domains.

Two instances, each covered by two tests tagged with the design name.
"""
from test_helpers import (
    validate_success, get_success_data, api_client,
    make_store_manager_headers, make_store_clerk_headers, make_customer_headers,
)
from test_helpers.fixtures import (
    set_clock, create_customer, create_sku_with_stock, restock_sku,
    setup_draft_order, reserve_order, apply_clearance,
    attach_custom_print, pay_order,
    setup_cpo_paid_with_n_revisions, setup_cpo_at_proof_sent,
    do_request_revision_and_proof,
)


# =====================================================================
# Instance A — order_grand_total_provisional_vs_finalized_snapshot
# =====================================================================

def test_order_grand_total_provisional_in_draft_uses_live_unit_price():
    """PRD §3.4: "Before reserve, while the order is still in DRAFT, the
    system exposes a provisional variant of the same total that reads the
    live Sku.unit_price_cents without any clearance snapshot lock, and that
    excludes HeliumOrder, DeliverySlot, and RentalContract deposits — this
    provisional total is intended for quoting only and may differ from the
    finalised total for the same set of entities whenever a SKU is later
    placed on clearance or an add-on is later attached between draft and
    reserve."

    Design: Difficulty/dual_variant_calc/order_grand_total_provisional_vs_finalized_snapshot
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=500, on_hand=100,
                                category="BALLOON_LATEX")
    # DRAFT order — provisional should be 10 * 500 = 5000 (no clearance applied).
    resp = api_client.create_order(
        {"customer_id": cust["id"], "channel": "IN_STORE",
         "lines": [{"sku_id": sku["id"], "qty": 10}]},
        make_store_clerk_headers(),
    )
    order = validate_success(resp, expected_status=201)
    assert order["grand_total_cents"] == 5000, (
        f"Provisional DRAFT grand_total_cents must be 10*500=5000 (live "
        f"unit_price, no clearance); got {order['grand_total_cents']}"
    )


def test_order_grand_total_finalized_at_reserve_uses_clearance_snapshot():
    """PRD §3.4: "the server performs the cascade. Each affected SKU's
    reserved_qty is increased by the corresponding line quantity...
    Each OrderLine's unit_price_cents_at_capture is pinned — from the SKU's
    unit_price_cents with clearance_pct applied when the SKU is on clearance,
    or from the bundle's bundle_price_cents when the line is a bundle line —
    and its line_total_cents is set to qty multiplied by
    unit_price_cents_at_capture."
    PRD §3.4: "Once the order is reserved, this value is immutable with
    respect to later catalog edits to the underlying SKUs — subsequently
    placing one of the SKUs on clearance does not mutate the reserved
    order's grand total."

    Design: Difficulty/dual_variant_calc/order_grand_total_provisional_vs_finalized_snapshot
    """
    set_clock("2026-06-15T10:00:00Z")
    cust = create_customer()
    sku = create_sku_with_stock(unit_price_cents=500, on_hand=100,
                                category="BALLOON_LATEX")
    order = setup_draft_order(cust["id"], sku["id"], qty=10)
    # Move SKU to clearance pct=0.20 BEFORE reserve.
    apply_clearance(sku["id"], 0.20, sku["version"])
    # RESERVE — snapshot picks up clearance: 10 * (500*0.80) = 4000.
    resp = api_client.reserve_order(
        order["id"], order["version"], make_store_clerk_headers(),
    )
    reserved = validate_success(resp)
    assert reserved["grand_total_cents"] == 4000, (
        f"Finalized grand_total_cents at RESERVED must be "
        f"10 * round(500*0.80) = 4000 (clearance snapshot); "
        f"got {reserved['grand_total_cents']}"
    )
    assert reserved["fulfillment_status"] == "RESERVED"


# =====================================================================
# Instance B — custom_print_fee_estimate_vs_finalized_with_revisions
# =====================================================================

def test_custom_print_fee_revision_count_increments_across_loop():
    """PRD §3.7: "A revision request transitions PROOF_SENT to
    REVISION_REQUESTED, increments revision_count by one, and is permitted
    only when revision_count is currently less than 3 — a fourth revision
    attempt is rejected with ERR_REVISION_LIMIT."

    Design: Difficulty/dual_variant_calc/custom_print_fee_estimate_vs_finalized_with_revisions
    """
    cust, sku, order, cpo_ps = setup_cpo_at_proof_sent(
        banner_length_ft=10, base_sku_price=100, base_on_hand=100,
    )
    # First proof already sent; revision_count=0 at this point.
    assert cpo_ps["revision_count"] == 0
    # Loop through 2 more revisions (request-rev + send-proof twice).
    latest = do_request_revision_and_proof(cpo_ps["id"], cust["id"])
    assert latest["revision_count"] == 1
    latest = do_request_revision_and_proof(cpo_ps["id"], cust["id"])
    assert latest["revision_count"] == 2
    assert latest["status"] == "PROOF_SENT"


def test_custom_print_fee_finalized_at_approve_includes_revision_surcharge():
    """PRD §3.7: "The finalised variant runs at approve time and uses the
    actual observed revision_count; the result is written to
    CustomPrintOrder.print_fee_cents, and the parent order's subtotal_cents
    and grand_total_cents are then recomputed to include it. For a ten-foot
    banner approved after two revision cycles, the finalised fee therefore
    exceeds the estimated fee by 500 cents per revision beyond the first —
    identical banner_length_ft inputs produce different persisted results
    whenever revisions accumulate."

    Design: Difficulty/dual_variant_calc/custom_print_fee_estimate_vs_finalized_with_revisions
    """
    cust, order, cpo_ps = setup_cpo_paid_with_n_revisions(
        banner_length_ft=10, n_revisions=2,
        base_sku_price=100, base_on_hand=100,
    )
    assert cpo_ps["revision_count"] == 2
    # 10-ft banner: 5*800 + 5*600 + 0*450 = 4000 + 3000 = 7000 unrounded;
    # revision surcharge = max(0, 2-1)*500 = 500. Rounded once = 7500.
    resp = api_client.approve_proof(cpo_ps["id"], make_customer_headers(cust["id"]))
    approved = validate_success(resp)
    assert approved["print_fee_cents"] == 7500, (
        f"Finalized print_fee_cents for 10-ft banner with 2 revisions "
        f"must be 5*800 + 5*600 + max(0,2-1)*500 = 7500; got {approved['print_fee_cents']}"
    )
    assert approved["revision_count"] == 2
