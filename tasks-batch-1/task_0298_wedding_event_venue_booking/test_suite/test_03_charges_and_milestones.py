"""Provisional vs final event charge, the F&B-floor service-then-tax nesting,
the milestone waterfall split, and derived balance reconciliation.

Translates difficulty rules `dual_variant_calc` and `combinatorial_formula`, plus
corner `calculations` and `cross_cutting` derived-field instances. Charge figures
are copied verbatim from the design indices (pre-computed there).
"""
from test_helpers import (
    validate_success,
    get_success_data,
    TEST_USERS,
    PROVISIONAL,
    FINAL,
    create_guarantee_payload,
    create_payment_payload,
    setup_confirmed_booking,
    setup_confirmed_with_cleared_vendor,
    get_milestones,
)

FO = TEST_USERS["finance_officer_headers"]


# ───────────── Rule 1: dual_variant_calc — provisional vs final ─────────────

def test_provisional_charge_on_confirm_with_fb_floor(api):
    """PRD §3.4: "the food-and-beverage subtotal is the larger of that head count
    multiplied by the package's `per_head_cents` and the package's
    `fb_minimum_cents` (so the minimum floor binds whenever the per-head total
    falls short)."
    PRD §3.4: "The provisional `event_charge_cents` is the food-and-beverage
    subtotal plus the service charge plus the tax plus the rental."

    Design: Difficulty/dual_variant_calc/provisional_vs_final_event_charge_on_booking
    """
    inv, booking = setup_confirmed_booking()
    # 120 heads * 15000 = 1_800_000 < 2_000_000 floor → floor binds.
    assert booking["event_charge_cents"] == PROVISIONAL["EVENT_CHARGE"] == 3_135_200


def test_guarantee_switches_to_final_charge_distinct_from_provisional(api):
    """PRD §3.7: "the billable head count is `guaranteed_count`; the
    food-and-beverage subtotal is the larger of that count multiplied by
    `per_head_cents` and the package's `fb_minimum_cents`".
    PRD §3.7: "The final `event_charge_cents` is the subtotal plus the service
    charge plus the tax plus the rental, and it differs from the provisional figure
    whenever `guaranteed_count` differs from `expected_guest_count`".

    Design: Difficulty/dual_variant_calc/provisional_vs_final_event_charge_on_booking
    """
    inv, booking = setup_confirmed_with_cleared_vendor()[:2]
    assert booking["event_charge_cents"] == PROVISIONAL["EVENT_CHARGE"]
    guaranteed = get_success_data(api.guarantee_booking(
        booking["id"], create_guarantee_payload(150), inv["coord_headers"]))
    # 150 heads * 15000 = 2_250_000 > 2_000_000 floor → per-head binds.
    assert guaranteed["event_charge_cents"] == FINAL["EVENT_CHARGE"] == 3_464_600
    assert guaranteed["event_charge_cents"] != PROVISIONAL["EVENT_CHARGE"]


# ───────────── Rule 2 mode (a): combinatorial F&B floor + service-then-tax ─────────────

def test_fb_floor_max_with_service_then_tax_components(api):
    """PRD §3.4: "The service charge equals the food-and-beverage subtotal
    multiplied by `service_charge_pct`, rounded half up to whole cents. The taxed
    base is the food-and-beverage subtotal plus that service charge, and the tax
    equals the taxed base multiplied by `tax_pct`, rounded half up to whole cents —
    service first, then tax on the serviced amount, in that pinned order."

    Design: Difficulty/combinatorial_formula/fb_floor_max_with_service_then_tax_nesting
    """
    inv, booking = setup_confirmed_booking()
    # service = round(2_000_000 * 0.22) = 440_000
    # tax     = round((2_000_000 + 440_000) * 0.08) = 195_200
    # rental  = 500_000 ; floor 2_000_000 (not 1_800_000)
    assert booking["event_charge_cents"] == 3_135_200
    assert PROVISIONAL["FB_SUBTOTAL"] == 2_000_000
    assert PROVISIONAL["SERVICE"] == 440_000
    assert PROVISIONAL["TAX"] == 195_200
    assert PROVISIONAL["RENTAL"] == 500_000


def test_fb_floor_binds_not_per_head_total(api):
    """PRD §3.4: "the food-and-beverage subtotal is the larger of that head count
    multiplied by the package's `per_head_cents` and the package's
    `fb_minimum_cents` (so the minimum floor binds whenever the per-head total
    falls short)."

    Design: Difficulty/combinatorial_formula/fb_floor_max_with_service_then_tax_nesting
    """
    inv, booking = setup_confirmed_booking()
    # If the floor had NOT bound, fb_subtotal would be 1_800_000 and the total
    # would be lower; the asserted 3_135_200 proves the 2_000_000 floor bound.
    assert booking["event_charge_cents"] == 3_135_200


# ───────────── Rule 2 mode (b): milestone waterfall remainder-to-final ─────────────

def test_milestone_split_deposit_interim_final_amounts(api):
    """PRD §3.5: "The deposit milestone (sequence 1, `kind` `DEPOSIT`) takes 25
    percent of the event charge, rounded half up. The interim milestone (sequence 2,
    `kind` `INTERIM`) takes 35 percent, rounded half up. The final milestone
    (sequence 3, `kind` `FINAL`) takes whatever remains — the event charge minus the
    deposit amount minus the interim amount".

    Design: Difficulty/combinatorial_formula/milestone_waterfall_remainder_to_final
    """
    inv, booking = setup_confirmed_booking()
    milestones = get_milestones(inv, booking["id"])
    by_seq = {m["sequence"]: m for m in milestones}
    assert by_seq[1]["kind"] == "DEPOSIT" and by_seq[1]["amount_due_cents"] == 783_800
    assert by_seq[2]["kind"] == "INTERIM" and by_seq[2]["amount_due_cents"] == 1_097_320
    assert by_seq[3]["kind"] == "FINAL" and by_seq[3]["amount_due_cents"] == 1_254_080


def test_milestone_amounts_sum_exactly_to_event_charge(api):
    """PRD §3.5: "so it absorbs every rounding remainder and the three
    `amount_due_cents` values sum exactly to `event_charge_cents`; the final
    milestone is never independently rounded."

    Design: Difficulty/combinatorial_formula/milestone_waterfall_remainder_to_final
    """
    inv, booking = setup_confirmed_booking()
    milestones = get_milestones(inv, booking["id"])
    total = sum(m["amount_due_cents"] for m in milestones)
    assert total == booking["event_charge_cents"] == 3_135_200


# ───────────── Corner: calculations — partial waterfall allocation ─────────────

def test_waterfall_partial_allocation_settles_deposit_partials_interim(api):
    """PRD §3.5: "the sequence-1 milestone is filled to its `amount_due_cents` first,
    any overflow spills to sequence 2, then to sequence 3."
    PRD §3.5: "`SETTLED` when `amount_allocated_cents` equals `amount_due_cents`,
    `PARTIAL` when allocation is positive but short of the amount due, and `OPEN`
    when nothing has been allocated."

    Design: Corner/calculations/waterfall_partial_allocation_settles_deposit_partials_interim
    """
    inv, booking = setup_confirmed_booking()  # deposit 783_800 paid in setup
    # Post a further 216_200 → total paid 1_000_000.
    get_success_data(api.post_payment(
        booking["id"], create_payment_payload("INBOUND", 216_200, "CARD"), FO))
    milestones = get_milestones(inv, booking["id"])
    by_seq = {m["sequence"]: m for m in milestones}
    assert by_seq[1]["milestone_status"] == "SETTLED"
    assert by_seq[1]["amount_allocated_cents"] == 783_800
    assert by_seq[2]["milestone_status"] == "PARTIAL"
    assert by_seq[2]["amount_allocated_cents"] == 216_200
    assert by_seq[3]["milestone_status"] == "OPEN"
    assert by_seq[3]["amount_allocated_cents"] == 0


# ───────────── Corner: cross_cutting — derived balance reconciliation ─────────────

def test_derived_balance_due_reconciles_after_payment(api):
    """PRD §3.5: "The booking's `balance_due_cents` is `event_charge_cents` minus
    `amount_paid_cents`".
    PRD §3.5: "The booking's `amount_paid_cents` is always derived from this stream:
    it is the sum of `amount_cents` over `INBOUND` payments with `status` `POSTED`,
    minus the sum over `OUTBOUND` payments with `status` `POSTED`."

    Design: Corner/cross_cutting_complexity_layers/derived_balance_due_reconciles_after_payment
    """
    inv, booking = setup_confirmed_booking()  # charge 3_135_200, deposit 783_800
    get_success_data(api.post_payment(
        booking["id"], create_payment_payload("INBOUND", 500_000, "CARD"), FO))
    data = get_success_data(api.get_booking(booking["id"], inv["coord_headers"]))
    assert data["amount_paid_cents"] == 1_283_800
    assert data["balance_due_cents"] == 1_851_400
    assert data["balance_due_cents"] == data["event_charge_cents"] - data["amount_paid_cents"]
