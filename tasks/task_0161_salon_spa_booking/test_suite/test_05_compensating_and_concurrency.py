"""Compensating-action invariants (inventory units and package sessions are
conserved across void/cancel), the inventory-restock action, no-show dispute
reversal, the optimistic-concurrency happy path, and immediate cascade
visibility.

Queue A (Difficulty) — rule: compensating_invariant.
Queue B (Corner) — sections: endpoints (restock, dispute),
cross_cutting_complexity_layers (OCC happy path), consistency_model.
"""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    create_appointment_payload,
    create_checkout_payload,
    create_salon,
    create_stylist,
    create_resource,
    create_service,
    create_client,
    create_product_sku,
    create_package,
    create_package_purchase,
    advance_clock,
    book_appointment,
    checkout_appointment,
    setup_bookable_salon,
)

OWNER = TEST_USERS["salon_owner_headers"]
FRONT = TEST_USERS["front_desk_headers"]


# =========================================================================== #
# Rule 9 — compensating_invariant
# =========================================================================== #
def test_void_conserves_product_inventory_units(api):
    """PRD §3.5: "On settlement each line decrements its SKU's qty_on_hand by the
    line's quantity and advances that SKU's version."
    PRD §3.6: "Each child ProductSale line restores its SKU's qty_on_hand by the
    line's quantity (advancing each touched SKU's version), so that total units
    are conserved."

    Design: Difficulty/compensating_invariant/void_conserves_product_inventory_units
    """
    salon = create_salon(name="Inv Salon", tip_split_policy="DIRECT")
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION",
                             commission_pct=0.40, buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Wash", duration_minutes=30,
                             base_price_cents=0, deposit_pct=0.0)
    client = create_client(salon["id"], full_name="C1", email="inv@x.com")
    sku = create_product_sku(salon["id"], sku="SH-2", name="Shampoo", unit_price_cents=2000, qty_on_hand=10)
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt, _ = book_appointment(salon["id"], client["id"], stylist, chair["id"],
                               service["id"], "2026-07-01T13:00:00Z")
    advance_clock(salon["id"], "2026-07-01T14:00:00Z", salon["version"])
    co = checkout_appointment(appt["id"], retail_lines=[{"product_sku_id": sku["id"], "quantity": 3}])
    after_sale = get_success_data(api.get_product_sku(sku["id"], FRONT))
    assert after_sale["qty_on_hand"] == 7  # 10 - 3
    get_success_data(api.void_checkout(co["id"], OWNER))
    after_void = get_success_data(api.get_product_sku(sku["id"], FRONT))
    assert after_void["qty_on_hand"] == 10  # restored, no drift


def test_void_restores_each_line_quantity_no_drift(api):
    """PRD §3.6: "Each child ProductSale line restores its SKU's qty_on_hand by
    the line's quantity (advancing each touched SKU's version), so that total
    units are conserved."

    Design: Difficulty/compensating_invariant/void_conserves_product_inventory_units
    """
    salon = create_salon(name="Inv Salon 2", tip_split_policy="DIRECT")
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION",
                             commission_pct=0.40, buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Wash", duration_minutes=30,
                             base_price_cents=0, deposit_pct=0.0)
    client = create_client(salon["id"], full_name="C1", email="inv2@x.com")
    # Two SKUs sold on two lines; each is restored by its own line quantity.
    sku_a = create_product_sku(salon["id"], sku="AA-1", name="A", unit_price_cents=1000, qty_on_hand=20)
    sku_b = create_product_sku(salon["id"], sku="BB-1", name="B", unit_price_cents=1000, qty_on_hand=8)
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt, _ = book_appointment(salon["id"], client["id"], stylist, chair["id"],
                               service["id"], "2026-07-01T13:00:00Z")
    advance_clock(salon["id"], "2026-07-01T14:00:00Z", salon["version"])
    co = checkout_appointment(
        appt["id"],
        retail_lines=[{"product_sku_id": sku_a["id"], "quantity": 5},
                      {"product_sku_id": sku_b["id"], "quantity": 6}],
    )
    a_sold = get_success_data(api.get_product_sku(sku_a["id"], FRONT))
    b_sold = get_success_data(api.get_product_sku(sku_b["id"], FRONT))
    assert a_sold["qty_on_hand"] == 15 and b_sold["qty_on_hand"] == 2
    get_success_data(api.void_checkout(co["id"], OWNER))
    a_back = get_success_data(api.get_product_sku(sku_a["id"], FRONT))
    b_back = get_success_data(api.get_product_sku(sku_b["id"], FRONT))
    assert a_back["qty_on_hand"] == 20  # fully restored
    assert b_back["qty_on_hand"] == 8   # fully restored


def test_cancel_conserves_package_sessions(api):
    """PRD §3.5: "If the appointment redeemed a package session, that session is
    now consumed: the purchase's sessions_remaining is decremented by one."
    PRD §3.2: "it decrements when an appointment redeems a session at checkout,
    and it is restored when such an appointment is later cancelled, no-showed, or
    has its checkout voided."

    Design: Difficulty/compensating_invariant/cancel_conserves_package_sessions
    """
    salon = create_salon(name="Pkg Salon", tip_split_policy="DIRECT")
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION",
                             commission_pct=0.40, buffer_minutes=0)
    chA = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    chB = create_resource(salon["id"], label="Chair B", resource_type="CHAIR")
    service = create_service(salon["id"], name="Facial", duration_minutes=45,
                             base_price_cents=9000, deposit_pct=0.0)
    pkg = create_package(salon["id"], service["id"], session_count=4, price_cents=24000)
    client = create_client(salon["id"], full_name="Pkg C", email="pkg@x.com")
    pp = create_package_purchase(client["id"], pkg["id"])
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt1, _ = book_appointment(salon["id"], client["id"], stylist, chA["id"],
                                service["id"], "2026-07-01T13:00:00Z", package_purchase_id=pp["id"])
    appt2, _ = book_appointment(salon["id"], client["id"], stylist, chB["id"],
                                service["id"], "2026-07-01T16:00:00Z", package_purchase_id=pp["id"])
    advance_clock(salon["id"], "2026-07-01T14:00:00Z", salon["version"])
    checkout_appointment(appt1["id"], tip_cents=0)  # redeem one (4 -> 3)
    after_redeem = get_success_data(api.get_package_purchase(pp["id"], FRONT))
    assert after_redeem["sessions_remaining"] == 3
    # Cancel the second still-booked package appointment. It was never checked
    # out, so it never redeemed a session; the cancel restores nothing and
    # remaining stays 3 (consumed 1 + remaining 3 == original 4).
    get_success_data(api.cancel_appointment(appt2["id"], FRONT))
    after_cancel = get_success_data(api.get_package_purchase(pp["id"], FRONT))
    assert after_cancel["sessions_remaining"] == 3
    assert after_cancel["status"] == "ACTIVE"


def test_noshow_conserves_package_sessions(api):
    """PRD §3.2: "it decrements when an appointment redeems a session at checkout,
    and it is restored when such an appointment is later cancelled, no-showed, or
    has its checkout voided."

    Design: Difficulty/compensating_invariant/cancel_conserves_package_sessions
    """
    salon = create_salon(name="Pkg NoShow Salon", no_show_fee_pct=0.0, tip_split_policy="DIRECT")
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION",
                             commission_pct=0.40, buffer_minutes=0)
    chA = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    chB = create_resource(salon["id"], label="Chair B", resource_type="CHAIR")
    service = create_service(salon["id"], name="Facial", duration_minutes=45,
                             base_price_cents=9000, deposit_pct=0.0)
    pkg = create_package(salon["id"], service["id"], session_count=4, price_cents=24000)
    client = create_client(salon["id"], full_name="Pkg C", email="pkgns@x.com")
    pp = create_package_purchase(client["id"], pkg["id"])
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt1, _ = book_appointment(salon["id"], client["id"], stylist, chA["id"],
                                service["id"], "2026-07-01T13:00:00Z", package_purchase_id=pp["id"])
    appt2, _ = book_appointment(salon["id"], client["id"], stylist, chB["id"],
                                service["id"], "2026-07-01T16:00:00Z", package_purchase_id=pp["id"])
    # Thread the salon version through each advance (the clock guard rejects a
    # stale expected_salon_version, PRD §2.7).
    salon = advance_clock(salon["id"], "2026-07-01T14:00:00Z", salon["version"])
    checkout_appointment(appt1["id"], tip_cents=0)  # redeem one (4 -> 3)
    after_redeem = get_success_data(api.get_package_purchase(pp["id"], FRONT))
    assert after_redeem["sessions_remaining"] == 3
    # Advance past appt2's start and no-show it. appt2 was never checked out, so
    # no session was redeemed for it; the no-show restores nothing and remaining
    # stays at 3 (consumed 1 + remaining 3 == original 4).
    salon = advance_clock(salon["id"], "2026-07-01T16:30:00Z", salon["version"])
    get_success_data(api.no_show_appointment(appt2["id"], FRONT))
    after_noshow = get_success_data(api.get_package_purchase(pp["id"], FRONT))
    assert after_noshow["sessions_remaining"] == 3
    assert after_noshow["status"] == "ACTIVE"


# =========================================================================== #
# Corner — endpoints section: restock, dispute
# =========================================================================== #
def test_restock_increments_qty_on_hand_and_version(api):
    """PRD §3.1: "A restock adds a supplied quantity to qty_on_hand and advances
    the SKU's version."

    Design: Corner/endpoints/restock_increments_qty_on_hand
    """
    salon = create_salon(name="S")
    sku = create_product_sku(salon["id"], sku="RS-1", name="P", unit_price_cents=1000, qty_on_hand=10)
    updated = get_success_data(api.restock_product_sku(sku["id"], {"quantity": 5}, OWNER))
    assert updated["qty_on_hand"] == 15
    assert updated["version"] == 2


def test_dispute_no_show_reverses_strike_and_unsuspends(api):
    """PRD §3.4: "The dispute decrements the client's no_show_strikes by one
    (never below zero); if that brings the count below the salon's
    no_show_suspend_threshold and the client is currently SUSPENDED, the client
    is restored to ACTIVE."

    Design: Corner/endpoints/dispute_no_show_reverses_strike_and_unsuspends
    """
    salon = create_salon(name="S", no_show_suspend_threshold=1, no_show_fee_pct=0.0)
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION", buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Cut", duration_minutes=30,
                             base_price_cents=5000, deposit_pct=0.0)
    client = create_client(salon["id"], full_name="C1", email="dn@x.com")
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt, _ = book_appointment(salon["id"], client["id"], stylist, chair["id"],
                               service["id"], "2026-07-01T13:00:00Z")
    advance_clock(salon["id"], "2026-07-01T14:00:00Z", salon["version"])
    get_success_data(api.no_show_appointment(appt["id"], FRONT))
    suspended = get_success_data(api.get_client(client["id"], OWNER))
    assert suspended["status"] == "SUSPENDED"
    get_success_data(api.dispute_no_show(client["id"], {"appointment_id": appt["id"]}, OWNER))
    after = get_success_data(api.get_client(client["id"], OWNER))
    assert after["no_show_strikes"] == 0
    assert after["status"] == "ACTIVE"


# =========================================================================== #
# Corner — cross_cutting_complexity_layers: OCC happy path
# =========================================================================== #
def test_occ_correct_stylist_version_succeeds_and_bumps(api):
    """PRD §2.7: "A booking request must carry expected_stylist_version, which
    must equal the target stylist's current version. Each successful booking
    advances that stylist's version by one, because the stylist's schedule has
    changed."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_stylist_version_succeeds
    """
    base = setup_bookable_salon(stylist_overrides={"buffer_minutes": 0})
    stylist = base["stylists"][0]
    resp = api.create_appointment(
        create_appointment_payload(base["salon"]["id"], base["client"]["id"], stylist["id"],
                                   base["resources"][0]["id"], base["service"]["id"],
                                   "2026-07-01T13:00:00Z", stylist["version"]),
        FRONT,
    )
    validate_success(resp, 201)
    after = get_success_data(api.get_stylist(stylist["id"], FRONT))
    assert after["version"] == stylist["version"] + 1


# =========================================================================== #
# Corner — consistency_model: immediate cascade visibility
# =========================================================================== #
def test_checkout_cascade_visible_in_same_request(api):
    """PRD §3.5: "If the appointment redeemed a package session, that session is
    now consumed: the purchase's sessions_remaining is decremented by one."
    PRD §2.5: "Every temporal decision in the system ... reads this current_utc
    value."  (All cascades are committed atomically inside the one request that
    triggers them — PRD §1.)

    Design: Corner/consistency_model/checkout_cascade_visible_in_same_request
    """
    salon = create_salon(name="S", no_show_fee_pct=0.0)
    stylist = create_stylist(salon["id"], full_name="S1", compensation_model="COMMISSION", buffer_minutes=0)
    chair = create_resource(salon["id"], label="Chair A", resource_type="CHAIR")
    service = create_service(salon["id"], name="Facial", duration_minutes=45,
                             base_price_cents=9000, deposit_pct=0.0)
    pkg = create_package(salon["id"], service["id"], session_count=4, price_cents=24000)
    client = create_client(salon["id"], full_name="C1", email="im@x.com")
    pp = create_package_purchase(client["id"], pkg["id"])
    salon = advance_clock(salon["id"], "2026-07-01T12:00:00Z", salon["version"])
    appt, _ = book_appointment(salon["id"], client["id"], stylist, chair["id"],
                               service["id"], "2026-07-01T13:00:00Z", package_purchase_id=pp["id"])
    advance_clock(salon["id"], "2026-07-01T14:00:00Z", salon["version"])
    checkout_appointment(appt["id"], tip_cents=0)
    # Immediate read shows the decrement already applied (4 -> 3).
    pp_now = get_success_data(api.get_package_purchase(pp["id"], FRONT))
    assert pp_now["sessions_remaining"] == 3
    assert pp_now["status"] == "ACTIVE"
