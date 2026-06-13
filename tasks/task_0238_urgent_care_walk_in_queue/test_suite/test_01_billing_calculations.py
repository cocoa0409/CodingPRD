"""Billing computation tests: subtotal aggregation, the dual-variant patient
responsibility calculation, rounding order, and input-set filtering (PRD §3.7).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    make_provider_headers,
    TEST_USERS,
    setup_visit_with_charges,
    post_charges,
)

_PROVIDER = lambda pid: make_provider_headers(pid)  # noqa: E731


# ─── dual_variant_calc / charge_total_insured_vs_self_pay_diverges ────

def test_charge_total_insured_eligible_yields_flat_copay():
    """PRD §3.7: "Under verified insurance — the coverage is INSURANCE with
    eligibility_status ELIGIBLE — the patient owes a flat copay_cents,
    independent of the subtotal, because the payer covers the balance."

    Design: Difficulty/dual_variant_calc/charge_total_insured_vs_self_pay_diverges
    """
    setup = setup_visit_with_charges(
        [20000], coverage_type="INSURANCE",
        coverage_overrides={"payer_name": "Aetna", "member_id": "M1", "copay_cents": 1500},
        verify_outcome="ELIGIBLE")
    visit = post_charges(setup["visit"]["id"], setup["provider"]["id"])
    assert visit["charges_subtotal_cents"] == 20000
    assert visit["patient_responsibility_cents"] == 1500, (
        f"verified-insurance responsibility should be the flat copay 1500, "
        f"got {visit['patient_responsibility_cents']}")


def test_charge_total_self_pay_yields_discounted_subtotal():
    """PRD §3.7: "the patient owes the subtotal reduced by the clinic's self-pay
    discount: the subtotal multiplied by one minus self_pay_discount_pct, rounded
    half-up to whole cents."

    Design: Difficulty/dual_variant_calc/charge_total_insured_vs_self_pay_diverges
    """
    setup = setup_visit_with_charges(
        [20000], coverage_type="SELF_PAY", clinic_overrides={"self_pay_discount_pct": 0.30})
    visit = post_charges(setup["visit"]["id"], setup["provider"]["id"])
    assert visit["charges_subtotal_cents"] == 20000
    # 20000 * (1 - 0.30) = 14000
    assert visit["patient_responsibility_cents"] == 14000, (
        f"self-pay responsibility should be 14000 (20000*0.70), "
        f"got {visit['patient_responsibility_cents']}")


def test_charge_total_same_charges_diverge_by_coverage():
    """PRD §3.7: "The same set of charge lines thus yields a flat copay under
    verified insurance but a discount-scaled amount under self-pay."

    Design: Difficulty/dual_variant_calc/charge_total_insured_vs_self_pay_diverges
    """
    insured = setup_visit_with_charges(
        [20000], coverage_type="INSURANCE",
        coverage_overrides={"payer_name": "Aetna", "member_id": "M1", "copay_cents": 1500},
        verify_outcome="ELIGIBLE", clinic_overrides={"self_pay_discount_pct": 0.30})
    self_pay = setup_visit_with_charges(
        [20000], coverage_type="SELF_PAY", clinic_overrides={"self_pay_discount_pct": 0.30})
    insured_visit = post_charges(insured["visit"]["id"], insured["provider"]["id"])
    self_pay_visit = post_charges(self_pay["visit"]["id"], self_pay["provider"]["id"])
    assert insured_visit["patient_responsibility_cents"] == 1500
    assert self_pay_visit["patient_responsibility_cents"] == 14000
    assert insured_visit["patient_responsibility_cents"] != self_pay_visit["patient_responsibility_cents"]


# ─── combinatorial_formula / charge_total_sum_then_discount_then_round_order ─

def test_charge_total_rounding_applied_once_after_discount():
    """PRD §3.7: "The order is pinned: the subtotal is computed first, then the
    coverage rule is applied, and rounding happens once at the very end rather
    than per line."

    Design: Difficulty/combinatorial_formula/charge_total_sum_then_discount_then_round_order
    """
    setup = setup_visit_with_charges(
        [4001, 4001, 4001], coverage_type="SELF_PAY",
        clinic_overrides={"self_pay_discount_pct": 0.30})
    visit = post_charges(setup["visit"]["id"], setup["provider"]["id"])
    assert visit["charges_subtotal_cents"] == 12003
    # round_half_up(12003 * 0.70) = round_half_up(8402.1) = 8402,
    # NOT per-line round(4001*0.70)*3 = 2801*3 = 8403.
    assert visit["patient_responsibility_cents"] == 8402, (
        f"sum-then-discount-then-round-once should give 8402, "
        f"got {visit['patient_responsibility_cents']}")


def test_charge_total_subtotal_is_sum_of_lines():
    """PRD §3.7: "The charges_subtotal_cents is the sum of amount_cents over the
    visit's charges where voided is false and source_type is VISIT".

    Design: Difficulty/combinatorial_formula/charge_total_sum_then_discount_then_round_order
    """
    setup = setup_visit_with_charges(
        [4001, 4001, 4001], coverage_type="SELF_PAY",
        clinic_overrides={"self_pay_discount_pct": 0.30})
    visit = post_charges(setup["visit"]["id"], setup["provider"]["id"])
    assert visit["charges_subtotal_cents"] == 12003, (
        f"subtotal should be 4001*3 = 12003, got {visit['charges_subtotal_cents']}")


# ─── calculations / insured_unverified_falls_back_to_self_pay_input_set ───

def test_insured_unverified_falls_back_to_self_pay():
    """PRD §3.7: "or an INSURANCE coverage whose eligibility_status is still
    UNVERIFIED or is INELIGIBLE, both of which fall back to self-pay — the patient
    owes the subtotal reduced by the clinic's self-pay discount".

    Design: Corner/calculations/insured_unverified_falls_back_to_self_pay_input_set
    """
    setup = setup_visit_with_charges(
        [10000], coverage_type="INSURANCE",
        coverage_overrides={"payer_name": "Humana", "member_id": "U1", "copay_cents": 500},
        clinic_overrides={"self_pay_discount_pct": 0.30})  # no verify -> UNVERIFIED
    visit = post_charges(setup["visit"]["id"], setup["provider"]["id"])
    # 10000 * 0.70 = 7000, NOT the 500 copay.
    assert visit["patient_responsibility_cents"] == 7000, (
        f"unverified insurance should fall back to self-pay (7000), "
        f"got {visit['patient_responsibility_cents']}")


# ─── calculations / occ_health_charge_excluded_from_patient_responsibility ───

def test_occ_health_charge_excluded_from_responsibility():
    """PRD §3.7: "occupational-health charges are employer-billed and are excluded
    from patient responsibility."

    Design: Corner/calculations/occ_health_charge_excluded_from_patient_responsibility
    """
    setup = setup_visit_with_charges(
        [5000, 9000], source_types=["VISIT", "OCC_HEALTH"], coverage_type="SELF_PAY",
        clinic_overrides={"self_pay_discount_pct": 0.30})
    visit = post_charges(setup["visit"]["id"], setup["provider"]["id"])
    # Only the 5000 VISIT charge counts: subtotal 5000, responsibility 5000*0.70=3500.
    assert visit["charges_subtotal_cents"] == 5000, (
        f"subtotal should exclude OCC_HEALTH charge (5000), "
        f"got {visit['charges_subtotal_cents']}")
    assert visit["patient_responsibility_cents"] == 3500, (
        f"responsibility should be 5000*0.70 = 3500, "
        f"got {visit['patient_responsibility_cents']}")


# ─── endpoints / computed_read_visit_surfaces_responsibility ───

def test_get_visit_surfaces_computed_totals():
    """PRD §3.7 dual-variant self-pay branch; PRD §2.8: "the computed
    charges_subtotal_cents and patient_responsibility_cents on a visit."

    Design: Corner/endpoints/computed_read_visit_surfaces_responsibility
    """
    setup = setup_visit_with_charges(
        [8000], coverage_type="SELF_PAY", clinic_overrides={"self_pay_discount_pct": 0.30})
    post_charges(setup["visit"]["id"], setup["provider"]["id"])
    fetched = validate_success(
        api_client.get_visit(setup["visit"]["id"], TEST_USERS["front_desk_headers"]), 200)
    assert fetched["charges_subtotal_cents"] == 8000
    # 8000 * 0.70 = 5600
    assert fetched["patient_responsibility_cents"] == 5600, (
        f"GET should surface responsibility 5600, got {fetched['patient_responsibility_cents']}")
