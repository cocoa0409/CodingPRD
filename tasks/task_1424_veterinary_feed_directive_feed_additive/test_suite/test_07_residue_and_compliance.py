"""Residue cases and clinic compliance: tiered penalty rounding on confirm,
score conservation on dismiss (PRD §2.9, §3.8)."""
import pytest

from test_helpers import (
    validate_success,
    ApiErrorId, TEST_USERS,
    setup_case_under_investigation,
)

INSPECTOR = TEST_USERS["inspector_headers"]


def _setup_ratio_37_case():
    """Full delivered chain plus a ResidueCase in UNDER_INVESTIGATION.

    Confirming with residue_ppb=370 / tolerance_ppb=100 yields ratio 3.7:
    severity TIER_2, and per the PRD §3.8 marginal schedule:
      tier 1: round(min(3.7, 2.0) - 1.0) * 50  = round(1.0) * 50  = 50
      tier 2: round(min(3.7, 5.0) - 2.0) * 150 = round(1.7) * 150 = 300
      flat administrative penalty              = 100
      total penalty_score_deduction            = 450
    """
    return setup_case_under_investigation(
        drug_overrides={"withdrawal_hours": 48},
        vfd_overrides={"authorized_animal_count": 20},
        order_overrides={"animal_count": 5},
    )


# ─── Difficulty: compliance_penalty_tiered_marginal_rounding ───

def test_confirm_computes_severity_tier_and_tiered_penalty(api):
    """PRD §3.8: "if the ratio is strictly less than 2.0 the case's
    `severity_tier` is `TIER_1`; otherwise if the ratio is strictly less than 5.0
    the `severity_tier` is `TIER_2`; otherwise the `severity_tier` is `TIER_3`."
    PRD §3.8: "If the ratio exceeds 1.0, add the first-tier marginal: take the
    smaller of the ratio and 2.0, subtract 1.0, round the result half-up to an
    integer, and multiply by 50. If the ratio exceeds 2.0, add the second-tier
    marginal: take the smaller of the ratio and 5.0, subtract 2.0, round half-up
    to an integer, and multiply by 150. ... Finally, add a flat administrative
    penalty of 100 for any confirmed violation. The order of operations is
    load-bearing: each tier's marginal amount is rounded before summing"

    Design: Difficulty/combinatorial_formula/compliance_penalty_tiered_marginal_rounding
    """
    chain = _setup_ratio_37_case()
    case = validate_success(api.confirm_residue_case(
        chain["case"]["id"], {"residue_ppb": 370, "tolerance_ppb": 100}, INSPECTOR,
    ), 200)
    assert case["status"] == "CONFIRMED_VIOLATION"
    assert case["severity_tier"] == "TIER_2", (
        f"ratio 3.7 must be TIER_2 (2.0 <= 3.7 < 5.0), got {case['severity_tier']}"
    )
    assert case["penalty_score_deduction"] == 450, (
        f"Expected round-per-tier-then-sum deduction 450, got {case['penalty_score_deduction']}"
    )


def test_confirm_debits_issuing_clinic_score_and_flips_audit_ready(api):
    """PRD §3.8: "The resulting `penalty_score_deduction` is recorded on the case
    and subtracted from the issuing clinic's `compliance_score`, walking the
    chronological path from the feed order back through its VFD to its
    veterinarian and finally to that veterinarian's clinic."
    PRD §2.9: "The clinic's `audit_ready` flag is true exactly when two conditions
    hold simultaneously: the clinic's `compliance_score` is at least 700, and no
    `ResidueCase` in status `OPEN` exists on any producer reached through any VFD
    issued by any veterinarian of that clinic."

    Design: Difficulty/combinatorial_formula/compliance_penalty_tiered_marginal_rounding
    """
    chain = _setup_ratio_37_case()
    clinic_before = validate_success(api.get_clinic(chain["clinic"]["id"], INSPECTOR), 200)
    assert clinic_before["compliance_score"] == 1000

    validate_success(api.confirm_residue_case(
        chain["case"]["id"], {"residue_ppb": 370, "tolerance_ppb": 100}, INSPECTOR,
    ), 200)

    clinic_after = validate_success(api.get_clinic(chain["clinic"]["id"], INSPECTOR), 200)
    assert clinic_after["compliance_score"] == 550, (
        f"Expected 1000 - 450 = 550, got {clinic_after['compliance_score']}"
    )
    assert clinic_after["audit_ready"] is False, (
        "audit_ready must flip to false when compliance_score drops below 700 (PRD §2.9)"
    )


# ─── Difficulty: clinic_compliance_score_conserved_across_confirm_dismiss ───

def test_dismissed_case_leaves_clinic_score_unchanged(api):
    """PRD §3.8: "From `OPEN` or `UNDER_INVESTIGATION` an inspector may dismiss
    the case, moving it to `DISMISSED`." The penalty schedule applies only to a
    confirmed violation: "The resulting `penalty_score_deduction` is recorded on
    the case and subtracted from the issuing clinic's `compliance_score`" (§3.8,
    on confirming) — a dismissed case applies no deduction.

    Design: Difficulty/compensating_invariant/clinic_compliance_score_conserved_across_confirm_dismiss
    """
    chain = setup_case_under_investigation()
    case = validate_success(
        api.dismiss_residue_case(chain["case"]["id"], INSPECTOR), 200)
    assert case["status"] == "DISMISSED"

    clinic_after = validate_success(api.get_clinic(chain["clinic"]["id"], INSPECTOR), 200)
    assert clinic_after["compliance_score"] == 1000, (
        f"Dismissal must not debit the clinic, got {clinic_after['compliance_score']}"
    )


def test_after_dismiss_no_open_case_clinic_is_audit_ready(api):
    """PRD §2.9: "The clinic's `audit_ready` flag is true exactly when two
    conditions hold simultaneously: the clinic's `compliance_score` is at least
    700, and no `ResidueCase` in status `OPEN` exists on any producer reached
    through any VFD issued by any veterinarian of that clinic."

    Design: Difficulty/compensating_invariant/clinic_compliance_score_conserved_across_confirm_dismiss
    """
    chain = setup_case_under_investigation()
    validate_success(api.dismiss_residue_case(chain["case"]["id"], INSPECTOR), 200)

    clinic_after = validate_success(api.get_clinic(chain["clinic"]["id"], INSPECTOR), 200)
    assert clinic_after["compliance_score"] == 1000
    assert clinic_after["audit_ready"] is True, (
        "With score >= 700 and no OPEN ResidueCase, audit_ready must be true (PRD §2.9)"
    )
