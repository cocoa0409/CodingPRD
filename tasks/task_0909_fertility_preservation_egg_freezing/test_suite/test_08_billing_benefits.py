"""Invoicing: tiered facility fee and pinned evaluation order, provisional-vs-settled benefit
coverage, and benefit-cap conservation across finalize/void.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
)
from test_helpers import fixtures as fx

BILLING = TEST_USERS["billing_admin_headers"]
COORD = TEST_USERS["coordinator_headers"]


# --------------------------------------------------------------- Difficulty: provisional vs settled
def test_provisional_coverage_capped_at_remaining_at_draft(api):
    """PRD §3.8: "At draft creation it is the provisional variant, reading remaining_cents as it
    stands at draft time and stored as estimated_coverage_cents." "The applied coverage is the
    smaller of that raw figure and the coverage's remaining_cents, so coverage is capped at the
    remaining cap rather than causing a rejection."

    Design: Difficulty/dual_variant_calc/benefit_provisional_vs_settled
    """
    b = fx.setup_benefit_coverage(annual_cap_cents=40000, covered_pct=0.5,
                                  covered_service_types=["CYCLE"])
    inv = fx.create_invoice(b["patient_id"], "CYCLE", [{"description": "stim", "amount_cents": 100000}])
    # raw = round_half_up(0.5 * 100000) = 50000; capped at remaining 40000.
    assert inv["estimated_coverage_cents"] == 40000, \
        f"provisional coverage must cap at 40000, got {inv['estimated_coverage_cents']}"


def test_settled_coverage_diverges_after_intervening_finalize(api):
    """PRD §3.8: "At finalize it is the final variant, re-reading `remaining_cents` after any
    intervening finalized or voided invoices and stored as `settled_coverage_cents`; because the
    cap may have moved in between, the settled figure can diverge from the provisional one, and
    the finalized `total_due_cents` uses the settled figure."

    Design: Difficulty/dual_variant_calc/benefit_provisional_vs_settled
    """
    b = fx.setup_benefit_coverage(annual_cap_cents=40000, covered_pct=0.5,
                                  covered_service_types=["CYCLE"])
    inv_b = fx.create_invoice(b["patient_id"], "CYCLE",
                              [{"description": "stim", "amount_cents": 100000}])
    assert inv_b["estimated_coverage_cents"] == 40000
    # An intervening invoice A consumes part of the cap before B is finalized.
    inv_a = fx.create_invoice(b["patient_id"], "CYCLE",
                              [{"description": "labs", "amount_cents": 20000}])
    fx.finalize_invoice(inv_a["id"])  # settles min(40000, 10000) = 10000; remaining -> 30000
    settled_b = fx.finalize_invoice(inv_b["id"])
    # raw for B = 50000; capped at remaining 30000.
    assert settled_b["settled_coverage_cents"] == 30000, \
        f"settled coverage must be 30000, got {settled_b['settled_coverage_cents']}"
    assert settled_b["settled_coverage_cents"] != inv_b["estimated_coverage_cents"], \
        "settled figure must diverge from the provisional 40000"


# --------------------------------------------------------------- Difficulty: tiered facility fee
def test_invoice_low_tier_facility_fee_and_total(api):
    """PRD §3.8: "a facility percentage is selected by tier on that subtotal: 0.05 when the
    subtotal is below 500,000 cents ... facility_fee_cents is the subtotal multiplied by that
    percentage, rounded half-up to a whole cent ... the amount due is the subtotal plus the
    facility fee minus the applicable coverage."

    Design: Difficulty/combinatorial_formula/invoice_total_tiered_facility_fee_circular
    """
    b = fx.setup_benefit_coverage(annual_cap_cents=40000, covered_pct=0.5,
                                  covered_service_types=["CYCLE"])
    inv = fx.create_invoice(b["patient_id"], "CYCLE",
                            [{"description": "stim cycle", "amount_cents": 100000}])
    assert inv["subtotal_cents"] == 100000
    assert inv["facility_fee_cents"] == 5000, f"0.05 tier => 5000, got {inv['facility_fee_cents']}"
    assert inv["estimated_coverage_cents"] == 40000
    # total = 100000 + 5000 - 40000 = 65000.
    assert inv["total_due_cents"] == 65000, f"total_due must be 65000, got {inv['total_due_cents']}"


def test_invoice_mid_tier_facility_fee(api):
    """PRD §3.8: "0.03 when the subtotal is at least 500,000 but below 1,500,000 cents ...
    facility_fee_cents is the subtotal multiplied by that percentage, rounded half-up to a whole
    cent ... the amount due is the subtotal plus the facility fee minus the applicable coverage."

    Design: Difficulty/combinatorial_formula/invoice_total_tiered_facility_fee_circular
    """
    patient = fx.create_patient()  # no benefit coverage => coverage 0
    inv = fx.create_invoice(patient["id"], "CYCLE",
                            [{"description": "big cycle", "amount_cents": 600000}])
    assert inv["subtotal_cents"] == 600000
    # round_half_up(0.03 * 600000) = 18000.
    assert inv["facility_fee_cents"] == 18000, f"0.03 tier => 18000, got {inv['facility_fee_cents']}"
    assert inv["total_due_cents"] == 618000, f"total_due must be 618000, got {inv['total_due_cents']}"


# --------------------------------------------------------------- Difficulty: cap conservation
def test_finalize_consumes_cap(api):
    """PRD §3.8: "Finalization recomputes ... and then cascades to the benefit ledger: the
    coverage's consumed_cents increases by the settled coverage, remaining_cents is recomputed."
    PRD §2.7: "consumed plus remaining always equals the annual cap."

    Design: Difficulty/compensating_invariant/benefit_cap_conservation_finalize_void
    """
    b = fx.setup_benefit_coverage(annual_cap_cents=100000, covered_pct=0.5,
                                  covered_service_types=["CYCLE"])
    inv = fx.create_invoice(b["patient_id"], "CYCLE",
                            [{"description": "cycle", "amount_cents": 40000}])
    fx.finalize_invoice(inv["id"])  # settles min(100000, 20000) = 20000
    cov = validate_success(api.get_benefit_coverage(b["benefit_id"], COORD), 200)
    assert cov["consumed_cents"] == 20000, f"finalize must consume 20000, got {cov['consumed_cents']}"
    assert cov["remaining_cents"] == 80000, f"remaining must be 80000, got {cov['remaining_cents']}"
    assert cov["consumed_cents"] + cov["remaining_cents"] == 100000


def test_void_restores_cap_and_reactivates(api):
    """PRD §3.8: "Voiding a finalized invoice ... compensates the ledger: the coverage's
    consumed_cents decreases by that invoice's settled_coverage_cents, remaining_cents is
    restored, and a coverage that had been EXHAUSTED returns to ACTIVE once its remaining_cents
    is greater than 0."

    Design: Difficulty/compensating_invariant/benefit_cap_conservation_finalize_void
    """
    b = fx.setup_benefit_coverage(annual_cap_cents=100000, covered_pct=0.5,
                                  covered_service_types=["CYCLE"])
    inv = fx.create_invoice(b["patient_id"], "CYCLE",
                            [{"description": "cycle", "amount_cents": 40000}])
    fx.finalize_invoice(inv["id"])
    validate_success(api.void_invoice(inv["id"], BILLING), 200)
    cov = validate_success(api.get_benefit_coverage(b["benefit_id"], COORD), 200)
    assert cov["consumed_cents"] == 0, f"void must restore consumed to 0, got {cov['consumed_cents']}"
    assert cov["remaining_cents"] == 100000, f"remaining must restore to cap, got {cov['remaining_cents']}"
    assert cov["status"] == "ACTIVE", "coverage must be ACTIVE after cap restored"
