"""Subrogation gross/net variants, recovery/dispute cycle, and liability conservation."""
from test_helpers import (
    validate_success, validate_error,
    create_pool_vehicle, create_subrogation_pending_claim,
    create_accident_claim_payload, TEST_USERS,
)

FIN = TEST_USERS["finance_officer_headers"]


# ─── dual_variant_calc / subrogation_gross_vs_net_diverge ───

def test_subrogation_gross_recoverable(api):
    """PRD §3.6: "The gross recoverable, gross_recoverable_cents, is the
    estimated_damage_cents multiplied by third_party_liable_pct, rounded half up."

    Design: Difficulty/dual_variant_calc/subrogation_gross_vs_net_diverge
    """
    vehicle = create_pool_vehicle(vin="VIN-AC-1")
    claim = create_subrogation_pending_claim(
        vehicle["id"], estimated_damage_cents=1000000, third_party_liable_pct=0.5,
        deductible_cents=50000)
    fetched = validate_success(api.get_accident_claim(claim["id"], FIN), 200)
    assert fetched["gross_recoverable_cents"] == 500000


def test_subrogation_net_recoverable_subtracts_deductible_and_admin_fee(api):
    """PRD §3.6: "The net recoverable, net_recoverable_cents, is that gross figure minus
    deductible_cents minus a fixed subrogation administration fee of 15,000 cents,
    floored at zero".

    Design: Difficulty/dual_variant_calc/subrogation_gross_vs_net_diverge
    """
    vehicle = create_pool_vehicle(vin="VIN-AC-2")
    claim = create_subrogation_pending_claim(
        vehicle["id"], estimated_damage_cents=1000000, third_party_liable_pct=0.5,
        deductible_cents=50000)
    fetched = validate_success(api.get_accident_claim(claim["id"], FIN), 200)
    assert fetched["net_recoverable_cents"] == 435000


# ─── non_linear_state_machine / accident_subrogation_dispute_cycle ───

def test_dispute_loops_claim_back_to_under_investigation(api):
    """PRD §3.6: "A dispute reverses part of a recovery and loops the claim
    SUBROGATION_PENDING → UNDER_INVESTIGATION".

    Design: Difficulty/non_linear_state_machine/accident_subrogation_dispute_cycle
    """
    vehicle = create_pool_vehicle(vin="VIN-CYC-1")
    claim = create_subrogation_pending_claim(
        vehicle["id"], estimated_damage_cents=1000000, third_party_liable_pct=0.5)
    validate_success(api.record_recovery(claim["id"], {"amount_cents": 200000}, FIN), 200)
    disputed = validate_success(api.dispute_claim(claim["id"], {"reversal_cents": 200000}, FIN), 200)
    assert disputed["status"] == "UNDER_INVESTIGATION"


def test_dispute_reverses_recovered_amount(api):
    """PRD §3.6: "it requires a positive reversal_cents that does not exceed the current
    recovered_cents (else ERR_SUBROGATION_INVALID), subtracts that reversal from
    recovered_cents, and recomputes outstanding_liable_cents the same way".

    Design: Difficulty/non_linear_state_machine/accident_subrogation_dispute_cycle
    """
    vehicle = create_pool_vehicle(vin="VIN-CYC-2")
    claim = create_subrogation_pending_claim(
        vehicle["id"], estimated_damage_cents=1000000, third_party_liable_pct=0.5)
    validate_success(api.record_recovery(claim["id"], {"amount_cents": 200000}, FIN), 200)
    disputed = validate_success(api.dispute_claim(claim["id"], {"reversal_cents": 200000}, FIN), 200)
    assert disputed["recovered_cents"] == 0


# ─── compensating_invariant / subrogation_recovery_dispute_conserves_liability ───

def test_recovery_reduces_outstanding_liability(api):
    """PRD §3.6: "A valid posting adds amount_cents to recovered_cents and recomputes
    outstanding_liable_cents as the gross recoverable minus recovered_cents."

    Design: Difficulty/compensating_invariant/subrogation_recovery_dispute_conserves_liability
    """
    vehicle = create_pool_vehicle(vin="VIN-9B")
    claim = create_subrogation_pending_claim(
        vehicle["id"], estimated_damage_cents=1000000, third_party_liable_pct=0.5)
    recovered = validate_success(api.record_recovery(claim["id"], {"amount_cents": 200000}, FIN), 200)
    assert recovered["recovered_cents"] == 200000
    assert recovered["outstanding_liable_cents"] == 300000


def test_dispute_conserves_recovered_plus_outstanding(api):
    """PRD §3.6: "recomputes outstanding_liable_cents the same way, so that recovered
    plus outstanding is conserved across a post-then-reverse pair."

    Design: Difficulty/compensating_invariant/subrogation_recovery_dispute_conserves_liability
    """
    vehicle = create_pool_vehicle(vin="VIN-9B2")
    claim = create_subrogation_pending_claim(
        vehicle["id"], estimated_damage_cents=1000000, third_party_liable_pct=0.5)
    validate_success(api.record_recovery(claim["id"], {"amount_cents": 200000}, FIN), 200)
    validate_success(api.dispute_claim(claim["id"], {"reversal_cents": 200000}, FIN), 200)
    fetched = validate_success(api.get_accident_claim(claim["id"], FIN), 200)
    assert fetched["recovered_cents"] == 0
    assert fetched["outstanding_liable_cents"] == 500000


# ─── validations / subrogate_at_fault_claim_returns_subrogation_invalid ───

def test_subrogate_at_fault_claim_returns_subrogation_invalid(api):
    """PRD §3.6: "Subrogation (UNDER_INVESTIGATION → SUBROGATION_PENDING) is defined only
    when the driver is not at fault and the third_party_liable_pct is greater than zero;
    a subrogation attempt that fails either condition is rejected with
    ERR_SUBROGATION_INVALID."

    Design: Corner/validations/subrogate_at_fault_claim_returns_subrogation_invalid
    """
    vehicle = create_pool_vehicle(vin="VIN-SUB-1")
    claim = validate_success(api.create_accident_claim(
        create_accident_claim_payload(vehicle["id"], at_fault=True,
                                      estimated_damage_cents=100000), FIN), 201)
    validate_success(api.investigate_claim(claim["id"], FIN), 200)
    validate_error(api.subrogate_claim(claim["id"], FIN), "ERR_SUBROGATION_INVALID")
