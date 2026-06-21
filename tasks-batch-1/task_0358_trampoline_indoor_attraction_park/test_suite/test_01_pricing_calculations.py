"""Pricing and refund calculations: pass pricing (inclusion / discount / plain),
party pricing pinned order, add-on catalog pricing, cancellation refund tiers, and
the frozen / immutable money fields.

Translates difficulty queue dual_variant_calc + combinatorial_formula (pricing
instances) and corner calculations / entities (system & immutable fields).
"""
from test_helpers import (
    validate_success, ApiErrorId,
    is_valid_uuid,
    create_park_with_clock, set_clock, create_slot, get_slot_version,
    create_adult, sign_waiver,
    create_member, create_membership, create_member_with_membership,
    create_reservation_pass, create_jump_pass,
    create_member_pass_paid,
    setup_party_prereqs, create_party_booking, hold_party_deposit,
    create_add_on_payload, create_jump_pass_payload,
    make_member_headers,
    api_client,
)
from test_helpers import TEST_USERS

PM = TEST_USERS["park_manager_headers"]
FD = TEST_USERS["front_desk_headers"]


# ─────────────────────────────────────────────────────────────────────
# dual_variant_calc / pass_pricing_inclusion_vs_discount_on_jump_pass  (2 tests)
# ─────────────────────────────────────────────────────────────────────
def test_pass_pricing_inclusion_variant_only_socks_billed(api):
    """PRD §3.5: "If a member is applied, the membership is `ACTIVE`, and it has at
    least one included visit remaining (`included_visits_remaining` greater than 0),
    the inclusion path applies: the base-plus-surcharge is fully waived (covered by
    the membership) and only the socks subtotal is billed, so `base_charge_cents`
    equals the socks subtotal, and the pass is marked to consume one inclusion when
    it is paid."

    Fresh GOLD member (8 inclusions), slot base 2000, 1 sock -> base_charge_cents == 350.

    Design: Difficulty/dual_variant_calc/pass_pricing_inclusion_vs_discount_on_jump_pass
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    member, _ = create_member_with_membership(park["id"], tier="GOLD", email="m1@x.com")
    mh = make_member_headers(member["id"])
    participant = create_adult(park["id"], full_name="Jumper Adult",
                               member_id=member["id"], headers=mh)
    pas = create_reservation_pass(slot["id"], participant["id"], get_slot_version(slot["id"]),
                                  headers=mh, sock_count=1, member_id=member["id"])
    assert pas["base_charge_cents"] == 350, \
        f"inclusion path bills only socks 350, got {pas['base_charge_cents']}"
    assert pas["member_id"] == member["id"]


def test_pass_pricing_discount_variant_when_inclusion_drained(api):
    """PRD §3.5: "If a member is applied and the membership is `ACTIVE` but no
    included visits remain, the discount path applies: the membership's tier discount
    percentage is taken off the discountable amount (rounded half up to whole cents)
    and `base_charge_cents` is that discounted discountable amount plus the full socks
    subtotal — no inclusion is consumed."

    GOLD member (25% discount), slot base 2000, RESERVATION (no surcharge), 1 sock,
    inclusion drained to 0 -> discountable 2000 - 500 = 1500, + 350 socks = 1850.

    Design: Difficulty/dual_variant_calc/pass_pricing_inclusion_vs_discount_on_jump_pass
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=20, base_price_cents=2000)
    # GOLD has 8 inclusions; drain them all by creating + paying 8 reservation passes.
    member, _ = create_member_with_membership(park["id"], tier="GOLD", email="g@x.com")
    mh = make_member_headers(member["id"])
    participant = create_adult(park["id"], full_name="Drain G", member_id=member["id"], headers=mh)
    for _ in range(8):
        drain = create_reservation_pass(slot["id"], participant["id"], get_slot_version(slot["id"]),
                                        headers=mh, sock_count=1, member_id=member["id"])
        validate_success(api.pay_jump_pass(drain["id"], mh), 200)
    # 9th member pass now takes the discount path: 2000*0.75 = 1500, + 350 = 1850.
    pas = create_reservation_pass(slot["id"], participant["id"], get_slot_version(slot["id"]),
                                  headers=mh, sock_count=1, member_id=member["id"])
    assert pas["base_charge_cents"] == 1850, \
        f"discount path: 1500 discounted + 350 socks == 1850, got {pas['base_charge_cents']}"


# ─────────────────────────────────────────────────────────────────────
# combinatorial_formula / pass_pricing_mode_a_nonlinear_branch_on_member_state  (2 tests)
# ─────────────────────────────────────────────────────────────────────
def test_pass_pricing_silver_walkin_discount_after_drain(api):
    """PRD §3.5: "If a member is applied and the membership is `ACTIVE` but no
    included visits remain, the discount path applies: the membership's tier discount
    percentage is taken off the discountable amount (rounded half up to whole cents)
    and `base_charge_cents` is that discounted discountable amount plus the full socks
    subtotal — no inclusion is consumed."
    PRD §3.5: "The surcharge is the park's `walkin_surcharge_cents` when the `channel`
    is `WALKIN`, and zero for a `RESERVATION`."

    SILVER (15%), 4 inclusions drained, WALKIN base 2500 + 500 surcharge = 3000,
    discount 450 -> 2550, + 3 socks*350=1050 -> base_charge_cents == 3600.

    Design: Difficulty/combinatorial_formula/pass_pricing_mode_a_nonlinear_branch_on_member_state
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2500)
    member, _ = create_member_with_membership(park["id"], tier="SILVER", email="m2@x.com")
    mh = make_member_headers(member["id"])
    participant = create_adult(park["id"], full_name="Drain Member",
                               member_id=member["id"], headers=mh)
    # Drain the 4 SILVER included visits via 4 paid reservation passes.
    for _ in range(4):
        drain = create_reservation_pass(slot["id"], participant["id"], get_slot_version(slot["id"]),
                                        headers=mh, sock_count=1, member_id=member["id"])
        validate_success(api.pay_jump_pass(drain["id"], mh), 200)
    pas = create_jump_pass(slot["id"], participant["id"], get_slot_version(slot["id"]),
                           headers=FD, channel="WALKIN", sock_count=3, member_id=member["id"])
    assert pas["base_charge_cents"] == 3600, \
        f"WALKIN discount mode: 2550 discounted + 1050 socks == 3600, got {pas['base_charge_cents']}"


def test_pass_pricing_silver_inclusion_first_pass_only_socks(api):
    """PRD §3.5: "the inclusion path applies: the base-plus-surcharge is fully waived
    (covered by the membership) and only the socks subtotal is billed, so
    `base_charge_cents` equals the socks subtotal".

    SILVER member's FIRST pass (4 inclusions available), 3 socks -> only socks billed
    == 1050, demonstrating the non-linear branch on member state before any drain.

    Design: Difficulty/combinatorial_formula/pass_pricing_mode_a_nonlinear_branch_on_member_state
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2500)
    member, _ = create_member_with_membership(park["id"], tier="SILVER", email="s@x.com")
    mh = make_member_headers(member["id"])
    participant = create_adult(park["id"], full_name="Fresh Silver",
                               member_id=member["id"], headers=mh)
    pas = create_jump_pass(slot["id"], participant["id"], get_slot_version(slot["id"]),
                           headers=mh, channel="WALKIN", sock_count=3, member_id=member["id"])
    assert pas["base_charge_cents"] == 1050, \
        f"inclusion path: base+surcharge waived, only 3*350 socks == 1050, got {pas['base_charge_cents']}"


# ─────────────────────────────────────────────────────────────────────
# combinatorial_formula / party_pricing_mode_b_pinned_discount_then_room_fee_order  (2 tests)
# ─────────────────────────────────────────────────────────────────────
def test_party_pricing_member_discount_before_room_fee_total(api):
    """PRD §3.8: "The per-guest subtotal is the package's `per_guest_cents` multiplied
    by `guest_count`. If a host member is applied and that membership is `ACTIVE`, a
    guest discount equal to the per-guest subtotal times the membership's tier discount
    percentage (rounded half up to whole cents) is subtracted from the per-guest
    subtotal — the discount touches only the per-guest portion, never the room fee. The
    `total_cents` is then the package's `base_room_fee_cents` plus that (possibly
    discounted) per-guest subtotal."

    GOLD host, per_guest 1500 x 10 = 15000, 25% discount -> 11250, + room fee 10000
    -> total_cents == 21250.

    Design: Difficulty/combinatorial_formula/party_pricing_mode_b_pinned_discount_then_room_fee_order
    """
    park, slot, room, package = setup_party_prereqs(
        clock="2026-06-15T00:00:00Z",
        slot_overrides={"jump_capacity": 30, "base_price_cents": 2000},
        room_overrides={"name": "Room A", "room_capacity": 30},
        package_overrides={"per_guest_cents": 1500, "base_room_fee_cents": 10000, "min_guests": 4},
    )
    member, _ = create_member_with_membership(park["id"], tier="GOLD", email="host@x.com")
    mh = make_member_headers(member["id"])
    booking = create_party_booking(package["id"], room["id"], slot["id"], guest_count=10,
                                   headers=mh, host_member_id=member["id"])
    assert booking["total_cents"] == 21250, \
        f"discount before room fee: 11250 + 10000 == 21250, got {booking['total_cents']}"


def test_party_pricing_deposit_rounds_frozen_total_half_up(api):
    """PRD §3.8: "The `deposit_cents` is pinned later, at the hold-deposit step, as
    `total_cents` times the park's `party_deposit_pct`, rounded half up to whole cents."

    Total 21250 (GOLD discount), party_deposit_pct 0.25 -> 21250*0.25 = 5312.5,
    rounded half up -> deposit_cents == 5313.

    Design: Difficulty/combinatorial_formula/party_pricing_mode_b_pinned_discount_then_room_fee_order
    """
    park, slot, room, package = setup_party_prereqs(
        clock="2026-06-15T00:00:00Z",
        slot_overrides={"jump_capacity": 30, "base_price_cents": 2000},
        room_overrides={"name": "Room A", "room_capacity": 30},
        package_overrides={"per_guest_cents": 1500, "base_room_fee_cents": 10000, "min_guests": 4},
    )
    member, _ = create_member_with_membership(park["id"], tier="GOLD", email="host2@x.com")
    mh = make_member_headers(member["id"])
    booking = create_party_booking(package["id"], room["id"], slot["id"], guest_count=10,
                                   headers=mh, host_member_id=member["id"])
    held = hold_party_deposit(booking["id"], slot["id"], headers=mh)
    assert held["total_cents"] == 21250
    assert held["deposit_cents"] == 5313, \
        f"round_half_up(21250*0.25) == 5313, got {held['deposit_cents']}"


# ─────────────────────────────────────────────────────────────────────
# Corner calculations
# ─────────────────────────────────────────────────────────────────────
def test_walkin_surcharge_applied_no_member(api):
    """PRD §3.5: "The surcharge is the park's `walkin_surcharge_cents` when the
    `channel` is `WALKIN`, and zero for a `RESERVATION`. The discountable amount is the
    slot's `base_price_cents` plus that surcharge ... Otherwise `base_charge_cents` is
    simply the discountable amount plus the socks subtotal."

    WALKIN, base 2000, 2 socks, no member -> 2000 + 500 surcharge + 700 socks == 3200.

    Design: Corner/calculations/walkin_surcharge_applied_no_member
    """
    park = create_park_with_clock("2026-06-20T10:05:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="WS J")
    sign_waiver(participant["id"], participant["id"], signature_text="WS J")
    pas = create_jump_pass(slot["id"], participant["id"], get_slot_version(slot["id"]),
                           channel="WALKIN", sock_count=2)
    assert pas["base_charge_cents"] == 3200, \
        f"2000 + 500 surcharge + 700 socks == 3200, got {pas['base_charge_cents']}"


def test_addon_catalog_price_overrides_input(api):
    """PRD §3.5: "The server resolves the `unit_price_cents` from its own catalog and
    ignores any client-supplied price: `ARM_SLEEVES` is 800 cents, `LOCKER` is 500
    cents, `FAST_PASS` is 1500 cents, and `PHOTO_PKG` is 2500 cents. The
    `line_total_cents` is the resolved unit price multiplied by `quantity`."

    PHOTO_PKG x1 -> unit_price_cents 2500, line_total_cents 2500.

    Design: Corner/calculations/addon_catalog_price_overrides_input
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="AO J")
    pas = create_reservation_pass(slot["id"], participant["id"], get_slot_version(slot["id"]))
    addon = validate_success(
        api.create_add_on(pas["id"], create_add_on_payload("PHOTO_PKG", 1), FD), 201)
    assert addon["unit_price_cents"] == 2500
    assert addon["line_total_cents"] == 2500


def test_late_cancel_partial_refund_socks_only(api):
    """PRD §3.6: "Otherwise the cancellation is late: the pass price is forfeited and
    only the socks-and-add-ons portion is refundable, so the refund is the lesser of
    `amount_paid_cents` and that socks-and-add-ons figure; `payment_status` becomes
    `PARTIALLY_REFUNDED` if that refund is strictly less than `amount_paid_cents`".

    Paid pass (base 2000 + 1 sock = paid 2350); cancel 60 min before start (< 120 cutoff)
    -> refund socks 350, payment_status PARTIALLY_REFUNDED.

    Design: Corner/calculations/late_cancel_partial_refund_socks_only
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="LC J")
    pas = create_reservation_pass(slot["id"], participant["id"], get_slot_version(slot["id"]))
    validate_success(api.pay_jump_pass(pas["id"], FD), 200)
    set_clock("2026-06-20T09:00:00Z")  # 60 min before slot start
    cancelled = validate_success(api.cancel_jump_pass(pas["id"], FD), 200)
    assert cancelled["amount_refunded_cents"] == 350
    assert cancelled["payment_status"] == "PARTIALLY_REFUNDED"


# ─────────────────────────────────────────────────────────────────────
# Corner entities — system / frozen / immutable money fields
# ─────────────────────────────────────────────────────────────────────
def test_jump_pass_system_fields_generated(api):
    """PRD §3.5: "The pass's `base_charge_cents` is frozen at this moment by the pricing
    rule below and never changes afterward."
    PRD §2.4: "The `version` field is an integer that starts at 1".

    RESERVATION base 2000 + 1 sock, no member -> base_charge_cents 2350 (server-computed),
    id is a UUID, version == 1.

    Design: Corner/entities/jump_pass_system_fields_generated
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="Sys J")
    pas = validate_success(
        api.create_jump_pass(
            create_jump_pass_payload(slot["id"], participant["id"], get_slot_version(slot["id"]),
                                     sock_count=1, base_charge_cents=999999),
            FD), 201)
    assert pas["base_charge_cents"] == 2350, \
        f"server-computed 2350, client input ignored, got {pas['base_charge_cents']}"
    assert is_valid_uuid(pas["id"])
    assert pas["version"] == 1


def test_pass_addon_immutable_no_version(api):
    """PRD §2.4: "One resource type is deliberately leaner: a `PassAddOn` is immutable
    once attached, so it carries only `id` and `created_at` — it has neither an
    `updated_at` nor a `version` field."

    FAST_PASS x2 -> line_total_cents 3000; the add-on body has id + created_at but no
    updated_at / version.

    Design: Corner/entities/pass_addon_immutable_no_version
    """
    park = create_park_with_clock("2026-06-15T00:00:00Z")
    slot = create_slot(park["id"], jump_capacity=10, base_price_cents=2000)
    participant = create_adult(park["id"], full_name="Add J")
    pas = create_reservation_pass(slot["id"], participant["id"], get_slot_version(slot["id"]))
    addon = validate_success(
        api.create_add_on(pas["id"], create_add_on_payload("FAST_PASS", 2), FD), 201)
    assert addon["line_total_cents"] == 3000
    assert is_valid_uuid(addon["id"])
    assert "created_at" in addon
    assert "updated_at" not in addon, "PassAddOn must not carry updated_at"
    assert "version" not in addon, "PassAddOn must not carry version"
