"""Contrast screening decision (dual variant + precedence + boundary) and
report turnaround / turnaround-met calculations.

Translates Difficulty/dual_variant_calc (screening), Difficulty/combinatorial_formula
(screening precedence), and Corner/calculations (turnaround) and the screening
Corner instances.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success, validate_error,
    create_screening_payload,
    TEST_USERS, make_nurse_headers, make_radiologist_headers,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["center_admin_headers"]
CLERK = TEST_USERS["scheduling_clerk_headers"]


# ─── Difficulty: dual-variant screening (contrast vs non-contrast) ────

def test_screening_contrast_vs_non_contrast_variant(api):
    """PRD §3.3: "If the order's protocol uses contrast and the patient has a
    documented contrast allergy, the screening is `BLOCKED` with reason
    `CONTRAST_ALLERGY`."
    PRD §3.3: "For a non-contrast protocol, the renal and contrast-allergy gates
    are inert because they only apply to contrast studies".

    Design: Difficulty/dual_variant_calc/screening_contrast_vs_non_contrast_variant
    """
    center = fx.create_center(name="C")
    modality = fx.create_modality(center["id"], modality_type="MRI", name="MRI",
                                  base_rvu=2.0, requires_prior_auth=False)
    nurse = fx.create_staff(center["id"], "NURSE", full_name="N", credentialed_modalities=["MRI"])
    nh = make_nurse_headers(nurse["id"])

    order_a = fx.create_order(center["id"], modality["id"], patient_mrn="MA",
                              ordering_provider_npi="N1", requires_contrast=True)
    order_b = fx.create_order(center["id"], modality["id"], patient_mrn="MB",
                              ordering_provider_npi="N1", requires_contrast=False)
    scr_a = validate_success(api.create_screening(order_a["id"],
            create_screening_payload(egfr_value=29, has_contrast_allergy=True,
                                     is_pregnant=False, metal_implant_unsafe=False), nh), 201)
    scr_b = validate_success(api.create_screening(order_b["id"],
            create_screening_payload(egfr_value=29, has_contrast_allergy=True,
                                     is_pregnant=False, metal_implant_unsafe=False), nh), 201)
    eval_a = validate_success(api.evaluate_screening(scr_a["id"], nh), 200)
    eval_b = validate_success(api.evaluate_screening(scr_b["id"], nh), 200)
    assert eval_a["outcome"] == "BLOCKED"
    assert eval_a["blocking_reason"] == "CONTRAST_ALLERGY"
    assert eval_b["outcome"] == "CLEARED"
    assert eval_b["blocking_reason"] is None


def test_screening_contrast_blocks_on_allergy_again(api):
    """Second translation of the dual-variant rule, isolating the contrast
    branch BLOCKED outcome (allergy gate live under a contrast protocol).

    PRD §3.3: "If the order's protocol uses contrast and the patient has a
    documented contrast allergy, the screening is `BLOCKED` with reason
    `CONTRAST_ALLERGY`."

    Design: Difficulty/dual_variant_calc/screening_contrast_vs_non_contrast_variant
    """
    center = fx.create_center(name="C")
    modality = fx.create_modality(center["id"], modality_type="MRI", name="MRI",
                                  base_rvu=2.0, requires_prior_auth=False)
    nurse = fx.create_staff(center["id"], "NURSE", full_name="N", credentialed_modalities=["MRI"])
    nh = make_nurse_headers(nurse["id"])
    order = fx.create_order(center["id"], modality["id"], requires_contrast=True)
    scr = validate_success(api.create_screening(order["id"],
          create_screening_payload(egfr_value=80, has_contrast_allergy=True), nh), 201)
    evaluated = validate_success(api.evaluate_screening(scr["id"], nh), 200)
    assert evaluated["outcome"] == "BLOCKED"
    assert evaluated["blocking_reason"] == "CONTRAST_ALLERGY"


# ─── Difficulty: precedence (pregnancy before allergy) ────────────────

def test_screening_precedence_pregnancy_over_allergy(api):
    """PRD §3.3: "The decision walks four hard-stop conditions in this fixed
    precedence, and the first one that matches sets `outcome` to `BLOCKED` and
    writes the corresponding `blocking_reason`".
    PRD §3.3: "If the patient is pregnant and either the order's protocol uses
    contrast or the modality is `CT`, the screening is `BLOCKED` with reason
    `PREGNANCY`."

    Design: Difficulty/combinatorial_formula/screening_precedence_pregnancy_over_allergy_order
    """
    center = fx.create_center(name="C")
    modality = fx.create_modality(center["id"], modality_type="CT", name="CT",
                                  base_rvu=3.0, requires_prior_auth=False)
    nurse = fx.create_staff(center["id"], "NURSE", full_name="N", credentialed_modalities=["CT"])
    nh = make_nurse_headers(nurse["id"])
    order = fx.create_order(center["id"], modality["id"], requires_contrast=True)
    scr = validate_success(api.create_screening(order["id"],
          create_screening_payload(egfr_value=10, has_contrast_allergy=True,
                                   is_pregnant=True, metal_implant_unsafe=False), nh), 201)
    evaluated = validate_success(api.evaluate_screening(scr["id"], nh), 200)
    assert evaluated["outcome"] == "BLOCKED"
    assert evaluated["blocking_reason"] == "PREGNANCY"


def test_screening_precedence_pregnancy_over_renal(api):
    """Second translation of the fixed-precedence rule: pregnancy (rule 1)
    pre-empts renal (rule 4) for a contrast CT study with low eGFR.

    PRD §3.3: "The decision walks four hard-stop conditions in this fixed
    precedence, and the first one that matches sets `outcome` to `BLOCKED`".
    PRD §3.3: "If the patient is pregnant and either the order's protocol uses
    contrast or the modality is `CT`, the screening is `BLOCKED` with reason
    `PREGNANCY`."

    Design: Difficulty/combinatorial_formula/screening_precedence_pregnancy_over_allergy_order
    """
    center = fx.create_center(name="C")
    modality = fx.create_modality(center["id"], modality_type="CT", name="CT",
                                  base_rvu=3.0, requires_prior_auth=False)
    nurse = fx.create_staff(center["id"], "NURSE", full_name="N", credentialed_modalities=["CT"])
    nh = make_nurse_headers(nurse["id"])
    order = fx.create_order(center["id"], modality["id"], requires_contrast=True)
    scr = validate_success(api.create_screening(order["id"],
          create_screening_payload(egfr_value=10, has_contrast_allergy=False,
                                   is_pregnant=True, metal_implant_unsafe=False), nh), 201)
    evaluated = validate_success(api.evaluate_screening(scr["id"], nh), 200)
    assert evaluated["outcome"] == "BLOCKED"
    assert evaluated["blocking_reason"] == "PREGNANCY"


# ─── Corner: screening blocks/clears ──────────────────────────────────

def test_screening_blocked_renal_low_egfr(api):
    """PRD §3.3: "If the order's protocol uses contrast and the patient's
    `egfr_value` is strictly below 30 (the minimum safe eGFR for contrast
    administration), the screening is `BLOCKED` with reason `RENAL_FUNCTION`."

    Design: Corner/state_machines/error_screening_blocked_renal_low_egfr
    """
    center = fx.create_center(name="C")
    modality = fx.create_modality(center["id"], modality_type="CT", name="CT",
                                  base_rvu=3.0, requires_prior_auth=False)
    nurse = fx.create_staff(center["id"], "NURSE", full_name="N", credentialed_modalities=["CT"])
    nh = make_nurse_headers(nurse["id"])
    order = fx.create_order(center["id"], modality["id"], requires_contrast=True)
    scr = validate_success(api.create_screening(order["id"],
          create_screening_payload(egfr_value=29, has_contrast_allergy=False,
                                   is_pregnant=False, metal_implant_unsafe=False), nh), 201)
    evaluated = validate_success(api.evaluate_screening(scr["id"], nh), 200)
    assert evaluated["outcome"] == "BLOCKED"
    assert evaluated["blocking_reason"] == "RENAL_FUNCTION"


def test_screening_egfr_exactly_30_clears(api):
    """PRD §3.3: "If the order's protocol uses contrast and the patient's
    `egfr_value` is strictly below 30 (the minimum safe eGFR for contrast
    administration), the screening is `BLOCKED` with reason `RENAL_FUNCTION`."
    PRD §3.3: "If none of the four conditions matches, the screening clears:
    `outcome` becomes `CLEARED` and `blocking_reason` remains null."

    Design: Corner/calculations/error_screening_egfr_exactly_30_clears
    """
    center = fx.create_center(name="C")
    modality = fx.create_modality(center["id"], modality_type="CT", name="CT",
                                  base_rvu=3.0, requires_prior_auth=False)
    nurse = fx.create_staff(center["id"], "NURSE", full_name="N", credentialed_modalities=["CT"])
    nh = make_nurse_headers(nurse["id"])
    order = fx.create_order(center["id"], modality["id"], requires_contrast=True)
    scr = validate_success(api.create_screening(order["id"],
          create_screening_payload(egfr_value=30, has_contrast_allergy=False,
                                   is_pregnant=False, metal_implant_unsafe=False), nh), 201)
    evaluated = validate_success(api.evaluate_screening(scr["id"], nh), 200)
    assert evaluated["outcome"] == "CLEARED"
    assert evaluated["blocking_reason"] is None


# ─── Corner: report turnaround / turnaround_met ───────────────────────

def test_turnaround_met_routine_within_target(api):
    """PRD §3.6: "`report_turnaround_minutes` is the difference between the
    exam's `signed_off_at_utc` and its `acquired_at_utc`, expressed in minutes
    (the millisecond difference divided by sixty thousand), rounded half-up to 2
    decimal places."
    PRD §3.6: "a turnaround less than or equal to the target counts as met (the
    boundary value, exactly equal to the target, is met)."
    PRD §3.6: "For `ROUTINE` orders the target is 1440 minutes for `MRI`, 720 for
    `CT`, 240 for `XRAY`, and 480 for `US`."

    Design: Corner/calculations/turnaround_met_routine_within_target
    """
    setup = fx.setup_signed_off(modality_type="XRAY", base_rvu=1.0, priority="ROUTINE",
                                requires_contrast=False,
                                acquired_clock="2026-06-01T09:00:00Z",
                                signoff_clock="2026-06-01T09:40:00Z")
    order = validate_success(api.get_order(setup["order_id"], CLERK), 200)
    assert order["report_turnaround_minutes"] == 40.0
    assert order["turnaround_met"] is True


def test_turnaround_missed_stat_over_target(api):
    """PRD §3.6: "The `turnaround_met` flag is then set by comparing the
    turnaround against a target chosen by modality and priority: a turnaround
    less than or equal to the target counts as met".
    PRD §3.6: "For `STAT` orders the target in minutes is 60 for `MRI`, 45 for
    `CT`, 30 for `XRAY`, and 45 for `US`."

    Design: Corner/calculations/turnaround_missed_stat_over_target
    """
    setup = fx.setup_signed_off(modality_type="XRAY", base_rvu=1.0, priority="STAT",
                                requires_contrast=False,
                                acquired_clock="2026-06-01T09:00:00Z",
                                signoff_clock="2026-06-01T09:40:00Z")
    order = validate_success(api.get_order(setup["order_id"], CLERK), 200)
    assert order["report_turnaround_minutes"] == 40.0
    assert order["turnaround_met"] is False
