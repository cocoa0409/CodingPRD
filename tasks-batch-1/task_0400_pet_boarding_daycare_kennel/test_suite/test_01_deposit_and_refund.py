"""Deposit estimation/latching and cancellation-refund calculations.

Translates difficulty queue (A) instances under rules dual_variant_calc,
combinatorial_formula (deposit), and boundary_precision_check (refund).
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success,
    create_reservation_payload, pay_deposit_payload,
    setup_facility_owner_pet, setup_held_reservation, setup_confirmed_reservation,
    TEST_USERS,
)

MGR = TEST_USERS["manager_headers"]


def test_deposit_estimate_latched_at_creation_under_standard(api):
    """PRD §3.5: "A base figure is chosen by service type: 1500 cents for `DAYCARE`,
    4000 cents for `OVERNIGHT`. That base is multiplied by a size multiplier keyed on
    the pet's `size_class` — 0.8 for `TOY`, 1.0 for `SMALL`, 1.2 for `MEDIUM`, and 1.5
    for `LARGE` — and by a unit count, where the unit count is the greater of `nights`
    and 1 for an overnight stay and exactly 1 for daycare."
    PRD §3.5: "That raw product is then multiplied by the policy factor selected by the
    facility's `deposit_policy`: 0.30 for `STANDARD`, 0.50 for `STRICT`, and 0 for `NONE`."

    OVERNIGHT/MEDIUM/3n/STANDARD = 4000 * 1.2 * 3 * 0.30 = 4320.

    Design: Difficulty/dual_variant_calc/deposit_estimate_vs_final_after_policy_change
    """
    facility, owner, pet = setup_facility_owner_pet(
        deposit_policy="STANDARD", weight_kg=18, review="CLEAR")
    assert pet["size_class"] == "MEDIUM"
    res = get_success_data(api_client.create_reservation(
        facility["id"],
        create_reservation_payload(pet["id"], "OVERNIGHT", "2026-02-01", "2026-02-04"),
        MGR,
    ))
    assert res["deposit_cents"] == 4320, f"estimate under STANDARD should be 4320, got {res['deposit_cents']}"
    # The estimate is stable on a subsequent read (advisory, not yet latched-final).
    res_now = validate_success(api.get_reservation(res["id"], MGR), 200)
    assert res_now["deposit_cents"] == 4320


def test_deposit_latched_to_final_variant_at_confirm(api):
    """PRD §3.6: "The deposit is re-evaluated and `deposit_cents` is latched to the final
    variant: the same deposit formula is recomputed against the facility's current
    `deposit_policy` and the current `nights` and `size_class`, and this latched value —
    not the earlier estimate — is the figure `deposit_paid_cents` was checked against for
    `ERR_DEPOSIT_UNPAID`."

    OVERNIGHT/MEDIUM/3n/STANDARD latches deposit_cents 4320 at confirm; paying 4320 then
    confirming leaves the latched final deposit at 4320.

    Design: Difficulty/dual_variant_calc/deposit_estimate_vs_final_after_policy_change
    """
    ctx = setup_confirmed_reservation(
        service_type="OVERNIGHT", start_date="2026-02-01", end_date="2026-02-04",
        deposit_policy="STANDARD", weight_kg=18, pay_cash=4320)
    res = ctx["reservation"]
    assert res["status"] == "CONFIRMED"
    assert res["deposit_cents"] == 4320, "final latched deposit recomputed under STANDARD is 4320"


def test_deposit_three_input_nonlinear_combination(api):
    """PRD §3.5: "That base is multiplied by a size multiplier keyed on the pet's
    `size_class` — 0.8 for `TOY`, 1.0 for `SMALL`, 1.2 for `MEDIUM`, and 1.5 for
    `LARGE` — and by a unit count, where the unit count is the greater of `nights`
    and 1 for an overnight stay and exactly 1 for daycare."
    PRD §3.5: "That raw product is then multiplied by the policy factor selected by the
    facility's `deposit_policy`: 0.30 for `STANDARD`, 0.50 for `STRICT`, and 0 for `NONE`."

    OVERNIGHT/LARGE/2n/STANDARD = 4000 * 1.5 * 2 * 0.30 = 3600.

    Design: Difficulty/combinatorial_formula/deposit_three_input_nonlinear_mode_a
    """
    facility, owner, pet = setup_facility_owner_pet(
        deposit_policy="STANDARD", weight_kg=35, vaccinate=False, review=None)
    assert pet["size_class"] == "LARGE"
    res = get_success_data(api_client.create_reservation(
        facility["id"],
        create_reservation_payload(pet["id"], "OVERNIGHT", "2026-03-01", "2026-03-03"),
        MGR,
    ))
    assert res["deposit_cents"] == 3600, f"4000*1.5*2*0.30 == 3600, got {res['deposit_cents']}"


def test_deposit_daycare_toy_strict_combination(api):
    """PRD §3.5: "A base figure is chosen by service type: 1500 cents for `DAYCARE`, 4000
    cents for `OVERNIGHT`. That base is multiplied by a size multiplier keyed on the pet's
    `size_class` — 0.8 for `TOY`, 1.0 for `SMALL`, 1.2 for `MEDIUM`, and 1.5 for `LARGE`
    — and by a unit count, where the unit count is the greater of `nights` and 1 for an
    overnight stay and exactly 1 for daycare."
    PRD §3.5: "That raw product is then multiplied by the policy factor selected by the
    facility's `deposit_policy`: 0.30 for `STANDARD`, 0.50 for `STRICT`, and 0 for `NONE`."

    DAYCARE/TOY/1unit/STRICT = 1500 * 0.8 * 1 * 0.50 = 600, a four-input combination no
    single-factor lookup produces.

    Design: Difficulty/combinatorial_formula/deposit_three_input_nonlinear_mode_a
    """
    facility, owner, pet = setup_facility_owner_pet(
        deposit_policy="STRICT", weight_kg=3, vaccinate=False, review=None)
    assert pet["size_class"] == "TOY"
    res = get_success_data(api_client.create_reservation(
        facility["id"],
        create_reservation_payload(pet["id"], "DAYCARE", "2026-03-01", "2026-03-01"),
        MGR,
    ))
    assert res["deposit_cents"] == 600, f"1500*0.8*1*0.50 == 600, got {res['deposit_cents']}"


def test_refund_provisional_zero_when_deposit_unpaid(api):
    """PRD §3.8: "when the lead is at least 7 days the refund is the full
    `deposit_paid_cents`".
    PRD §3.8: "Cancelling from `REQUESTED` is the provisional variant:
    `deposit_paid_cents` may still be 0 because the deposit was never collected, so even
    a generous lead-time tier yields a refund of 0."

    Cancel from REQUESTED at lead 31 days with deposit unpaid -> refund 0.

    Design: Difficulty/dual_variant_calc/refund_provisional_vs_final_same_lead_tier
    """
    ctx = setup_held_reservation(
        service_type="OVERNIGHT", start_date="2026-02-01", end_date="2026-02-04",
        deposit_policy="STANDARD", weight_kg=18)
    res = ctx["reservation"]
    assert res["status"] == "REQUESTED"
    assert res["deposit_paid_cents"] == 0
    cancelled = validate_success(api.cancel_reservation(res["id"], MGR), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["refund_cents"] == 0, "provisional refund with deposit_paid_cents 0 is 0"


def test_refund_final_full_when_deposit_paid_high_lead(api):
    """PRD §3.8: "when the lead is at least 7 days the refund is the full
    `deposit_paid_cents`".
    PRD §3.8: "Cancelling from `CONFIRMED` is the final variant: the deposit has been
    fully collected, so the same lead-time tier yields a non-zero refund the provisional
    path could not."

    Cancel from CONFIRMED at lead 31 days with deposit 4320 paid -> refund 4320.

    Design: Difficulty/dual_variant_calc/refund_provisional_vs_final_same_lead_tier
    """
    ctx = setup_confirmed_reservation(
        service_type="OVERNIGHT", start_date="2026-02-01", end_date="2026-02-04",
        deposit_policy="STANDARD", weight_kg=18, pay_cash=4320)
    res = ctx["reservation"]
    assert res["status"] == "CONFIRMED"
    assert res["deposit_paid_cents"] == 4320
    cancelled = validate_success(api.cancel_reservation(res["id"], MGR), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["refund_cents"] == 4320, "final refund at >=7 lead is full deposit_paid_cents"


def test_refund_full_at_lead_exactly_7(api):
    """PRD §3.8: "The refund is keyed on lead time, defined as the number of days from
    the facility's `current_date` to the reservation's `start_date`: when the lead is at
    least 7 days the refund is the full `deposit_paid_cents`".

    DAYCARE/SMALL/STANDARD deposit = 1500*1.0*1*0.30 = 450; lead exactly 7 -> refund 450.

    Design: Difficulty/boundary_precision_check/refund_lead_day_boundary_7_vs_6
    """
    # current_date 2026-01-01, start 2026-01-08 => lead exactly 7.
    ctx = setup_confirmed_reservation(
        service_type="DAYCARE", start_date="2026-01-08", end_date="2026-01-08",
        deposit_policy="STANDARD", weight_kg=6, pay_cash=450, daycare_capacity=5)
    res = ctx["reservation"]
    assert res["deposit_paid_cents"] == 450
    cancelled = validate_success(api.cancel_reservation(res["id"], MGR), 200)
    assert cancelled["refund_cents"] == 450, "lead == 7 hits the >=7 full-refund tier"


def test_refund_partial_at_lead_6(api):
    """PRD §3.8: "when the lead is at least 2 days but fewer than 7 the refund is
    `deposit_paid_cents` multiplied by 0.50 and rounded half up to whole cents".

    Boundary companion: deposit 450 paid, lead exactly 6 -> 450 * 0.50 = 225.

    Design: Difficulty/boundary_precision_check/refund_lead_day_boundary_7_vs_6
    """
    # current_date 2026-01-01, start 2026-01-07 => lead 6.
    ctx = setup_confirmed_reservation(
        service_type="DAYCARE", start_date="2026-01-07", end_date="2026-01-07",
        deposit_policy="STANDARD", weight_kg=6, pay_cash=450, daycare_capacity=5)
    res = ctx["reservation"]
    assert res["deposit_paid_cents"] == 450
    cancelled = validate_success(api.cancel_reservation(res["id"], MGR), 200)
    assert cancelled["refund_cents"] == 225, "lead 6 (2..6 tier) -> 50% of 450 == 225"
