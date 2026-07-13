"""FEMA-PA cost recovery: the estimated-vs-actual federal-share dual variant,
the enhanced-tier percentage selection, per-record rounding order, the cost
ceiling, and ledger conservation on void.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    create_activated_incident,
    setup_eligible_incident,
    create_cost_record,
    finalize_cost_record,
    void_cost_record,
    incident_version,
    create_cost_record_payload,
    get_incident,
)

FIN = TEST_USERS["finance_chief_headers"]


# ─── Difficulty: dual_variant_calc / federal_estimated_vs_actual_share ───
def test_estimated_and_actual_federal_shares_diverge(api):
    """PRD §3.8: "`federal_share_estimated` is the sum, over the incident's eligible cost
    records in `ESTIMATED` status, of each record's `estimated_cost` multiplied by the
    applicable percentage and rounded to two decimal places; `federal_share_actual` is the
    sum, over the incident's eligible cost records in `ACTUAL` status, of each record's
    `actual_cost` multiplied by the applicable percentage and rounded to two decimal places."

    Design: Difficulty/dual_variant_calc/federal_estimated_vs_actual_share
    """
    inc = setup_eligible_incident(damage=5000000, declaration_category="EMERGENCY", name="Riverbend Flood")
    create_cost_record(inc["id"], category="LABOR", estimated_cost=100.00, eligible=True)
    cost_y = create_cost_record(inc["id"], category="CONTRACT", estimated_cost=100.00, eligible=True)
    finalize_cost_record(cost_y["id"], actual_cost=200.00)
    incident = get_incident(inc["id"])
    assert incident["federal_share_estimated"] == pytest.approx(75.00, abs=0.001)
    assert incident["federal_share_actual"] == pytest.approx(150.00, abs=0.001)
    assert incident["federal_share_estimated"] != incident["federal_share_actual"]


def test_total_committed_cost_uses_actual_when_finalized(api):
    """PRD §2.9: "Its `total_committed_cost` is the sum, over every cost record in either
    `ESTIMATED` or `ACTUAL` status, of that record's contribution — the record's `actual_cost`
    when it has reached `ACTUAL`, otherwise its `estimated_cost`."

    Design: Difficulty/dual_variant_calc/federal_estimated_vs_actual_share
    """
    inc = setup_eligible_incident(damage=5000000, declaration_category="EMERGENCY", name="Riverbend Flood")
    create_cost_record(inc["id"], category="LABOR", estimated_cost=100.00, eligible=True)
    cost_y = create_cost_record(inc["id"], category="CONTRACT", estimated_cost=100.00, eligible=True)
    finalize_cost_record(cost_y["id"], actual_cost=200.00)
    incident = get_incident(inc["id"])
    assert incident["total_committed_cost"] == pytest.approx(300.00, abs=0.001)


# ─── Difficulty: combinatorial_formula / federal_share_enhanced_tier_selection ───
def test_enhanced_tier_declaration_eligible(api):
    """PRD §3.7: "it becomes `ELIGIBLE` when `total_verified_damage` is at least the
    declaration threshold of 5,000,000 dollars, and remains `INELIGIBLE` below that; a total
    exactly equal to 5,000,000 is `ELIGIBLE`."

    Design: Difficulty/combinatorial_formula/federal_share_enhanced_tier_selection
    """
    inc = setup_eligible_incident(damage=10000000, declaration_category="MAJOR_DISASTER", name="Metro Quake")
    assert inc["declaration_status"] == "ELIGIBLE"


def test_enhanced_tier_applies_ninety_percent(api):
    """PRD §3.8: "Otherwise, when `declaration_category` is `MAJOR_DISASTER` and
    `total_verified_damage` is at least the enhanced damage threshold of 10,000,000 dollars,
    the enhanced share of 90 percent applies; in every other eligible case the base share of
    75 percent applies."

    Design: Difficulty/combinatorial_formula/federal_share_enhanced_tier_selection
    """
    inc = setup_eligible_incident(damage=10000000, declaration_category="MAJOR_DISASTER", name="Metro Quake")
    create_cost_record(inc["id"], category="CONTRACT", estimated_cost=1000.00, eligible=True)
    assert get_incident(inc["id"])["federal_share_estimated"] == pytest.approx(900.00, abs=0.001)


# ─── Difficulty: combinatorial_formula / cost_rollup_rounding_order ───
def test_per_record_rounding_yields_pinned_cent_total(api):
    """PRD §3.8: "The rounding order is fixed: each record's share is rounded to two decimals
    using round-half-up first, and only then are the rounded shares summed — summing first and
    rounding once would yield a different cent total and is not used."

    Design: Difficulty/combinatorial_formula/cost_rollup_rounding_order
    """
    inc = setup_eligible_incident(damage=5000000, declaration_category="EMERGENCY", name="County Wildfire")
    create_cost_record(inc["id"], category="MATERIALS", estimated_cost=6.02, eligible=True)
    create_cost_record(inc["id"], category="MATERIALS", estimated_cost=6.02, eligible=True)
    assert get_incident(inc["id"])["federal_share_estimated"] == pytest.approx(9.04, abs=0.001)


def test_rounding_order_is_not_sum_then_round(api):
    """PRD §3.8: "The rounding order is fixed: each record's share is rounded to two decimals
    using round-half-up first, and only then are the rounded shares summed — summing first and
    rounding once would yield a different cent total and is not used."

    Design: Difficulty/combinatorial_formula/cost_rollup_rounding_order
    """
    inc = setup_eligible_incident(damage=5000000, declaration_category="EMERGENCY", name="County Wildfire")
    create_cost_record(inc["id"], category="MATERIALS", estimated_cost=6.02, eligible=True)
    create_cost_record(inc["id"], category="MATERIALS", estimated_cost=6.02, eligible=True)
    # sum-then-round would give round(12.04*0.75)=9.03; per-record rounding gives 9.04.
    assert get_incident(inc["id"])["federal_share_estimated"] != pytest.approx(9.03, abs=0.001)


# ─── Difficulty: compensating_invariant / cost_ledger_conserved_on_void ───
def test_void_cost_record_transitions_to_void(api):
    """PRD §3.8: "A record may also be voided, moving it from `ESTIMATED` or from `ACTUAL` to
    the terminal `VOID` state; voiding removes the record's contribution from the incident's
    totals, a compensating action that conserves the ledger."

    Design: Difficulty/compensating_invariant/cost_ledger_conserved_on_void
    """
    inc = create_activated_incident(name="Debris Op", hazard_type="WILDFIRE")
    cost = create_cost_record(inc["id"], category="EQUIPMENT", estimated_cost=500.00, eligible=True)
    voided = void_cost_record(cost["id"])
    assert voided["status"] == "VOID", f"expected VOID, got {voided['status']}"


def test_void_cost_record_restores_committed_cost(api):
    """PRD §2.9: "Voiding a record removes its contribution from these sums, a compensating
    action that conserves the ledger. The `total_committed_cost` equals that defined sum at all
    times."

    Design: Difficulty/compensating_invariant/cost_ledger_conserved_on_void
    """
    inc = create_activated_incident(name="Debris Op", hazard_type="WILDFIRE")
    cost = create_cost_record(inc["id"], category="EQUIPMENT", estimated_cost=500.00, eligible=True)
    void_cost_record(cost["id"])
    assert get_incident(inc["id"])["total_committed_cost"] == pytest.approx(0.00, abs=0.001)


# ─── Corner: calculations / federal_share_zero_when_ineligible ───
def test_federal_share_zero_when_ineligible(api):
    """PRD §3.8: "When `declaration_status` is not `ELIGIBLE`, the percentage is zero."
    PRD §2.9: "Its `total_committed_cost` is the sum, over every cost record in either
    `ESTIMATED` or `ACTUAL` status, of that record's contribution — the record's `actual_cost`
    when it has reached `ACTUAL`, otherwise its `estimated_cost`."

    Design: Corner/calculations/federal_share_zero_when_ineligible
    """
    inc = create_activated_incident(name="Ineligible Ctx", hazard_type="FLOOD")
    create_cost_record(inc["id"], category="CONTRACT", estimated_cost=1000.00, eligible=True)
    incident = get_incident(inc["id"])
    assert incident["declaration_status"] == "INELIGIBLE"
    assert incident["federal_share_estimated"] == 0
    assert incident["total_committed_cost"] == pytest.approx(1000.00, abs=0.001)


# ─── Corner: calculations / ineligible_costrecord_excluded_from_federal_share ───
def test_ineligible_flag_excluded_from_federal_share(api):
    """PRD §3.8: "Only records whose `eligible` flag is true contribute."
    PRD §2.9: "Its `total_committed_cost` is the sum, over every cost record in either
    `ESTIMATED` or `ACTUAL` status, of that record's contribution — the record's `actual_cost`
    when it has reached `ACTUAL`, otherwise its `estimated_cost`."

    Design: Corner/calculations/ineligible_costrecord_excluded_from_federal_share
    """
    inc = setup_eligible_incident(damage=5000000, declaration_category="EMERGENCY", name="Filter Ctx")
    create_cost_record(inc["id"], category="CONTRACT", estimated_cost=1000.00, eligible=False)
    incident = get_incident(inc["id"])
    assert incident["total_committed_cost"] == pytest.approx(1000.00, abs=0.001)
    assert incident["federal_share_estimated"] == 0


# ─── Corner: state_machines / costrecord_void_then_actual_returns_invalid_state ───
def test_actual_from_void_cost_record_rejected(api):
    """PRD §3.8: "A record may also be voided, moving it from `ESTIMATED` or from `ACTUAL` to
    the terminal `VOID` state."
    PRD §2.7: "the system verifies that the target resource is in a valid originating state
    for the requested transition (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/costrecord_void_then_actual_returns_invalid_state
    """
    inc = create_activated_incident(name="Fin Ctx", hazard_type="WILDFIRE")
    cost = create_cost_record(inc["id"], category="LABOR", estimated_cost=250.00)
    void_cost_record(cost["id"])
    validate_error(
        api.transition_cost_record(cost["id"], {"to_status": "ACTUAL", "actual_cost": 300.00}, FIN),
        ApiErrorId.ERR_INVALID_STATE.value,
    )


# ─── Corner: validations / cost_record_exceeds_ceiling ───
def test_cost_record_exceeding_ceiling_rejected(api):
    """PRD §3.8: "The create also enforces the cost ceiling: adding the new record's
    `estimated_cost` to the incident's `total_committed_cost` must not push that total above
    the incident's `cost_ceiling`, where a result exactly equal to the ceiling is allowed; a
    create that would exceed it is rejected with `ERR_COST_CEILING_EXCEEDED`."

    Design: Corner/validations/cost_record_exceeds_ceiling
    """
    inc = create_activated_incident(name="Ceiling Ctx", hazard_type="WILDFIRE", cost_ceiling=100)
    version = incident_version(inc["id"])
    payload = create_cost_record_payload(inc["id"], version, category="LABOR", estimated_cost=200.00)
    validate_error(
        api.create_cost_record(payload, FIN),
        ApiErrorId.ERR_COST_CEILING_EXCEEDED.value,
    )
