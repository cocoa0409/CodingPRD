"""Settlement-charge calculation tests (fees computed at return).

PRD §3.7 pins the damage fee by disposition, the waiver credit cap, the deposit
waterfall, and the net/refund split.
"""
from test_helpers import (
    validate_success,
    create_picked_up_reservation, return_reservation,
)

# Catalog used across these tests: daily 5000, deposit 20000, replacement 80000,
# waiver 1200/day, buffer 2, late fee 2000/day.
CAT = {
    "daily_rate_cents": 5000, "deposit_cents": 20000, "replacement_value_cents": 80000,
    "waiver_daily_rate_cents": 1200, "cleaning_buffer_days": 2, "late_fee_daily_rate_cents": 2000,
}

# A 3-day on-time reservation: pickup 09-01, return window end 09-03T17:00.
RESV = {
    "event_date_iso": "2026-09-04T00:00:00Z",
    "pickup_window_start_iso": "2026-09-01T09:00:00Z",
    "return_window_end_iso": "2026-09-03T17:00:00Z",
}


def test_damaged_return_net_charge_after_deposit(api):
    """PRD §3.7: "a `DAMAGED` return carries a damage fee equal to the smaller of the catalog's `replacement_value_cents` and 60 percent of that replacement value rounded half-up to whole cents, with the minimum applied after the percentage is rounded".
    PRD §3.7: "The `net_charge_cents` — what the customer still owes beyond the deposit — is the gross fees minus the deposit, floored at 0 so it is never negative."
    PRD §3.7: "The `deposit_refund_cents` — what is returned to the customer — is the deposit minus the amount drawn from it."

    Design: Difficulty/dual_variant_calc/settlement_charges_clean_vs_damaged_on_settlement
    """
    _, _, _, resv = create_picked_up_reservation(
        catalog_overrides={**CAT, "style_name": "Tux B"}, reservation_overrides=RESV)
    settlement = return_reservation(resv["id"], "2026-09-03T12:00:00Z", "DAMAGED")

    # damage = min(80000, round(80000*0.60)=48000) = 48000; no waiver.
    assert settlement["damage_fee_cents"] == 48000
    # gross 48000 - deposit 20000 = 28000 net; deposit fully drawn so refund 0.
    assert settlement["net_charge_cents"] == 28000
    assert settlement["deposit_refund_cents"] == 0


def test_clean_return_net_zero_full_refund(api):
    """PRD §3.7: "a `CLEAN` return carries a damage fee of 0".
    PRD §3.7: "The `deposit_refund_cents` — what is returned to the customer — is the deposit minus the amount drawn from it."

    Design: Difficulty/dual_variant_calc/settlement_charges_clean_vs_damaged_on_settlement
    """
    _, _, _, resv = create_picked_up_reservation(
        catalog_overrides={**CAT, "style_name": "Tux B2"}, reservation_overrides=RESV)
    settlement = return_reservation(resv["id"], "2026-09-03T12:00:00Z", "CLEAN")

    # CLEAN on-time: damage 0, late 0, gross 0; deposit (20000) fully refunded.
    assert settlement["damage_fee_cents"] == 0
    assert settlement["net_charge_cents"] == 0
    assert settlement["deposit_refund_cents"] == 20000


def test_damaged_with_waiver_nested_min_max(api):
    """PRD §3.7: "The `waiver_credit_cents` absorbs damage only, never late fees: when `damage_waiver_opted` is true it equals the smaller of `damage_fee_cents` and the waiver cap of 30000 cents, and when the waiver was not purchased it is 0."
    PRD §3.7: "The gross fees are then `late_fee_cents` plus `damage_fee_cents` minus `waiver_credit_cents`."
    PRD §3.7: "The amount drawn from the deposit is the smaller of the deposit and the gross fees."

    Design: Difficulty/combinatorial_formula/settlement_charges_nested_min_max_branches
    """
    _, _, _, resv = create_picked_up_reservation(
        catalog_overrides={**CAT, "style_name": "Gown C"},
        reservation_overrides={**RESV, "damage_waiver_opted": True})
    settlement = return_reservation(resv["id"], "2026-09-03T12:00:00Z", "DAMAGED")

    assert settlement["damage_fee_cents"] == 48000
    # waiver = min(48000, 30000) = 30000
    assert settlement["waiver_credit_cents"] == 30000
    # gross 48000 - 30000 = 18000; deposit 20000 absorbs all -> net 0
    assert settlement["net_charge_cents"] == 0
    # refund = 20000 - applied 18000 = 2000
    assert settlement["deposit_refund_cents"] == 2000


def test_lost_return_damage_fee_is_full_replacement(api):
    """PRD §3.7: "a `LOST` return carries a damage fee equal to the full `replacement_value_cents`."
    PRD §3.7: "The `net_charge_cents` — what the customer still owes beyond the deposit — is the gross fees minus the deposit, floored at 0 so it is never negative."

    Design: Corner/calculations/lost_return_damage_fee_is_full_replacement
    """
    _, _, _, resv = create_picked_up_reservation(
        catalog_overrides={**CAT, "style_name": "Tux G2"}, reservation_overrides=RESV)
    settlement = return_reservation(resv["id"], "2026-09-03T12:00:00Z", "LOST")

    assert settlement["damage_fee_cents"] == 80000, "LOST -> full replacement value"
    assert settlement["net_charge_cents"] == 60000, "80000 - deposit 20000"
    assert settlement["deposit_refund_cents"] == 0
