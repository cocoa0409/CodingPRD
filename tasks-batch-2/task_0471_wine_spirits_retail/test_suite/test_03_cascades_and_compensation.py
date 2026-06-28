"""Cascades and compensation: bonded->taxed withdrawal, shipment-return order cancel,
reservation conservation on cancel, monthly-volume restoration, derived compliance recompute.

Covers difficulty queue transitive_cascade + compensating_invariant and the
corner queue cross_cutting_complexity_layers derived-field reconciliation.
"""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS, make_customer_headers, fixtures as fx,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─── Difficulty: transitive_cascade ─────────────────────────────────────────
def test_capture_bonded_withdrawal_depletes_bonded_lot(api):
    """PRD §3.7: "For each order line whose chosen lot is `BONDED` at capture time, the system withdraws that line's units from bond: it sets the line's `line_excise_cents` to the line's `qty` times the bonded lot's `excise_band_cents_per_unit`; it decrements that bonded lot's `qty_on_hand` by the line's `qty` and its `qty_reserved` by the line's `qty`; it mints or appends a `TAXED` inventory lot for the same vintage and increases that taxed lot's `qty_on_hand` by the line's `qty`; and it repoints the line's `lot_id` to the taxed lot."
    PRD §3.6: "The settled total diverges from the provisional total exactly when some line drew from a bonded lot."

    Design: Difficulty/transitive_cascade/capture_bonded_withdrawal_line_to_bonded_lot_to_taxed_lot_depth3
    """
    fx.set_clock()
    cust = fx.create_verified_customer("tc1@x.com", ship_state_code="CA")
    _, vint, blot = fx.setup_released_vintage(
        "TC-1", category="SPIRITS", abv_pct=40.00, list_price_cents=4000, case_pack_size=6,
        tax_status="BONDED", qty_on_hand=4, excise_band_cents_per_unit=60, vintage_year=2018)

    order = fx.build_submitted_order(cust, vint["id"], 4, channel="POS")
    fx.authorize(cust, order["id"])
    captured = validate_success(api_client.capture_payment(order["id"], ASSOCIATE))

    bonded = get_success_data(api_client.get_lot(blot["id"], ASSOCIATE))
    assert bonded["qty_on_hand"] == 0, f"bonded lot qty_on_hand should drop to 0, got {bonded['qty_on_hand']}"
    assert bonded["qty_reserved"] == 0, f"bonded lot qty_reserved should drop to 0, got {bonded['qty_reserved']}"
    assert captured["settled_total_cents"] > captured["provisional_total_cents"], \
        "settled must exceed provisional once real excise is added"


def test_shipment_return_cancels_order_and_releases_reservation(api):
    """PRD §3.10: "Returning a dispatched shipment advances `DISPATCHED → RETURNED` and cascades across the aggregate boundary: the owning order is cancelled from `READY` via the same compensation as an order cancel — reservations released, lot quantities restored, and the compliance-window row deactivated."

    Design: Difficulty/transitive_cascade/shipment_return_cancels_order_releases_reservation_depth2
    """
    fx.set_clock()
    fx.create_state_rule("TX", ship_allowed=True, growler_keg_allowed=True,
                         requires_adult_signature=False)
    cust = fx.create_verified_customer("tc2@x.com", ship_state_code="TX")
    _, vint, lot = fx.setup_released_vintage("TC-2", list_price_cents=3000, case_pack_size=6,
                                             qty_on_hand=10, vintage_year=2020)

    order, shipment = fx.build_dispatched_shipment(cust, vint["id"], 3, "TX")
    returned = validate_success(api_client.return_shipment(shipment["id"], ASSOCIATE))

    assert returned["status"] == "RETURNED"
    order_after = get_success_data(api_client.get_order(order["id"], ASSOCIATE))
    assert order_after["fulfillment_status"] == "CANCELLED", \
        f"owning order should be CANCELLED, got {order_after['fulfillment_status']}"
    lot_after = get_success_data(api_client.get_lot(lot["id"], ASSOCIATE))
    assert lot_after["qty_reserved"] == 0, \
        f"reservation should be released; qty_reserved should be 0, got {lot_after['qty_reserved']}"


# ─── Difficulty: compensating_invariant ─────────────────────────────────────
def test_cancel_restores_lot_available_units(api):
    """PRD §3.10: "Cancelling a `SUBMITTED` order ... advances `SUBMITTED → CANCELLED` and runs the compensation cascade: each line's `reservation_state` advances `COMMITTED → RELEASED`, the lot's `qty_reserved` is credited back by the line's `qty`"
    PRD §3.3: "the selected lot's `qty_reserved` is increased by the line's `qty`."

    Design: Difficulty/compensating_invariant/cancel_restores_lot_available_units_conserved
    """
    fx.set_clock()
    cust = fx.create_verified_customer("ci1@x.com", ship_state_code="CA")
    _, vint, lot = fx.setup_released_vintage("CI-1", list_price_cents=3000, case_pack_size=6,
                                             qty_on_hand=5, vintage_year=2020)

    order = fx.build_submitted_order(cust, vint["id"], 2, channel="POS")
    cancelled = validate_success(api_client.cancel_order(order["id"], make_customer_headers(cust["id"])))
    assert cancelled["fulfillment_status"] == "CANCELLED"

    lot_after = get_success_data(api_client.get_lot(lot["id"], ASSOCIATE))
    assert lot_after["qty_reserved"] == 0, f"qty_reserved should return to 0, got {lot_after['qty_reserved']}"
    assert lot_after["qty_on_hand"] == 5, f"qty_on_hand should remain 5, got {lot_after['qty_on_hand']}"


def test_cancel_restores_monthly_compliance_volume(api):
    """PRD §3.5: "When the producing order is later cancelled or refunded, its compliance-window row's `active` flag is flipped to false so that the released volume no longer counts against the month's cap — the compensating invariant that keeps the monthly accounting honest."
    PRD §3.5: "The order is rejected with `ERR_ABC_MONTHLY_LIMIT_EXCEEDED` (HTTP 422) when that already-used volume plus this order's volume would be strictly greater than the destination state's `monthly_volume_limit_ml`; exactly reaching the limit is allowed."

    Design: Difficulty/compensating_invariant/cancel_restores_monthly_compliance_volume_conserved
    """
    fx.set_clock()
    fx.create_state_rule("TX", ship_allowed=True, growler_keg_allowed=True,
                         monthly_volume_limit_ml=1500, requires_adult_signature=False)
    cust = fx.create_verified_customer("ci2@x.com", ship_state_code="TX")
    _, vint, _ = fx.setup_released_vintage("CI-2", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=20, vintage_year=2020)

    # First SHIP order 750*2 = 1500ml fills the cap, then cancelled.
    order1 = fx.build_submitted_order(cust, vint["id"], 2, channel="SHIP", dest_state_code="TX")
    get_success_data(api_client.cancel_order(order1["id"], make_customer_headers(cust["id"])))

    # Second order of the same 1500ml must now succeed (volume restored).
    order2 = fx.build_submitted_order(cust, vint["id"], 2, channel="SHIP", dest_state_code="TX")
    assert order2["fulfillment_status"] == "SUBMITTED", \
        f"second order should submit after cancel restored volume, got {order2['fulfillment_status']}"
    order1_after = get_success_data(api_client.get_order(order1["id"], ASSOCIATE))
    assert order1_after["fulfillment_status"] == "CANCELLED"


# ─── Corner: cross_cutting_complexity_layers (derived field reconciliation) ──
def test_compliance_status_reconciles_to_clear_after_verify(api):
    """PRD §3.2: "A customer's **compliance status** is a derived risk posture recomputed after every ID-scan verify or reject ... start at zero; add 2 if the customer is not age-verified ... A final score of exactly 0 yields `CLEAR`"
    PRD §3.2: "On a successful verify, the owning customer's `age_verified` flips to true and that customer's `compliance_status` is recomputed."

    Design: Corner/cross_cutting_complexity_layers/derived_compliance_status_reconciled_after_scan_verify
    """
    fx.set_clock()
    cust = fx.register_customer("dr1@x.com", ship_state_code="CA")
    scan = fx.create_pending_scan(cust)

    validate_success(api_client.verify_id_scan(scan["id"], ASSOCIATE))
    customer = get_success_data(api_client.get_customer(cust["id"], COMPLIANCE))

    assert customer["compliance_status"] == "CLEAR", \
        f"compliance_status should reconcile to CLEAR, got {customer['compliance_status']}"
    assert customer["age_verified"] is True
