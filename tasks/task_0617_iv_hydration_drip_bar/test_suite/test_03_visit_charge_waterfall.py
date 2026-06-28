"""The visit-charge waterfall at schedule time: discount fractions, credit
waterfall, per-line round-half-up then sum, and the mobile surcharge.

Covers the dual-variant cash-vs-member-credit difficulty instance, the
combinatorial round-per-line difficulty instance, the GOLD single-line corner,
and the immediate-consistency corner.
"""
import pytest
from test_helpers import (
    get_success_data, validate_success,
    set_clock, create_menu_item, create_lounge, create_patient, create_membership,
    create_add_on, create_supply_lot, create_active_standing_order,
    create_requested_appointment, submit_intake, sign_consent, current_version,
    schedule_appointment, setup_cleared_lounge_ready_to_schedule,
    TEST_USERS,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["clinic_admin_headers"]
FAR_EXPIRY = "2026-12-31T00:00:00Z"


# ─── Difficulty: dual_variant_calc / dv_visit_charge_cash_vs_member_credit ───
def test_visit_charge_cash_visit_full_list_price(api):
    """PRD §3.11: "For a cash visit (no membership, or a membership that is not `ACTIVE`)
    the discount fraction is 0, no credits are consumed, every line is charged at full
    list price, and the mobile surcharge still applies for a mobile visit."

    A cash NAD ($650) + glutathione ($45) + b12 ($25) LOUNGE visit = 72000 cents,
    drip_credit_used 0.

    Design: Difficulty/dual_variant_calc/dv_visit_charge_cash_vs_member_credit
    """
    set_clock("2026-06-22T00:00:00Z")
    nad = create_menu_item(name="NAD+", tier="NAD", base_price_cents=65000,
                           requires_standing_order=True, g6pd_sensitive=False)
    glut = create_add_on(name="Glutathione Push", code="GLUTATHIONE", price_cents=4500)
    b12 = create_add_on(name="B12 Boost", code="B12", price_cents=2500)
    lounge = create_lounge(name="Downtown", bay_count=2)
    create_supply_lot(item_kind="DRIP_BASE", tier_or_code="NAD", lot_number="NAD-L1",
                      units_total=10, expires_at=FAR_EXPIRY)
    create_supply_lot(item_kind="ADDON", tier_or_code="GLUTATHIONE", lot_number="GLU-L1",
                      units_total=10, expires_at=FAR_EXPIRY)
    create_supply_lot(item_kind="ADDON", tier_or_code="B12", lot_number="B12-L1",
                      units_total=10, expires_at=FAR_EXPIRY)
    create_active_standing_order(covered_tier="NAD", md_user_id="md-1")

    patient = create_patient(full_name="Cash Pat")
    appt = create_requested_appointment(
        patient["id"], nad["id"], addon_ids=[glut["id"], b12["id"]],
        location_type="LOUNGE", lounge_id=lounge["id"], start_at="2026-06-23T09:00:00Z",
        duration_minutes=60)
    submit_intake(appt["id"])
    sign_consent(appt["id"])
    scheduled = schedule_appointment(appt["id"])
    assert scheduled["amount_charged_cents"] == 72000, \
        f"expected 72000, got {scheduled['amount_charged_cents']}"
    assert scheduled["drip_credit_used"] == 0


def test_visit_charge_member_credit_visit_with_mobile_surcharge(api):
    """PRD §3.11: the credit waterfall covers the drip and leading add-ons in order, the
    uncovered add-on is discounted cash, and "A mobile surcharge of 9,500 cents is then
    added when `location_type` is `MOBILE` ... this surcharge is never discounted and
    never coverable by a credit."

    PLATINUM (0.225) NAD + [glutathione,b12] MOBILE, 1 drip + 1 addon credit: drip and
    glutathione credit-covered, b12 cash = round_half_up(2500*0.775)=1938, +9500 mobile =
    11438; drip_credit_used 1, addon_credits_used 1; both remaining pools drop to 0.

    Design: Difficulty/dual_variant_calc/dv_visit_charge_cash_vs_member_credit
    """
    set_clock("2026-06-22T00:00:00Z")
    nad = create_menu_item(name="NAD+", tier="NAD", base_price_cents=65000,
                           requires_standing_order=True, g6pd_sensitive=False)
    glut = create_add_on(name="Glutathione Push", code="GLUTATHIONE", price_cents=4500)
    b12 = create_add_on(name="B12 Boost", code="B12", price_cents=2500)
    create_supply_lot(item_kind="DRIP_BASE", tier_or_code="NAD", lot_number="NAD-L1",
                      units_total=10, expires_at=FAR_EXPIRY)
    create_supply_lot(item_kind="ADDON", tier_or_code="GLUTATHIONE", lot_number="GLU-L1",
                      units_total=10, expires_at=FAR_EXPIRY)
    create_supply_lot(item_kind="ADDON", tier_or_code="B12", lot_number="B12-L1",
                      units_total=10, expires_at=FAR_EXPIRY)
    create_active_standing_order(covered_tier="NAD", md_user_id="md-1")

    mem = create_membership(tier="PLATINUM", covered_drip_tier="NAD",
                            drip_credits_total=1, addon_credits_total=1)
    patient = create_patient(full_name="Member Pat", membership_id=mem["id"])
    appt = create_requested_appointment(
        patient["id"], nad["id"], addon_ids=[glut["id"], b12["id"]],
        location_type="MOBILE", start_at="2026-06-23T13:00:00Z",
        duration_minutes=60, membership_id=mem["id"])
    submit_intake(appt["id"])
    sign_consent(appt["id"])
    scheduled = schedule_appointment(appt["id"])

    assert scheduled["amount_charged_cents"] == 11438, \
        f"expected 11438, got {scheduled['amount_charged_cents']}"
    assert scheduled["drip_credit_used"] == 1
    assert scheduled["addon_credits_used"] == 1
    mem_after = get_success_data(api_client.get_membership(mem["id"], ADMIN))
    assert mem_after["drip_credits_remaining"] == 0
    assert mem_after["addon_credits_remaining"] == 0


# ─── Difficulty: combinatorial_formula / combo_visit_charge_round_per_line_then_sum ───
def test_visit_charge_rounds_per_line_then_sums(api):
    """PRD §2.8: "the discounted line amount is rounded half up to the nearest whole cent,
    and the rounding is applied to each individual line before the lines are summed —
    never to a running subtotal after summation."

    PLATINUM (0.225) on MYERS+[glut,b12,zofran] with zero credits, every line discounted
    cash: round_half_up per line (13563+3488+1938+2325) = 21314 (summing-then-rounding-once
    would give 21313).

    Design: Difficulty/combinatorial_formula/combo_visit_charge_round_per_line_then_sum
    """
    set_clock("2026-06-22T00:00:00Z")
    myers = create_menu_item(name="Myers", tier="MYERS", base_price_cents=17500,
                             requires_standing_order=False)
    glut = create_add_on(name="Glutathione", code="GLUTATHIONE", price_cents=4500)
    b12 = create_add_on(name="B12", code="B12", price_cents=2500)
    zof = create_add_on(name="Zofran", code="ZOFRAN", price_cents=3000)
    lounge = create_lounge(bay_count=3)
    for kind, code, lot in (("DRIP_BASE", "MYERS", "MY-1"), ("ADDON", "GLUTATHIONE", "GL-1"),
                            ("ADDON", "B12", "B-1"), ("ADDON", "ZOFRAN", "Z-1")):
        create_supply_lot(item_kind=kind, tier_or_code=code, lot_number=lot,
                          units_total=10, expires_at=FAR_EXPIRY)
    mem = create_membership(tier="PLATINUM", covered_drip_tier="MYERS",
                            drip_credits_total=0, addon_credits_total=0)
    patient = create_patient(full_name="Plat Pat", membership_id=mem["id"])
    appt = create_requested_appointment(
        patient["id"], myers["id"], addon_ids=[glut["id"], b12["id"], zof["id"]],
        location_type="LOUNGE", lounge_id=lounge["id"], start_at="2026-06-23T09:00:00Z",
        membership_id=mem["id"])
    submit_intake(appt["id"])
    sign_consent(appt["id"])
    scheduled = schedule_appointment(appt["id"])
    assert scheduled["amount_charged_cents"] == 21314, \
        f"expected 21314 (round-per-line), got {scheduled['amount_charged_cents']}"
    assert scheduled["drip_credit_used"] == 0
    assert scheduled["addon_credits_used"] == 0


def test_visit_charge_platinum_single_line_round_half_up(api):
    """PRD §3.11: "Each cash line's amount is its list price ... multiplied by one minus
    the discount fraction, rounded half up to a whole cent — rounded per line".
    PRD §3.11: "a `PLATINUM` membership yields 0.225."

    A single MYERS ($175) drip, no add-ons, PLATINUM but with covered_drip_tier=NAD (so
    drip is NOT credit-covered) and 0 credits: round_half_up(17500*0.775)=13563.

    Design: Difficulty/combinatorial_formula/combo_visit_charge_round_per_line_then_sum
    """
    ctx = setup_cleared_lounge_ready_to_schedule(
        menu_overrides={"tier": "MYERS", "base_price_cents": 17500,
                        "requires_standing_order": False},
        membership_overrides={"tier": "PLATINUM", "covered_drip_tier": "NAD",
                              "drip_credits_total": 0, "addon_credits_total": 0})
    scheduled = schedule_appointment(ctx["appointment"]["id"], ctx["version"])
    assert scheduled["amount_charged_cents"] == 13563, \
        f"expected 13563, got {scheduled['amount_charged_cents']}"
    assert scheduled["drip_credit_used"] == 0


# ─── Corner: calculations / gold_discount_single_line_correct ───
def test_gold_discount_single_line_correct(api):
    """PRD §3.11: "a `GOLD` membership yields 0.150" and each cash line is "its list price
    ... multiplied by one minus the discount fraction, rounded half up to a whole cent".

    GOLD (covered_drip_tier=NAD so MYERS drip NOT credit-covered) on a single MYERS drip:
    round_half_up(17500*0.85) = 14875.

    Design: Corner/calculations/gold_discount_single_line_correct
    """
    ctx = setup_cleared_lounge_ready_to_schedule(
        menu_overrides={"tier": "MYERS", "base_price_cents": 17500,
                        "requires_standing_order": False},
        membership_overrides={"tier": "GOLD", "covered_drip_tier": "NAD",
                              "drip_credits_total": 0, "addon_credits_total": 0})
    scheduled = schedule_appointment(ctx["appointment"]["id"], ctx["version"])
    assert scheduled["amount_charged_cents"] == 14875, \
        f"expected 14875, got {scheduled['amount_charged_cents']}"
    assert scheduled["drip_credit_used"] == 0


# ─── Corner: consistency_model / immediate_charge_visible_in_schedule_response ───
def test_amount_charged_visible_in_schedule_response(api):
    """PRD §3.7: "On success the system reserves one unit on the FEFO-chosen lot ...
    computes `amount_charged_cents` via the visit-charge waterfall (§3.11) and decrements
    the membership credits accordingly, sets `status` to `SCHEDULED`".

    A full-price cash MYERS LOUNGE visit charges exactly 17500, visible in the same
    schedule response.

    Design: Corner/consistency_model/immediate_charge_visible_in_schedule_response
    """
    ctx = setup_cleared_lounge_ready_to_schedule(
        menu_overrides={"tier": "MYERS", "base_price_cents": 17500,
                        "requires_standing_order": False})
    scheduled = schedule_appointment(ctx["appointment"]["id"], ctx["version"])
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["amount_charged_cents"] == 17500, \
        f"expected 17500, got {scheduled['amount_charged_cents']}"
