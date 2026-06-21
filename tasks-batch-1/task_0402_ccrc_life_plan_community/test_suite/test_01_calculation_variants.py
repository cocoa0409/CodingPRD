"""Dual-variant and combinatorial-formula calculation tests (PRD §3.6, §3.7).

Queue (A) difficulty instances for the entrance-fee refund and monthly-invoice
calculations: same formula, divergent variants; and multi-input non-linear
folds with a pinned rounding order.
"""
from test_helpers import (
    advance_clock,
    get_residency,
    list_refund_disbursements,
    setup_active_residency,
    setup_community_and_plan,
    setup_residency_in_skilled_with_occupied_bed,
    terminate_residency,
    FO,
)
from test_helpers.api_client import api_client
from test_helpers import validate_success


# ─────────────────────────────────────────────────────────────────────────────
# dual_variant_calc / refund_voluntary_vs_death_diverge_on_fifty_plan
# ─────────────────────────────────────────────────────────────────────────────

def test_fifty_refundable_voluntary_amortizes_above_floor(api):
    """PRD §3.7: "Under `FIFTY_REFUNDABLE`, the floor is half the gross fee — the
    floor of the gross fee multiplied by 5000 divided by 10000 — and the refundable
    amount is the larger of that floor and the gross fee minus the per-month amount
    times the occupied months."

    G=10_000_000, declining_monthly_bps=200, m=5: per_month=floor(10_000_000*200/10000)
    =200_000, *5=1_000_000; refundable=max(5_000_000, 10_000_000-1_000_000)=9_000_000.

    Design: Difficulty/dual_variant_calc/refund_voluntary_vs_death_diverge_on_fifty_plan
    """
    community, _plan, residency, refund = _terminate_fifty(reason="VOLUNTARY")
    assert refund["refundable_cents"] == 9_000_000, (
        f"VOLUNTARY FIFTY refund must be 9_000_000, got {refund['refundable_cents']}"
    )
    assert refund["termination_reason"] == "VOLUNTARY"


def test_fifty_refundable_death_pays_full_floor_dropping_amortization(api):
    """PRD §3.7: "Under the `DEATH` variant, the `FIFTY_REFUNDABLE` and
    `NINETY_REFUNDABLE` plans pay the full floor regardless of how many months
    were occupied — that is, the refundable amount equals the floor amount and the
    amortization subtraction is dropped entirely."

    Same residency (G=10_000_000, m=5): the DEATH FIFTY floor is
    floor(10_000_000*5000/10000)=5_000_000, distinct from the VOLUNTARY 9_000_000.

    Design: Difficulty/dual_variant_calc/refund_voluntary_vs_death_diverge_on_fifty_plan
    """
    community, _plan, residency, refund = _terminate_fifty(reason="DEATH")
    assert refund["refundable_cents"] == 5_000_000, (
        f"DEATH FIFTY refund must be 5_000_000 (full floor), got {refund['refundable_cents']}"
    )
    assert refund["termination_reason"] == "DEATH"
    assert 9_000_000 != 5_000_000  # the two variants diverge on the same plan


def _terminate_fifty(reason: str):
    """FIFTY_REFUNDABLE plan, G=10_000_000, residency ACTIVE with occupied_months=5,
    then terminated with the given reason."""
    community, plan, _unit, active = setup_active_residency(
        community_name="Maplewood",
        actuarial_discount_rate_bps=600,
        reserve_assets_cents=0,
        plan_overrides={
            "name": "Fifty Plan",
            "contract_type": "TYPE_C",
            "entrance_fee_cents": 10_000_000,
            "refund_plan": "FIFTY_REFUNDABLE",
            "monthly_service_fee_cents": 300_000,
            "second_person_fee_cents": 150_000,
            "declining_monthly_bps": 200,
        },
    )
    advance_clock(community["id"], 5)
    fresh = get_residency(active["id"])
    terminate_residency(fresh["id"], reason, fresh["version"])
    refund = list_refund_disbursements(fresh["id"])[0]
    return community, plan, fresh, refund


# ─────────────────────────────────────────────────────────────────────────────
# dual_variant_calc / invoice_type_a_vs_type_c_diverge_on_skilled_per_diem
# ─────────────────────────────────────────────────────────────────────────────

def test_invoice_type_a_skilled_days_add_zero_per_diem(api):
    """PRD §3.6: "under `TYPE_A`, the life-care contract, the surcharge is 0 because
    nursing carries no marginal monthly cost".

    TYPE_A plan, SKILLED residency, 15 skilled days, per_diem 40_000:
    care_surcharge_cents == 0, total_cents == base 300_000.

    Design: Difficulty/dual_variant_calc/invoice_type_a_vs_type_c_diverge_on_skilled_per_diem
    """
    invoice = _skilled_invoice("TYPE_A", "Cedar A", skilled_days=15)
    assert invoice["care_surcharge_cents"] == 0, (
        f"TYPE_A skilled care_surcharge must be 0, got {invoice['care_surcharge_cents']}"
    )
    assert invoice["total_cents"] == 300_000, (
        f"TYPE_A skilled total must be 300_000, got {invoice['total_cents']}"
    )


def test_invoice_type_c_bills_every_skilled_day(api):
    """PRD §3.6: "under `TYPE_C`, fee-for-service, every skilled day of the period is
    billed, so the surcharge is this period's skilled days multiplied by
    `skilled_per_diem_cents`".

    TYPE_C plan, SKILLED residency, 15 skilled days, per_diem 40_000:
    care_surcharge_cents == 15*40_000 == 600_000, total == 300_000+600_000 == 900_000.

    Design: Difficulty/dual_variant_calc/invoice_type_a_vs_type_c_diverge_on_skilled_per_diem
    """
    invoice = _skilled_invoice("TYPE_C", "Cedar C", skilled_days=15)
    assert invoice["care_surcharge_cents"] == 600_000, (
        f"TYPE_C skilled care_surcharge must be 600_000, got {invoice['care_surcharge_cents']}"
    )
    assert invoice["total_cents"] == 900_000, (
        f"TYPE_C skilled total must be 900_000, got {invoice['total_cents']}"
    )


def _skilled_invoice(contract_type: str, community_name: str, skilled_days: int):
    """ACTIVE residency stepped to SKILLED with an occupied bed, then invoiced."""
    _community, _plan, _ind, _sk, residency = (
        setup_residency_in_skilled_with_occupied_bed(
            community_name=community_name,
            plan_overrides={
                "name": f"{contract_type} Plan",
                "contract_type": contract_type,
                "entrance_fee_cents": 5_000_000,
                "refund_plan": "DECLINING",
                "monthly_service_fee_cents": 300_000,
                "second_person_fee_cents": 150_000,
                "skilled_per_diem_cents": 40_000,
            },
        )
    )
    return validate_success(api_client.issue_invoice(
        residency["id"], {"skilled_days_in_period": skilled_days}, FO,
    ), expected_status=201)


# ─────────────────────────────────────────────────────────────────────────────
# combinatorial_formula / refund_rounding_order_pinned_per_month_then_multiply
# ─────────────────────────────────────────────────────────────────────────────

def test_declining_refund_pins_per_month_floor_then_multiply(api):
    """PRD §3.7: "First compute a per-month amortization amount as the floor of the
    gross fee multiplied by the plan's `declining_monthly_bps` and divided by 10000
    — this per-month figure is computed once and then multiplied by the occupied
    months, and this ordering is mandatory because computing the per-month amount
    first and then multiplying differs in cents from multiplying the gross fee by the
    rate and the months together before flooring."

    G=999_999, declining_monthly_bps=200, m=5, nonref_bps=0:
    per_month=floor(999_999*200/10000)=19_999, *5=99_995;
    refundable=max(0, 999_999-0-99_995)=900_004, NOT 999_999-99_999=900_000.

    Design: Difficulty/combinatorial_formula/refund_rounding_order_pinned_per_month_then_multiply
    """
    community, plan, _unit, active = setup_active_residency(
        community_name="Birch",
        plan_overrides={
            "name": "Round Plan",
            "contract_type": "TYPE_C",
            "entrance_fee_cents": 999_999,
            "refund_plan": "DECLINING",
            "monthly_service_fee_cents": 300_000,
            "second_person_fee_cents": 0,
            "declining_monthly_bps": 200,
            "declining_nonrefundable_bps": 0,
        },
    )
    advance_clock(community["id"], 5)
    fresh = get_residency(active["id"])
    terminate_residency(fresh["id"], "VOLUNTARY", fresh["version"])
    refund = list_refund_disbursements(fresh["id"])[0]
    assert refund["refundable_cents"] == 900_004, (
        f"pinned per-month-then-multiply refund must be 900_004 "
        f"(not 900_000), got {refund['refundable_cents']}"
    )


def test_declining_refund_rounding_order_not_collapsed(api):
    """PRD §3.7: "computing the per-month amount first and then multiplying differs
    in cents from multiplying the gross fee by the rate and the months together
    before flooring."

    Asserts the result is strictly the pinned-order value 900_004, never the
    collapsed-order value 900_000 — confirming the floor is applied per-month.

    Design: Difficulty/combinatorial_formula/refund_rounding_order_pinned_per_month_then_multiply
    """
    community, plan, _unit, active = setup_active_residency(
        community_name="Birch2",
        plan_overrides={
            "name": "Round Plan",
            "contract_type": "TYPE_C",
            "entrance_fee_cents": 999_999,
            "refund_plan": "DECLINING",
            "monthly_service_fee_cents": 300_000,
            "second_person_fee_cents": 0,
            "declining_monthly_bps": 200,
            "declining_nonrefundable_bps": 0,
        },
    )
    advance_clock(community["id"], 5)
    fresh = get_residency(active["id"])
    terminate_residency(fresh["id"], "VOLUNTARY", fresh["version"])
    refund = list_refund_disbursements(fresh["id"])[0]
    assert refund["refundable_cents"] == 900_004
    assert refund["refundable_cents"] != 900_000, (
        "collapsed-order 900_000 would mean the floor was applied to G*bps*m, "
        "violating the pinned per-month-then-multiply order"
    )


# ─────────────────────────────────────────────────────────────────────────────
# combinatorial_formula / invoice_three_input_nonlinear_assisted_second_skilled
# ─────────────────────────────────────────────────────────────────────────────

def test_invoice_folds_assisted_base_second_person_and_care(api):
    """PRD §3.6: "The base line begins as the plan's `monthly_service_fee_cents`; if
    the residency's `care_level` is `ASSISTED`, the plan's
    `assisted_monthly_surcharge_cents` is added into that base."
    PRD §3.6: "The second-person line is the plan's flat `second_person_fee_cents`
    when the residency's `has_second_person` is true, and 0 otherwise — it is never
    scaled by care level."
    PRD §3.6: "If the residency's `care_level` is not `SKILLED`, the care surcharge
    is 0."

    ASSISTED residency, second person, TYPE_C, 0 skilled days:
    base=300_000+120_000=420_000, second=150_000, care=0, total=570_000.

    Design: Difficulty/combinatorial_formula/invoice_three_input_nonlinear_assisted_second_skilled
    """
    invoice = _assisted_second_person_invoice("Aspen")
    assert invoice["base_service_fee_cents"] == 420_000, (
        f"base must be 420_000 (300_000 + 120_000 ASSISTED surcharge), "
        f"got {invoice['base_service_fee_cents']}"
    )
    assert invoice["second_person_fee_cents"] == 150_000, (
        f"second-person line must be 150_000, got {invoice['second_person_fee_cents']}"
    )
    assert invoice["care_surcharge_cents"] == 0, (
        f"non-SKILLED care surcharge must be 0, got {invoice['care_surcharge_cents']}"
    )
    assert invoice["total_cents"] == 570_000, (
        f"total must be 570_000, got {invoice['total_cents']}"
    )


def test_invoice_total_equals_sum_of_three_lines(api):
    """PRD §3.6: "The invoice `total_cents` is the sum of the base line, the
    second-person line, and the care surcharge."

    Confirms total_cents == base + second + care == 420_000 + 150_000 + 0 == 570_000
    for the ASSISTED+second-person TYPE_C residency.

    Design: Difficulty/combinatorial_formula/invoice_three_input_nonlinear_assisted_second_skilled
    """
    invoice = _assisted_second_person_invoice("Aspen2")
    assert invoice["total_cents"] == (
        invoice["base_service_fee_cents"]
        + invoice["second_person_fee_cents"]
        + invoice["care_surcharge_cents"]
    )
    assert invoice["total_cents"] == 570_000


def _assisted_second_person_invoice(community_name: str):
    """ACTIVE residency, second person added, stepped to ASSISTED, then invoiced
    with 0 skilled days on a TYPE_C plan."""
    community, plan, _unit, active = setup_active_residency(
        community_name=community_name,
        plan_overrides={
            "name": "Combo Plan",
            "contract_type": "TYPE_C",
            "entrance_fee_cents": 5_000_000,
            "refund_plan": "DECLINING",
            "monthly_service_fee_cents": 300_000,
            "second_person_fee_cents": 150_000,
            "assisted_monthly_surcharge_cents": 120_000,
            "skilled_per_diem_cents": 40_000,
        },
    )
    from test_helpers import AD, propose_and_apply_transition
    from test_helpers.factories import create_second_person_payload
    validate_success(api_client.add_second_person(
        active["id"],
        create_second_person_payload(full_name="Spouse", date_of_birth="1938-07-07"),
        AD,
    ), expected_status=201)
    propose_and_apply_transition(active["id"], "ASSISTED")
    return validate_success(api_client.issue_invoice(
        active["id"], {"skilled_days_in_period": 0}, FO,
    ), expected_status=201)
