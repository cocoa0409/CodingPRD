"""Nightly-rate rounding, forward vs chronological room charges, folio balance
provisional-vs-final, package fee, and the corporate credit evaluation order.

Difficulty queue: dual_variant_calc, combinatorial_formula.
Corner queue (calculations): package fee once, comp upgrade leaves projection.
"""
from test_helpers import (
    api_client as _api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    setup_basic,
    setup_corporate,
    corporate_bundle_as_basic,
    create_hotel,
    create_room_type,
    create_rate_plan,
    create_guest,
    create_inspected_room,
    create_held_reservation,
    create_confirmed_reservation,
    create_assigned_reservation,
    create_checked_in_reservation,
    get_folio_for_reservation,
    get_hotel_version,
    open_audit,
    complete_audit,
    run_one_audit,
)
api = _api_client
RM = TEST_USERS["revenue_manager_headers"]
FDA = TEST_USERS["front_desk_headers"]
NA = TEST_USERS["night_auditor_headers"]


def _folio(hotel_id, res_id):
    return get_folio_for_reservation(hotel_id, res_id)


# ===========================================================================
# Difficulty/dual_variant_calc/room_charge_forward_vs_chronological_diverge_on_upgrade
# ===========================================================================
def test_forward_projection_pinned_at_confirm_king_only():
    """PRD §3.6: "It computes the nightly rate of §3.4 for the rate plan against the
    room type effective at that moment, multiplies it by the reservation's `nights`, and,
    when the rate plan's `kind` is `PACKAGE`, adds the `package_fee_cents` once for the
    whole stay. The result is stored as `projected_charges_cents`."

    KING base 20000, BAR PCT -15 -> nightly round_half_up(20000*0.85)=17000; *2 nights = 34000.

    Design: Difficulty/dual_variant_calc/room_charge_forward_vs_chronological_diverge_on_upgrade
    """
    hotel = create_hotel(current_business_date="2026-07-01", overbooking_allowance_pct=0.0)
    king = create_room_type(hotel["id"], code="KING", tier_rank=1,
                            physical_inventory=3, base_rate_cents=20000)
    create_room_type(hotel["id"], code="SUITE", tier_rank=2,
                     physical_inventory=3, base_rate_cents=30000)
    bar = create_rate_plan(hotel["id"], code="BAR", kind="BAR",
                           adjustment_mode="PCT", adjustment_value=-15, no_show_policy="NONE")
    guest = create_guest(hotel["id"])
    res = get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": king["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-03"}, FDA))
    folio_id = _folio(hotel["id"], res["id"])["id"]
    validate_success(api.confirm_reservation(res["id"], FDA))

    folio = validate_success(api.get_folio(folio_id, FDA))
    assert folio["projected_charges_cents"] == 34000, folio


def test_chronological_accrual_diverges_from_forward_after_midstay_upgrade():
    """PRD §3.8: "Because each night is posted at the rate in effect that night, a
    mid-stay upgrade changes only the nights posted after it and leaves already-posted
    nights untouched — so the chronological accrual diverges from the single-snapshot
    forward projection whenever an upgrade lands mid-stay."

    Chronological accrual: KING night1 17000 + SUITE night2 25500 = 42500.
    Forward projection: PRD §3.5 — "When the upgrade is not complimentary, the folio's
    forward projection is recomputed at the higher rate using the forward room-charge
    calculation of §3.6." A paid upgrade to SUITE thus repins the projection to
    SUITE nightly 25500 * 2 nights = 51000. 51000 != 42500, so the two variants diverge.

    Design: Difficulty/dual_variant_calc/room_charge_forward_vs_chronological_diverge_on_upgrade
    """
    hotel = create_hotel(current_business_date="2026-07-01", overbooking_allowance_pct=0.0)
    king = create_room_type(hotel["id"], code="KING", tier_rank=1,
                            physical_inventory=3, base_rate_cents=20000)
    suite = create_room_type(hotel["id"], code="SUITE", tier_rank=2,
                             physical_inventory=3, base_rate_cents=30000)
    bar = create_rate_plan(hotel["id"], code="BAR", kind="BAR",
                           adjustment_mode="PCT", adjustment_value=-15, no_show_policy="NONE")
    # SUITE room so the upgraded reservation can occupy a SUITE-tier room.
    room = create_inspected_room(hotel["id"], suite["id"], room_number="501")
    guest = create_guest(hotel["id"])
    res = get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": king["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-03"}, FDA))
    folio_id = _folio(hotel["id"], res["id"])["id"]
    get_success_data(api.confirm_reservation(res["id"], FDA))
    get_success_data(api.assign_room(res["id"],
        {"room_id": room["id"], "expected_room_version": room["version"]}, FDA))
    get_success_data(api.check_in(res["id"], FDA))
    # First night audit: posts night-1 KING charge (17000).
    run_one_audit(hotel["id"])
    # Mid-stay paid upgrade to SUITE before the second audited night.
    get_success_data(api.upgrade_reservation(res["id"],
        {"target_room_type_id": suite["id"], "comp": False}, FDA))
    # Second night audit: posts night-2 SUITE charge (25500).
    run_one_audit(hotel["id"])

    folio = validate_success(api.get_folio(folio_id, FDA))
    assert folio["projected_charges_cents"] == 51000, folio
    assert folio["room_charges_cents"] == 42500, folio
    assert folio["projected_charges_cents"] != folio["room_charges_cents"], folio


# ===========================================================================
# Difficulty/dual_variant_calc/folio_balance_provisional_open_vs_final_closed
# ===========================================================================
def test_folio_provisional_open_balance_after_one_audited_night():
    """PRD §3.6: "While the folio is `OPEN` before check-out, the balance is provisional,
    reflecting only the nights and lines posted so far and still mutable".

    One audited night of a 2-night KING BAR -15 stay: room_charges 17000 while OPEN.

    Design: Difficulty/dual_variant_calc/folio_balance_provisional_open_vs_final_closed
    """
    hotel = create_hotel(current_business_date="2026-07-01", overbooking_allowance_pct=0.0)
    king = create_room_type(hotel["id"], code="KING", tier_rank=1,
                            physical_inventory=3, base_rate_cents=20000)
    bar = create_rate_plan(hotel["id"], code="BAR", kind="BAR",
                           adjustment_mode="PCT", adjustment_value=-15, no_show_policy="NONE")
    room = create_inspected_room(hotel["id"], king["id"], room_number="101")
    guest = create_guest(hotel["id"])
    res = get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": king["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-03"}, FDA))
    folio_id = _folio(hotel["id"], res["id"])["id"]
    get_success_data(api.confirm_reservation(res["id"], FDA))
    get_success_data(api.assign_room(res["id"],
        {"room_id": room["id"], "expected_room_version": room["version"]}, FDA))
    get_success_data(api.check_in(res["id"], FDA))
    run_one_audit(hotel["id"])

    folio = validate_success(api.get_folio(folio_id, FDA))
    assert folio["status"] == "OPEN", folio
    assert folio["balance_cents"] == 17000, folio


def test_folio_final_closed_balance_after_checkout():
    """PRD §3.6: "at and after the close that fires on check-out, no-show, or cancel, the
    balance is frozen at that instant as the total of all posted room charges and
    incidentals, and no later posting alters it."

    Both nights audited then checkout: room_charges 34000, status CLOSED.

    Design: Difficulty/dual_variant_calc/folio_balance_provisional_open_vs_final_closed
    """
    hotel = create_hotel(current_business_date="2026-07-01", overbooking_allowance_pct=0.0)
    king = create_room_type(hotel["id"], code="KING", tier_rank=1,
                            physical_inventory=3, base_rate_cents=20000)
    bar = create_rate_plan(hotel["id"], code="BAR", kind="BAR",
                           adjustment_mode="PCT", adjustment_value=-15, no_show_policy="NONE")
    room = create_inspected_room(hotel["id"], king["id"], room_number="101")
    guest = create_guest(hotel["id"])
    res = get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": king["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-03"}, FDA))
    folio_id = _folio(hotel["id"], res["id"])["id"]
    get_success_data(api.confirm_reservation(res["id"], FDA))
    get_success_data(api.assign_room(res["id"],
        {"room_id": room["id"], "expected_room_version": room["version"]}, FDA))
    get_success_data(api.check_in(res["id"], FDA))
    run_one_audit(hotel["id"])  # night 1
    run_one_audit(hotel["id"])  # night 2
    validate_success(api.check_out(res["id"], FDA))

    folio = validate_success(api.get_folio(folio_id, FDA))
    assert folio["balance_cents"] == 34000, folio
    assert folio["status"] == "CLOSED", folio


# ===========================================================================
# Difficulty/combinatorial_formula/nightly_rate_pct_round_then_multiply_order
# ===========================================================================
def test_nightly_rate_round_per_night_then_multiply():
    """PRD §3.4: "that per-night figure is rounded half up to a whole number of cents
    before it is multiplied by the number of nights: the rate is rounded per night first
    and then multiplied, never summed and then rounded."

    base 13333, PCT -15 -> round_half_up(13333*0.85)=round_half_up(11333.05)=11333;
    *3 nights = 33999.

    Design: Difficulty/combinatorial_formula/nightly_rate_pct_round_then_multiply_order
    """
    hotel = create_hotel(current_business_date="2026-07-01", overbooking_allowance_pct=0.0)
    std = create_room_type(hotel["id"], code="STD", tier_rank=1,
                           physical_inventory=5, base_rate_cents=13333)
    bar = create_rate_plan(hotel["id"], code="BAR", kind="BAR",
                           adjustment_mode="PCT", adjustment_value=-15, no_show_policy="NONE")
    guest = create_guest(hotel["id"])
    res = get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": std["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-04"}, FDA))
    folio_id = _folio(hotel["id"], res["id"])["id"]
    validate_success(api.confirm_reservation(res["id"], FDA))

    folio = validate_success(api.get_folio(folio_id, FDA))
    assert folio["projected_charges_cents"] == 33999, folio


def test_reservation_nights_computed_for_three_night_stay():
    """PRD §3.3: "The server computes `nights` as the number of days from `arrival_date`
    to `departure_date` (which must be at least 1)".

    2026-07-01..2026-07-04 -> nights == 3.

    Design: Difficulty/combinatorial_formula/nightly_rate_pct_round_then_multiply_order
    """
    hotel = create_hotel(current_business_date="2026-07-01", overbooking_allowance_pct=0.0)
    std = create_room_type(hotel["id"], code="STD", tier_rank=1,
                           physical_inventory=5, base_rate_cents=13333)
    bar = create_rate_plan(hotel["id"], code="BAR", kind="BAR",
                           adjustment_mode="PCT", adjustment_value=-15, no_show_policy="NONE")
    guest = create_guest(hotel["id"])
    res = validate_success(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": std["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-04"}, FDA), expected_status=201)
    assert res["nights"] == 3, res


# ===========================================================================
# Difficulty/combinatorial_formula/corporate_credit_eval_order_outstanding_plus_projection
# ===========================================================================
def test_corporate_credit_gate_sums_outstanding_then_projection():
    """PRD §3.7: "the system computes a forward projection — the corporate account's
    current `outstanding_balance_cents` plus the folio's `projected_charges_cents` for the
    reservation being confirmed — and rejects the confirmation when that projected total
    is strictly greater than the account's `credit_limit_cents`, returning
    `ERR_CREDIT_LIMIT_EXCEEDED` (HTTP 402)."

    outstanding 40000 + projection 40000 = 80000 > limit 50000 -> rejected.

    Design: Difficulty/combinatorial_formula/corporate_credit_eval_order_outstanding_plus_projection
    """
    b = setup_corporate(credit_limit_cents=50000, base_rate_cents=20000,
                        physical_inventory=5, adjustment_value=0)
    hotel_id = b["hotel"]["id"]
    acct = b["account"]
    basic = corporate_bundle_as_basic(b)
    # First corporate stay: 2 nights FLAT base 20000 = 40000 room, + minibar 40000? No:
    # the YAML posts a 40000 CHARGE incidental then checks out to set outstanding 40000.
    room = create_inspected_room(hotel_id, b["room_type"]["id"], room_number="201")
    res1 = get_success_data(api.create_reservation({
        "hotel_id": hotel_id, "guest_id": b["guest"]["id"],
        "room_type_id": b["room_type"]["id"], "rate_plan_id": b["rate_plan"]["id"],
        "arrival_date": "2026-07-01", "departure_date": "2026-07-03"}, FDA))
    folio1_id = _folio(hotel_id, res1["id"])["id"]
    get_success_data(api.confirm_reservation(res1["id"], FDA))
    get_success_data(api.assign_room(res1["id"],
        {"room_id": room["id"], "expected_room_version": room["version"]}, FDA))
    get_success_data(api.check_in(res1["id"], FDA))
    get_success_data(api.create_incidental({
        "hotel_id": hotel_id, "folio_id": folio1_id, "kind": "CHARGE",
        "description": "Room block", "amount_cents": 40000}, FDA))
    get_success_data(api.check_out(res1["id"], FDA))

    # Second corporate reservation, 2 nights -> projection 40000.
    guest2 = create_guest(hotel_id, full_name="Dee D")
    res2 = get_success_data(api.create_reservation({
        "hotel_id": hotel_id, "guest_id": guest2["id"],
        "room_type_id": b["room_type"]["id"], "rate_plan_id": b["rate_plan"]["id"],
        "arrival_date": "2026-07-05", "departure_date": "2026-07-07"}, FDA))

    resp = api.confirm_reservation(res2["id"], FDA)
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)
    acct_after = validate_success(api.get_corporate_account(acct["id"], RM))
    assert acct_after["outstanding_balance_cents"] == 40000, acct_after
    res2_after = validate_success(api.get_reservation(res2["id"], FDA))
    assert res2_after["status"] == "HELD", res2_after


def test_corporate_credit_gate_outstanding_balance_reflects_checked_out_stay():
    """PRD §3.7: "The account's `outstanding_balance_cents` itself is the sum of the
    `balance_cents` of every folio that is billed to the account — that is, every folio
    whose `bill_to` is `CORPORATE` and whose reservation's `corporate_account_id` is this
    account and whose reservation has reached `CHECKED_OUT`."

    After one checked-out corporate stay with a 40000 charge, outstanding == 40000.

    Design: Difficulty/combinatorial_formula/corporate_credit_eval_order_outstanding_plus_projection
    """
    b = setup_corporate(credit_limit_cents=50000, base_rate_cents=20000,
                        physical_inventory=5, adjustment_value=0)
    hotel_id = b["hotel"]["id"]
    room = create_inspected_room(hotel_id, b["room_type"]["id"], room_number="201")
    res1 = get_success_data(api.create_reservation({
        "hotel_id": hotel_id, "guest_id": b["guest"]["id"],
        "room_type_id": b["room_type"]["id"], "rate_plan_id": b["rate_plan"]["id"],
        "arrival_date": "2026-07-01", "departure_date": "2026-07-03"}, FDA))
    folio1_id = _folio(hotel_id, res1["id"])["id"]
    get_success_data(api.confirm_reservation(res1["id"], FDA))
    get_success_data(api.assign_room(res1["id"],
        {"room_id": room["id"], "expected_room_version": room["version"]}, FDA))
    get_success_data(api.check_in(res1["id"], FDA))
    get_success_data(api.create_incidental({
        "hotel_id": hotel_id, "folio_id": folio1_id, "kind": "CHARGE",
        "description": "Room block", "amount_cents": 40000}, FDA))
    get_success_data(api.check_out(res1["id"], FDA))

    acct_after = validate_success(api.get_corporate_account(b["account"]["id"], RM))
    assert acct_after["outstanding_balance_cents"] == 40000, acct_after


# ===========================================================================
# Corner/calculations/package_rate_plan_adds_per_stay_fee_once
# ===========================================================================
def test_package_plan_adds_per_stay_fee_once():
    """PRD §3.6: "when the rate plan's `kind` is `PACKAGE`, adds the `package_fee_cents`
    once for the whole stay. The result is stored as `projected_charges_cents`."

    PACKAGE FLAT+0 base 20000, package_fee 5000, 2 nights -> 20000*2 + 5000 == 45000.

    Design: Corner/calculations/package_rate_plan_adds_per_stay_fee_once
    """
    hotel = create_hotel(current_business_date="2026-07-01")
    king = create_room_type(hotel["id"], code="KING", tier_rank=1,
                            physical_inventory=3, base_rate_cents=20000)
    pkg = create_rate_plan(hotel["id"], code="PKG", kind="PACKAGE",
                           adjustment_mode="FLAT", adjustment_value=0,
                           no_show_policy="NONE", package_fee_cents=5000)
    guest = create_guest(hotel["id"])
    res = get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": king["id"],
        "rate_plan_id": pkg["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-03"}, FDA))
    folio_id = _folio(hotel["id"], res["id"])["id"]
    validate_success(api.confirm_reservation(res["id"], FDA))

    folio = validate_success(api.get_folio(folio_id, FDA))
    assert folio["projected_charges_cents"] == 45000, folio


# ===========================================================================
# Corner/calculations/comp_upgrade_does_not_change_projection
# ===========================================================================
def test_comp_upgrade_leaves_projection_unchanged():
    """PRD §3.5: "an upgrade marked complimentary carries no rate change."
    PRD §3.5: "The upgrade sets the reservation's `effective_room_type_id` to the target
    type, sets `is_upgraded` to true, and records `upgrade_is_comp` from the `comp` flag."

    Confirmed KING 2 nights BAR -15 (projected 34000); comp upgrade to SUITE leaves it 34000.

    Design: Corner/calculations/comp_upgrade_does_not_change_projection
    """
    hotel = create_hotel(current_business_date="2026-07-01")
    king = create_room_type(hotel["id"], code="KING", tier_rank=1,
                            physical_inventory=3, base_rate_cents=20000)
    suite = create_room_type(hotel["id"], code="SUITE", tier_rank=2,
                             physical_inventory=3, base_rate_cents=30000)
    bar = create_rate_plan(hotel["id"], code="BAR", kind="BAR",
                           adjustment_mode="PCT", adjustment_value=-15, no_show_policy="NONE")
    guest = create_guest(hotel["id"], full_name="Lm L", loyalty_tier="PLATINUM")
    res = get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": king["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-01",
        "departure_date": "2026-07-03"}, FDA))
    folio_id = _folio(hotel["id"], res["id"])["id"]
    get_success_data(api.confirm_reservation(res["id"], FDA))

    upgraded = validate_success(api.upgrade_reservation(res["id"],
        {"target_room_type_id": suite["id"], "comp": True}, FDA))
    assert upgraded["is_upgraded"] is True, upgraded
    assert upgraded["upgrade_is_comp"] is True, upgraded
    assert upgraded["effective_room_type_id"] == suite["id"], upgraded
    folio = validate_success(api.get_folio(folio_id, FDA))
    assert folio["projected_charges_cents"] == 34000, folio


# ===========================================================================
# Corner/calculations/no_show_first_night_policy_charge
# ===========================================================================
def test_no_show_first_night_policy_charges_one_nightly():
    """PRD §3.8: "Under `FIRST_NIGHT` the charge is exactly one nightly rate."
    PRD §3.8: "the nightly rate of §3.4 is resolved first for the rate plan against the
    reservation's booked `room_type_id`, and then the policy multiplier keyed off the rate
    plan's `no_show_policy` is applied."

    QUEEN base 15000, BAR PCT -10 -> nightly 13500; a 3-night FIRST_NIGHT no-show posts 13500.

    Design: Corner/calculations/no_show_first_night_policy_charge
    """
    hotel = create_hotel(current_business_date="2026-07-10")
    queen = create_room_type(hotel["id"], code="QUEEN", tier_rank=1,
                             physical_inventory=5, base_rate_cents=15000)
    bar = create_rate_plan(hotel["id"], code="BAR", kind="BAR",
                           adjustment_mode="PCT", adjustment_value=-10,
                           no_show_policy="FIRST_NIGHT")
    guest = create_guest(hotel["id"])
    res = get_success_data(api.create_reservation({
        "hotel_id": hotel["id"], "guest_id": guest["id"], "room_type_id": queen["id"],
        "rate_plan_id": bar["id"], "arrival_date": "2026-07-10",
        "departure_date": "2026-07-13"}, FDA))
    folio_id = _folio(hotel["id"], res["id"])["id"]
    get_success_data(api.confirm_reservation(res["id"], FDA))
    run_one_audit(hotel["id"])

    res_after = validate_success(api.get_reservation(res["id"], FDA))
    assert res_after["status"] == "NO_SHOW", res_after
    folio = validate_success(api.get_folio(folio_id, FDA))
    assert folio["room_charges_cents"] == 13500, folio
