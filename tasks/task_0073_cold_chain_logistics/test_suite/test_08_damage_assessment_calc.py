"""Damage assessment tests — dual-variant calculation, evidence rules
(PRD §3.9).

Difficulty-design instances exercised:
- # difficulty: dual_variant_calc/damage_amount_insured_vs_invoice_value
- # difficulty: combinatorial_formula/damage_amount_three_input_nonlinear
- # difficulty: combinatorial_formula/damage_amount_per_unit_then_sum_rounding_order
- # difficulty: boundary_precision_check/damage_assessment_empty_evidence_array
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    COMPLIANCE,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TaskParties,
    advance_clock,
    assert_damage_assessment,
    create_damage_assessment,
    create_damage_assessment_payload,
    get_clock_now,
    ingest_reading,
    open_alert_via_reading,
    parse_iso,
    setup_delivered_with_alert,
    setup_finalized_assessment_pair_for_dual_variant,
    validate_error,
    validate_success,
    walk_alert_to_resolved,
)


# ===========================================================================
# Successful creation — INSURED_VALUE
# ===========================================================================
def test_insured_value_damage_amount(api):
    """PRD §3.9: 'Under variant of INSURED_VALUE, the per-unit value in
    cents is the floor of the task's cargo_value_cents divided by the
    task's cargo_quantity.'

    With cargo_value=1_000_000, qty=100, factor=0.60 (MODERATE),
    salvage=0.10: unit=10_000; per_unit=round_half_up(10_000*0.60*0.90)
    =5_400; raw=5_400*5=27_000. Cap=1_000_000 (large) -> damage_amount
    =27_000."""
    scenario = setup_delivered_with_alert(
        cargo_value_cents=1_000_000, cargo_quantity=100,
        insured_cap_cents=1_000_000,
    )
    assessment = create_damage_assessment(
        scenario=scenario,
        damaged_quantity=5,
        damage_class="MODERATE",
        salvage_pct=0.10,
        variant="INSURED_VALUE",
    )
    assert_damage_assessment(assessment)
    assert assessment["damage_amount_cents"] == 27_000


def test_invoice_value_damage_amount(api):
    """PRD §3.9: 'Under variant of INVOICE_VALUE, the per-unit value is
    invoice_unit_value_cents supplied in the payload, which must be a
    positive integer (greater than zero).'

    With invoice=12_000, factor=0.60, salvage=0.10:
    per_unit=round_half_up(12_000*0.60*0.90)=6_480; raw=6_480*5=32_400.

    # difficulty: dual_variant_calc/damage_amount_insured_vs_invoice_value
    """
    scenario = setup_delivered_with_alert(
        cargo_value_cents=1_000_000, cargo_quantity=100,
        insured_cap_cents=1_000_000,
    )
    assessment = create_damage_assessment(
        scenario=scenario,
        damaged_quantity=5,
        damage_class="MODERATE",
        salvage_pct=0.10,
        variant="INVOICE_VALUE",
        invoice_unit_value_cents=12_000,
    )
    assert assessment["damage_amount_cents"] == 32_400


def test_dual_variant_same_inputs_different_outputs(api):
    """PRD §3.9: 'a deterministic two-variant rule. ... Under variant of
    INSURED_VALUE, the per-unit value in cents is the floor of the
    task's cargo_value_cents divided by the task's cargo_quantity. ...
    Under variant of INVOICE_VALUE, the per-unit value is
    invoice_unit_value_cents supplied in the payload.'

    Identical damaged_quantity / damage_class / salvage_pct, different
    variant -> different damage_amount_cents.

    # difficulty: dual_variant_calc/damage_amount_insured_vs_invoice_value
    """
    scenario_a, scenario_b = (
        setup_finalized_assessment_pair_for_dual_variant(
            insured_cap_cents=500_000,
            cargo_value_cents=1_000_000,
            cargo_quantity=100,
            invoice_unit_value_cents=12_000,
            damaged_quantity=5,
            damage_class="MODERATE",
            salvage_pct=0.10,
        )
    )
    assert scenario_a["assessment"]["damage_amount_cents"] == 27_000
    assert scenario_b["assessment"]["damage_amount_cents"] == 32_400
    assert (
        scenario_a["assessment"]["damage_amount_cents"]
        != scenario_b["assessment"]["damage_amount_cents"]
    ), "PRD §3.9: same inputs, different variant must produce different totals"


# ===========================================================================
# Cap clipping — three-input nonlinear difficulty
# ===========================================================================
def test_damage_amount_capped_by_vehicle_insurance(api):
    """PRD §3.9: 'damage_amount_cents is the smaller of the raw total
    and the task's vehicle insured_cap_cents; ... when the raw total
    exceeds the cap only the capped value is persisted (the unclipped
    raw total is not retained).'

    With insured_cap=20_000 and raw_total=27_000 (per-unit 5_400 x 5):
    damage_amount = min(27_000, 20_000) = 20_000.

    # difficulty: combinatorial_formula/damage_amount_three_input_nonlinear
    """
    scenario = setup_delivered_with_alert(
        cargo_value_cents=1_000_000, cargo_quantity=100,
        insured_cap_cents=20_000,
    )
    assessment = create_damage_assessment(
        scenario=scenario,
        damaged_quantity=5,
        damage_class="MODERATE",
        salvage_pct=0.10,
        variant="INSURED_VALUE",
    )
    assert assessment["damage_amount_cents"] == 20_000


def test_damage_amount_equal_to_cap_not_clipped_as_error(api):
    """PRD §3.9: 'when the raw total equals the cap exactly no
    cap-clipping error is raised, and when the raw total exceeds the
    cap only the capped value is persisted.'

    With insured_cap_cents = raw_total exactly (27_000 here), the
    request succeeds and damage_amount_cents equals the cap value.

    # difficulty: combinatorial_formula/damage_amount_three_input_nonlinear
    """
    scenario = setup_delivered_with_alert(
        cargo_value_cents=1_000_000, cargo_quantity=100,
        insured_cap_cents=27_000,  # exactly equal to raw_total
    )
    assessment = create_damage_assessment(
        scenario=scenario,
        damaged_quantity=5,
        damage_class="MODERATE",
        salvage_pct=0.10,
        variant="INSURED_VALUE",
    )
    # per-unit = 5_400; raw = 27_000; cap = 27_000; min = 27_000.
    assert assessment["damage_amount_cents"] == 27_000


def test_damage_amount_per_unit_then_sum_rounding(api):
    """PRD §3.9: 'The evaluation order is pinned: per-unit first and
    rounded, then multiplied by quantity, then capped.'
    PRD §2.7: 'compute the per-unit damage and round it first, then
    multiply by the damaged-unit count.'

    With cargo_value=1_000_100, qty=100, factor=0.60, salvage=0.00:
    unit_value=floor(1_000_100/100)=10_001; per_unit=
    round_half_up(10_001*0.60*1.00)=round_half_up(6_000.6)=6_001;
    raw_total=6_001*3=18_003. The alternate ordering (round once at
    the end) yields 18_002 — the assertion pins 18_003.

    # difficulty: combinatorial_formula/damage_amount_per_unit_then_sum_rounding_order
    """
    scenario = setup_delivered_with_alert(
        cargo_value_cents=1_000_100, cargo_quantity=100,
        insured_cap_cents=10_000_000,
    )
    assessment = create_damage_assessment(
        scenario=scenario,
        damaged_quantity=3,
        damage_class="MODERATE",
        salvage_pct=0.00,
        variant="INSURED_VALUE",
    )
    assert assessment["damage_amount_cents"] == 18_003, (
        "PRD §3.9 pins per-unit rounding first: expected 6_001 * 3 = 18_003, "
        "not 18_002 (sum-then-round-once alternative)."
    )


def test_damage_amount_per_unit_rounding_does_not_grow_by_quantity(api):
    """PRD §3.9: 'The evaluation order is pinned: per-unit first and
    rounded, then multiplied by quantity, then capped.'
    PRD §2.7: 'compute the per-unit damage and round it first, then
    multiply by the damaged-unit count.'

    With unit_value=10_001, factor=0.60 (MODERATE), salvage=0.00,
    damaged_quantity=10: per_unit=round_half_up(6_000.6)=6_001;
    raw_total=6_001*10=60_010. The alternative ordering (multiply then
    round) would yield round_half_up(10_001*0.60*10)=60_006. The PRD
    pins 60_010.

    # difficulty: combinatorial_formula/damage_amount_per_unit_then_sum_rounding_order
    """
    scenario = setup_delivered_with_alert(
        cargo_value_cents=1_000_100, cargo_quantity=100,
        insured_cap_cents=10_000_000,
    )
    assessment = create_damage_assessment(
        scenario=scenario,
        damaged_quantity=10,
        damage_class="MODERATE",
        salvage_pct=0.00,
        variant="INSURED_VALUE",
    )
    assert assessment["damage_amount_cents"] == 60_010, (
        "PRD §3.9 pinned rounding order: per_unit (6_001) * 10 = 60_010, "
        "not the 60_006 you'd get from sum-then-round-once."
    )


# ===========================================================================
# Damage class factor lookup
# ===========================================================================
@pytest.mark.parametrize(
    "damage_class,expected_factor",
    [
        ("MINOR", 0.30),
        ("MODERATE", 0.60),
        ("TOTAL_LOSS", 1.00),
    ],
)
def test_damage_class_factor(api, damage_class, expected_factor):
    """PRD §3.9: 'the damage factor lookup table assigns 0.30 to MINOR,
    0.60 to MODERATE, and 1.00 to TOTAL_LOSS.'"""
    scenario = setup_delivered_with_alert(
        cargo_value_cents=1_000_000, cargo_quantity=100,
        insured_cap_cents=10_000_000,
    )
    # damaged_quantity=1, salvage=0.00: per_unit = floor(value/qty)*factor
    assessment = create_damage_assessment(
        scenario=scenario,
        damaged_quantity=1,
        damage_class=damage_class,
        salvage_pct=0.00,
        variant="INSURED_VALUE",
    )
    expected = round(10_000 * expected_factor)
    assert assessment["damage_amount_cents"] == expected, (
        f"PRD §3.9: damage_class={damage_class}, factor={expected_factor}: "
        f"expected {expected}, got {assessment['damage_amount_cents']}"
    )


# ===========================================================================
# Evidence and quantity rules
# ===========================================================================
def test_empty_evidence_array_rejected(api):
    """PRD §3.9: 'evidence_alert_ids (the list of supporting Alert ids
    — non-empty, with every referenced alert sharing the same task_id
    and being in either RESOLVED or CLOSED; violations are reported as
    ERR_EVIDENCE_REQUIRED).'

    # difficulty: boundary_precision_check/damage_assessment_empty_evidence_array
    """
    scenario = setup_delivered_with_alert()
    payload = create_damage_assessment_payload(
        task_id=scenario["task"]["id"],
        evidence_alert_ids=[],
        damaged_quantity=1,
        damage_class="MINOR",
        salvage_pct=0.00,
        variant="INSURED_VALUE",
    )
    resp = api.create_damage_assessment(payload, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_EVIDENCE_REQUIRED.value)


def test_non_empty_evidence_array_accepted(api):
    """PRD §3.9: opposite of empty-evidence-array — size 1 must succeed.

    # difficulty: boundary_precision_check/damage_assessment_empty_evidence_array
    """
    scenario = setup_delivered_with_alert()
    assessment = create_damage_assessment(
        scenario=scenario,
        damaged_quantity=1,
        damage_class="MINOR",
        salvage_pct=0.00,
        variant="INSURED_VALUE",
    )
    assert_damage_assessment(assessment)


def test_invoice_value_variant_missing_invoice_field_rejected(api):
    """PRD §3.9: 'a missing or non-positive invoice_unit_value_cents
    under this variant is rejected with ERR_INVOICE_VALUE_REQUIRED.'"""
    scenario = setup_delivered_with_alert()
    payload = create_damage_assessment_payload(
        task_id=scenario["task"]["id"],
        evidence_alert_ids=[scenario["alert"]["id"]],
        damaged_quantity=1,
        damage_class="MINOR",
        salvage_pct=0.00,
        variant="INVOICE_VALUE",
        # invoice_unit_value_cents omitted
    )
    resp = api.create_damage_assessment(payload, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_INVOICE_VALUE_REQUIRED.value)


def test_invoice_value_variant_zero_invoice_field_rejected(api):
    """PRD §3.9: 'invoice_unit_value_cents supplied in the payload,
    which must be a positive integer (greater than zero); a missing or
    non-positive invoice_unit_value_cents under this variant is
    rejected with ERR_INVOICE_VALUE_REQUIRED.'"""
    scenario = setup_delivered_with_alert()
    payload = create_damage_assessment_payload(
        task_id=scenario["task"]["id"],
        evidence_alert_ids=[scenario["alert"]["id"]],
        damaged_quantity=1,
        damage_class="MINOR",
        salvage_pct=0.00,
        variant="INVOICE_VALUE",
        invoice_unit_value_cents=0,
    )
    resp = api.create_damage_assessment(payload, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_INVOICE_VALUE_REQUIRED.value)


def test_damaged_quantity_zero_rejected(api):
    """PRD §3.9: 'damaged_quantity (an integer that must satisfy at
    least one and at most the task's cargo_quantity, with violations
    reported as ERR_QUANTITY_INVALID).'"""
    scenario = setup_delivered_with_alert(cargo_quantity=100)
    payload = create_damage_assessment_payload(
        task_id=scenario["task"]["id"],
        evidence_alert_ids=[scenario["alert"]["id"]],
        damaged_quantity=0,
        damage_class="MINOR",
        salvage_pct=0.00,
        variant="INSURED_VALUE",
    )
    resp = api.create_damage_assessment(payload, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_QUANTITY_INVALID.value)


def test_damaged_quantity_above_cargo_rejected(api):
    """PRD §3.9: 'at most the task's cargo_quantity.'"""
    scenario = setup_delivered_with_alert(cargo_quantity=10)
    payload = create_damage_assessment_payload(
        task_id=scenario["task"]["id"],
        evidence_alert_ids=[scenario["alert"]["id"]],
        damaged_quantity=11,
        damage_class="MINOR",
        salvage_pct=0.00,
        variant="INSURED_VALUE",
    )
    resp = api.create_damage_assessment(payload, COMPLIANCE)
    validate_error(resp, ApiErrorId.ERR_QUANTITY_INVALID.value)


# ===========================================================================
# Finalization lock
# ===========================================================================
def test_finalize_locks_subsequent_patch(api):
    """PRD §3.9: 'Finalising advances the assessment from DRAFT to
    FINALIZED; subsequent PATCH attempts to mutable fields are rejected
    with ERR_INVALID_STATE.'"""
    scenario = setup_delivered_with_alert()
    assessment = create_damage_assessment(
        scenario=scenario, damaged_quantity=1, damage_class="MINOR",
        salvage_pct=0.00, variant="INSURED_VALUE",
    )
    finalized = validate_success(
        api.finalize_damage_assessment(assessment["id"], COMPLIANCE)
    )
    assert finalized["status"] == "FINALIZED"
    # Try to PATCH after finalize.
    resp = api.patch_damage_assessment(
        assessment["id"],
        {"version": finalized["version"], "damaged_quantity": 2},
        COMPLIANCE,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
