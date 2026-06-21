"""Pricing calculations (provisional vs final, combinatorial) and the arcade
wallet loyalty bonus.

Covers Difficulty queue rules dual_variant_calc and combinatorial_formula,
plus the corner-design calculation claims and the immediate-consistency claim.
"""
from test_helpers import (
    validate_success,
    api_client,
    create_venue_payload, create_attraction_payload, create_pricing_plan_payload,
    create_heat_payload, create_tee_session_payload, create_guest_payload,
    create_waiver_payload, create_combo_pass_payload, create_booking_payload,
    top_up_payload,
    make_ops_manager_headers, make_cashier_headers,
    setup_open_heat_scenario, setup_open_tee_scenario, make_signed_guest,
    create_heat_hold_booking, create_tee_hold_booking,
    confirm_booking_heat, confirm_booking_tee,
    create_guest, get_wallet_for_guest, create_combo_pass,
)

OPS = make_ops_manager_headers()
CASHIER = make_cashier_headers()


# ───────────────────────── Difficulty: dual_variant_calc ─────────────────────

def test_provisional_offpeak_price_at_hold(api):
    """PRD §3.7: "The provisional variant runs at booking creation: it reads the
    slot's window as it stands at create time, stores the result as
    gross_price_cents on the held booking without applying any combo credits, and
    sets credits_applied to zero and cash_due_cents equal to gross_price_cents."
    PRD §3.7: "For a per-round or per-heat plan, the price scales with both units
    and players: the raw amount is the per-unit price multiplied by the effective
    unit count and then by the party_size."

    Design: Difficulty/dual_variant_calc/booking_price_provisional_vs_final_diverges_on_window_flip
    """
    s = setup_open_heat_scenario(
        lane_count=10, base_price_cents=1500, mode="PER_HEAT", window="OFF_PEAK",
        plan_overrides={"peak_surcharge_cents": 500, "group_discount_pct": 0},
    )
    guest = make_signed_guest(height_cm=180)
    bk = create_heat_hold_booking(
        s["venue"]["id"], guest["id"], s["heat"]["id"], s["plan"]["id"], party_size=2, units=1
    )
    # PROVISIONAL OFF_PEAK: 1500 * 1 * 2 = 3000
    assert bk["gross_price_cents"] == 3000, f"expected 3000 provisional, got {bk['gross_price_cents']}"


def test_final_peak_price_at_confirm_diverges_from_provisional(api):
    """PRD §3.7: "when the slot's window is PEAK the plan's peak_surcharge_cents is
    added to that per-unit price."
    PRD §3.7: "The final variant runs at confirm and again at waitlist promotion:
    it re-reads the slot's window at that moment (it may have changed since the
    hold via a slot edit), recomputes gross_price_cents, then applies combo
    credits and finalizes cash_due_cents."

    Design: Difficulty/dual_variant_calc/booking_price_provisional_vs_final_diverges_on_window_flip
    """
    # OFF_PEAK heat booking (provisional) and a PEAK heat booking (final) under
    # the same plan; their gross prices diverge by the peak surcharge.
    s = setup_open_heat_scenario(
        lane_count=10, base_price_cents=1500, mode="PER_HEAT", window="OFF_PEAK",
        plan_overrides={"peak_surcharge_cents": 500, "group_discount_pct": 0},
    )
    venue_id, plan_id = s["venue"]["id"], s["plan"]["id"]
    heat_off = s["heat"]
    # A second, PEAK heat on the same attraction (non-overlapping interval).
    peak_heat = validate_success(api.create_heat(create_heat_payload(
        venue_id, s["attraction"]["id"], window="PEAK",
        start_utc="2026-06-14T11:00:00Z", end_utc="2026-06-14T11:15:00Z",
    ), OPS), 201)
    peak_heat = validate_success(api.open_heat(peak_heat["id"], OPS), 200)

    guest = make_signed_guest(height_cm=180)
    bk_off = create_heat_hold_booking(venue_id, guest["id"], heat_off["id"], plan_id, party_size=2, units=1)
    bk_peak = create_heat_hold_booking(venue_id, guest["id"], peak_heat["id"], plan_id, party_size=2, units=1)

    confirmed = confirm_booking_heat(bk_peak["id"], peak_heat["version"])
    # FINAL PEAK: (1500 + 500) * 1 * 2 = 4000
    assert confirmed["gross_price_cents"] == 4000, f"expected 4000 final PEAK, got {confirmed['gross_price_cents']}"
    assert confirmed["gross_price_cents"] != bk_off["gross_price_cents"], (
        "PEAK final price must differ from OFF_PEAK provisional price"
    )


def test_loyalty_bonus_credited_on_crossing_topup_order_a(api):
    """PRD §3.4: "For a given top-up, if the guest's total_loaded_cents before this
    top-up is below 5000 cents and the total after adding this top-up's amount
    reaches or exceeds 5000 cents, then this is the threshold-crossing top-up and
    it earns a bonus equal to ten percent of that single top-up's amount, rounded
    half up; the bonus is credited to arcade_card_balance_cents on top of the
    amount itself but is never added to total_loaded_cents."

    Design: Difficulty/dual_variant_calc/wallet_balance_loyalty_vs_balance_forward_diverge_on_topup_order
    """
    guest = create_guest(full_name="Alex", height_cm=175, as_role="cashier")
    wallet = get_wallet_for_guest(guest["id"])
    # Order [3000, 4000, 3000]: crossing top-up is 4000 -> bonus 400.
    for amt in (3000, 4000, 3000):
        wallet = validate_success(api.top_up_wallet(wallet["id"], top_up_payload(amt), CASHIER), 200)
    assert wallet["arcade_card_balance_cents"] == 10400, (
        f"expected 10400 (10000 + 400 bonus), got {wallet['arcade_card_balance_cents']}"
    )
    assert wallet["total_loaded_cents"] == 10000, (
        f"total_loaded_cents excludes bonus; expected 10000, got {wallet['total_loaded_cents']}"
    )


def test_loyalty_bonus_depends_on_topup_order_b(api):
    """PRD §3.4: "because eligibility depends on the cumulative total_loaded_cents
    standing before each top-up, the order in which top-ups are processed
    determines which top-up earns it."
    PRD §3.4: "and its total_loaded_cents is the lifetime sum of top-up amounts,
    which deliberately excludes any loyalty bonus credited on top of those
    amounts."

    Design: Difficulty/dual_variant_calc/wallet_balance_loyalty_vs_balance_forward_diverge_on_topup_order
    """
    guest = create_guest(full_name="Blair", height_cm=175, as_role="cashier")
    wallet = get_wallet_for_guest(guest["id"])
    # Order [3000, 3000, 4000]: crossing top-up is the second 3000 -> bonus 300.
    for amt in (3000, 3000, 4000):
        wallet = validate_success(api.top_up_wallet(wallet["id"], top_up_payload(amt), CASHIER), 200)
    assert wallet["arcade_card_balance_cents"] == 10300, (
        f"expected 10300 (10000 + 300 bonus), got {wallet['arcade_card_balance_cents']}"
    )
    assert wallet["total_loaded_cents"] == 10000


# ─────────────────────── Difficulty: combinatorial_formula ───────────────────

def test_per_round_peak_group_discount_combined_price(api):
    """PRD §3.7: "when the slot's window is PEAK the plan's peak_surcharge_cents is
    added to that per-unit price."
    PRD §3.7: "When the party_size is at least four players, the raw amount is
    multiplied by one minus the plan's group_discount_pct; for any smaller party
    the raw amount is left unchanged."

    Design: Difficulty/combinatorial_formula/booking_price_mode_a_nonlinear_multi_input
    """
    s = setup_open_tee_scenario(
        party_slot_capacity=20, base_price_cents=1200, mode="PER_ROUND", window="PEAK",
        plan_overrides={"peak_surcharge_cents": 300, "group_discount_pct": 0.20},
    )
    guest = make_signed_guest(height_cm=170)
    bk = create_tee_hold_booking(
        s["venue"]["id"], guest["id"], s["tee_session"]["id"], s["plan"]["id"],
        party_size=4, units=2,
    )
    confirmed = confirm_booking_tee(bk["id"], s["tee_session"]["version"])
    # per_unit = 1200 + 300 = 1500; raw = 1500*2*4 = 12000; *0.80 = 9600
    assert confirmed["gross_price_cents"] == 9600, (
        f"expected 9600 (PEAK+group discount), got {confirmed['gross_price_cents']}"
    )
    assert confirmed["status"] == "CONFIRMED"


def test_loyalty_bonus_order_dependent_two_topups(api):
    """PRD §3.4: "A loyalty bonus rewards the single top-up that carries a guest's
    lifetime loading across the 5000-cent threshold."
    PRD §3.4: "it earns a bonus equal to ten percent of that single top-up's
    amount, rounded half up; the bonus is credited to arcade_card_balance_cents on
    top of the amount itself but is never added to total_loaded_cents."

    Design: Difficulty/combinatorial_formula/wallet_loyalty_mode_c_order_dependent_bonus
    """
    guest = create_guest(full_name="Rao", height_cm=175)
    wallet = get_wallet_for_guest(guest["id"])
    # [2000, 6000]: 2000 below threshold; 6000 crosses -> bonus 600. Total 8600.
    for amt in (2000, 6000):
        wallet = validate_success(api.top_up_wallet(wallet["id"], top_up_payload(amt), OPS), 200)
    assert wallet["arcade_card_balance_cents"] == 8600, (
        f"expected 8600 (2000 + 6000 + 600 bonus), got {wallet['arcade_card_balance_cents']}"
    )
    assert wallet["total_loaded_cents"] == 8000


def test_per_heat_no_group_discount_below_min_party(api):
    """PRD §3.7: "For a per-round or per-heat plan, the price scales with both units
    and players: the raw amount is the per-unit price multiplied by the effective
    unit count and then by the party_size."
    PRD §3.7: "When the party_size is at least four players, the raw amount is
    multiplied by one minus the plan's group_discount_pct; for any smaller party
    the raw amount is left unchanged."

    Design: Difficulty/combinatorial_formula/booking_price_mode_a_nonlinear_multi_input
    """
    # party_size 3 (< 4) so the group-discount branch does NOT fire, even with a
    # PEAK surcharge and multi-unit booking: pure non-linear multi-input check.
    s = setup_open_tee_scenario(
        party_slot_capacity=20, base_price_cents=1200, mode="PER_ROUND", window="PEAK",
        plan_overrides={"peak_surcharge_cents": 300, "group_discount_pct": 0.20},
    )
    guest = make_signed_guest(height_cm=170)
    bk = create_tee_hold_booking(
        s["venue"]["id"], guest["id"], s["tee_session"]["id"], s["plan"]["id"],
        party_size=3, units=2,
    )
    confirmed = confirm_booking_tee(bk["id"], s["tee_session"]["version"])
    # per_unit = 1200 + 300 = 1500; raw = 1500*2*3 = 9000; party 3 < 4 -> no discount.
    assert confirmed["gross_price_cents"] == 9000, (
        f"expected 9000 (no group discount under party 4), got {confirmed['gross_price_cents']}"
    )


def test_loyalty_bonus_not_awarded_to_later_topup(api):
    """PRD §3.4: "Only the one crossing top-up earns the bonus — it is not applied
    retroactively to earlier top-ups and not applied to later ones, and because
    eligibility depends on the cumulative total_loaded_cents standing before each
    top-up, the order in which top-ups are processed determines which top-up earns
    it."

    Design: Difficulty/combinatorial_formula/wallet_loyalty_mode_c_order_dependent_bonus
    """
    guest = create_guest(full_name="Sasha", height_cm=175)
    wallet = get_wallet_for_guest(guest["id"])
    # [6000, 2000]: the FIRST 6000 crosses (bonus 600); the later 2000 earns nothing.
    for amt in (6000, 2000):
        wallet = validate_success(api.top_up_wallet(wallet["id"], top_up_payload(amt), OPS), 200)
    # 6000 + 600 bonus + 2000 (no bonus) = 8600.
    assert wallet["arcade_card_balance_cents"] == 8600, (
        f"later top-up earns no bonus; expected 8600, got {wallet['arcade_card_balance_cents']}"
    )
    assert wallet["total_loaded_cents"] == 8000


# ───────────────────────── Corner: calculations ──────────────────────────────

def test_wristband_price_is_flat_per_player(api):
    """PRD §3.7: "For a wristband plan, the price is flat per player: the per-unit
    price is multiplied by the party_size to give the raw amount, and the
    booking's units are folded into the band rather than multiplied through."

    Design: Corner/calculations/wristband_band_price_per_player
    """
    s = setup_open_tee_scenario(
        party_slot_capacity=10, base_price_cents=4000, mode="WRISTBAND",
        plan_overrides={"wristband_unit_cap": 6},
    )
    guest = make_signed_guest(height_cm=170)
    bk = create_tee_hold_booking(
        s["venue"]["id"], guest["id"], s["tee_session"]["id"], s["plan"]["id"],
        party_size=3, units=6,
    )
    confirmed = confirm_booking_tee(bk["id"], s["tee_session"]["version"])
    # WRISTBAND flat band: 4000 * party_size 3 = 12000 (units folded in).
    assert confirmed["gross_price_cents"] == 12000, (
        f"expected 12000 (flat band per player), got {confirmed['gross_price_cents']}"
    )
    assert confirmed["status"] == "CONFIRMED"


def test_combo_partial_coverage_splits_credits_and_cash(api):
    """PRD §3.7: "The number of billable units for credit purposes is the same
    effective unit count used in pricing multiplied by the party_size. The credits
    applied is the smaller of the pass's credits_remaining and that billable-unit
    count. The fraction of the booking those credits cover is the credits applied
    divided by the billable units (kept as an exact ratio), the credit's cash
    value is gross_price_cents multiplied by that covered fraction and rounded half
    up, and cash_due_cents is gross_price_cents minus that credit value, floored at
    zero."

    Design: Corner/calculations/combo_partial_coverage_splits_credits_and_cash
    """
    s = setup_open_tee_scenario(
        party_slot_capacity=20, base_price_cents=1200, mode="PER_ROUND", window="PEAK",
        plan_overrides={"peak_surcharge_cents": 300, "group_discount_pct": 0.20},
    )
    guest = make_signed_guest(height_cm=170)
    pass_ = create_combo_pass(guest["id"], total_credits=5)
    bk = create_tee_hold_booking(
        s["venue"]["id"], guest["id"], s["tee_session"]["id"], s["plan"]["id"],
        party_size=4, units=2, combo_pass_id=pass_["id"],
    )
    confirmed = confirm_booking_tee(bk["id"], s["tee_session"]["version"])
    # gross 9600; billable_units = 2*4 = 8; credits_applied = min(5,8) = 5;
    # credit_value = round(9600*5/8) = 6000; cash_due = 3600.
    assert confirmed["gross_price_cents"] == 9600
    assert confirmed["credits_applied"] == 5, f"expected 5 credits applied, got {confirmed['credits_applied']}"
    assert confirmed["cash_due_cents"] == 3600, f"expected 3600 cash due, got {confirmed['cash_due_cents']}"


def test_loyalty_threshold_exact_boundary_earns_bonus(api):
    """PRD §3.4: "if the guest's total_loaded_cents before this top-up is below
    5000 cents and the total after adding this top-up's amount reaches or exceeds
    5000 cents, then this is the threshold-crossing top-up and it earns a bonus
    equal to ten percent of that single top-up's amount, rounded half up".

    Design: Corner/calculations/loyalty_threshold_exact_boundary_earns_bonus
    """
    g1 = create_guest(full_name="Exact", height_cm=175, as_role="cashier")
    w1 = get_wallet_for_guest(g1["id"])
    g2 = create_guest(full_name="Below", height_cm=175, as_role="cashier")
    w2 = get_wallet_for_guest(g2["id"])

    w1 = validate_success(api.top_up_wallet(w1["id"], top_up_payload(5000), CASHIER), 200)
    w2 = validate_success(api.top_up_wallet(w2["id"], top_up_payload(4999), CASHIER), 200)

    assert w1["arcade_card_balance_cents"] == 5500, (
        f"5000 reaches threshold -> +10% bonus 500; expected 5500, got {w1['arcade_card_balance_cents']}"
    )
    assert w2["arcade_card_balance_cents"] == 4999, (
        f"4999 below threshold -> no bonus; expected 4999, got {w2['arcade_card_balance_cents']}"
    )


def test_waiver_expiry_makes_status_expired(api):
    """PRD §3.3: "Signing a waiver for a guest records its guest_id, stamps
    signed_at with the venue's current clock value at the moment of signing, and
    computes expires_at as exactly 365 days after signed_at".
    PRD §3.3: "report ... EXPIRED when the venue's current_utc is at or after that
    waiver's expires_at, and SIGNED otherwise."

    Design: Corner/calculations/waiver_expiry_makes_status_expired
    """
    venue = validate_success(api.create_venue(create_venue_payload(name="V"), OPS), 201)
    validate_success(api.set_venue_clock(venue["id"], {"to_iso8601": "2026-06-14T09:00:00Z"}, OPS), 200)
    guest = validate_success(api.create_guest(
        create_guest_payload(full_name="G", height_cm=175, birthdate="1990-01-01"), OPS), 201)
    validate_success(api.create_waiver(create_waiver_payload(guest["id"]), OPS), 201)
    # Advance the clock past signed_at + 365 days.
    validate_success(api.set_venue_clock(venue["id"], {"to_iso8601": "2027-06-15T09:00:00Z"}, OPS), 200)

    refreshed = validate_success(api.get_guest(guest["id"], OPS), 200)
    assert refreshed["waiver_status"] == "EXPIRED", (
        f"expected EXPIRED after one year, got {refreshed['waiver_status']}"
    )


# ───────────────────────── Corner: consistency_model ─────────────────────────

def test_confirm_response_reflects_final_price_immediately(api):
    """PRD §2.4: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data field."
    PRD §3.6: "its gross_price_cents is recomputed in the final manner, combo
    credits are applied to set credits_applied and cash_due_cents".

    Design: Corner/consistency_model/confirm_response_reflects_final_price_immediately
    """
    s = setup_open_heat_scenario(lane_count=5, base_price_cents=1500, mode="PER_HEAT", window="OFF_PEAK")
    guest = make_signed_guest(height_cm=180)
    bk = create_heat_hold_booking(
        s["venue"]["id"], guest["id"], s["heat"]["id"], s["plan"]["id"], party_size=2
    )
    confirmed = validate_success(
        api.confirm_booking(bk["id"], {"expected_heat_version": s["heat"]["version"]}, OPS), 200
    )
    # 1500 * 1 * 2 OFF_PEAK, no combo: gross == cash == 3000, in the confirm body.
    assert confirmed["gross_price_cents"] == 3000
    assert confirmed["cash_due_cents"] == 3000
    assert confirmed["status"] == "CONFIRMED"
