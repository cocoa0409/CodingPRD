"""Remittance adjudication: the dual-variant allowed-amount calculation, the cyclic
denial-appeal-resubmit loop, and remittance validation gates.

Translates difficulty queue (dual_variant_calc, non_linear_state_machine cyclic)
and corner queue (calculations medicaid factor, state_machines invalid transition,
validations).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    setup_agency_org,
    create_medicare_plan,
    create_plan,
    create_patient_with_coverages,
    setup_documentation_complete,
    submit_primary_claim,
    post_remittance,
    transport_version,
)
from test_helpers import factories as F


# ---------------------------------------------------------------------------
# dual_variant_calc / adjudicated_allowed_payer_reported_vs_fee_schedule
# (queue A, 2 tests)
# ---------------------------------------------------------------------------

def test_adjudicated_allowed_uses_reported_figure_verbatim(api):
    """PRD §3.7: "When `reported_allowed_cents` is provided, the allowed amount is
    that reported figure verbatim."

    Design: Difficulty/dual_variant_calc/adjudicated_allowed_payer_reported_vs_fee_schedule
    """
    org = setup_agency_org()
    med = create_medicare_plan(org)
    pat = create_patient_with_coverages(org, [{"payer_plan_id": med["id"], "policy_rank": 1}])
    t = setup_documentation_complete(org, pat["id"], "RUN-A", "ALS1",
                                     loaded_miles=12.0, emergency_indicator=True)
    claim = submit_primary_claim(org, t["id"], med["id"])
    get_success_data(api.create_remittance(
        claim["id"], F.create_remittance_payload("PAID", 40000, reported_allowed_cents=50000),
        org["biller_h"]))
    adjudicated = get_success_data(api.get_claim(claim["id"], org["biller_h"]))
    assert adjudicated["allowed_amount_cents"] == 50000


def test_adjudicated_allowed_derived_from_fee_schedule_when_null(api):
    """PRD §3.7: "When `reported_allowed_cents` is null, the allowed amount is derived
    from the Medicare fee-schedule baseline for this transport's charges, scaled by
    payer type: for a `MEDICARE` plan the allowed amount equals the baseline".
    PRD §3.7: "the schedule in which ... `A0427` is 41000 cents" and "the mileage
    component (computed at 800 cents per loaded mile".

    Design: Difficulty/dual_variant_calc/adjudicated_allowed_payer_reported_vs_fee_schedule
    """
    org = setup_agency_org()
    med = create_medicare_plan(org)
    pat = create_patient_with_coverages(org, [{"payer_plan_id": med["id"], "policy_rank": 1}])
    t = setup_documentation_complete(org, pat["id"], "RUN-B", "ALS1",
                                     loaded_miles=12.0, emergency_indicator=True)
    claim = submit_primary_claim(org, t["id"], med["id"])
    get_success_data(api.create_remittance(
        claim["id"], F.create_remittance_payload("PAID", 40000), org["biller_h"]))
    adjudicated = get_success_data(api.get_claim(claim["id"], org["biller_h"]))
    # A0427 base 41000 + 12*800 mileage 9600 = 50600
    assert adjudicated["allowed_amount_cents"] == 50600


# ---------------------------------------------------------------------------
# corner / calculations / medicaid_factor_allowed_derivation_rural
# ---------------------------------------------------------------------------

def test_medicaid_factor_allowed_derivation_rural(api):
    """PRD §3.7: "for a `MEDICAID` plan it is the baseline multiplied by 0.80 and
    rounded half up".
    PRD §3.7: "the mileage component (computed at 800 cents per loaded mile, with the
    same first-17-mile rural bonus factor of 1.5 applied when the pickup is rural)."

    Design: Corner/calculations/medicaid_factor_allowed_derivation_rural
    """
    org = setup_agency_org(state_code="MT")
    mcaid = create_plan(org, "MEDICAID", name="Medicaid", allows_balance_billing=False)
    pat = create_patient_with_coverages(org, [{"payer_plan_id": mcaid["id"], "policy_rank": 1}])
    t = setup_documentation_complete(org, pat["id"], "MC1", "BLS",
                                     origin_modifier="R", destination_modifier="H",
                                     loaded_miles=20.0, is_rural_pickup=True, emergency_indicator=False)
    claim = submit_primary_claim(org, t["id"], mcaid["id"])
    get_success_data(api.create_remittance(
        claim["id"], F.create_remittance_payload("PAID", 30000), org["biller_h"]))
    adjudicated = get_success_data(api.get_claim(claim["id"], org["biller_h"]))
    # baseline A0428 23000 + rural mileage (round(17*800*1.5)=20400 + round(3*800)=2400) = 45800
    # 45800 * 0.80 = 36640
    assert adjudicated["allowed_amount_cents"] == 36640
    transport = get_success_data(api.get_transport(t["id"], org["biller_h"]))
    assert transport["total_billed_cents"] == 94875


# ---------------------------------------------------------------------------
# non_linear_state_machine / claim_cyclic_denied_appeal_resubmit_loop
# (queue A, 2 tests)
# ---------------------------------------------------------------------------

def _denied_primary(org, run_number):
    """Drive a primary claim to DENIED while keeping it appealable.

    PRD §3.8 closes a settled DENIED claim only when "no further coverage entry at
    the next `policy_rank`" exists; with a downstream rank-2 coverage present the
    payer sequence is NOT yet exhausted, so the DENIED primary stays DENIED and the
    denial-appeal-resubmit loop (PRD §3.8) is reachable.
    """
    med = create_medicare_plan(org)
    mcaid = create_plan(org, "MEDICAID", name="Medicaid", allows_balance_billing=False)
    pat = create_patient_with_coverages(org, [
        {"payer_plan_id": med["id"], "policy_rank": 1},
        {"payer_plan_id": mcaid["id"], "policy_rank": 2},
    ])
    t = setup_documentation_complete(org, pat["id"], run_number, "ALS1",
                                     loaded_miles=12.0, emergency_indicator=True)
    claim = submit_primary_claim(org, t["id"], med["id"])
    post_remittance(org, claim["id"], "DENIED", 0, denial_reason="NOT_MEDICALLY_NECESSARY")
    return t, claim


def test_claim_cycles_back_to_submitted_after_appeal_resubmit(api):
    """PRD §3.8: "A `Biller` appeals a denied claim, advancing its status from
    `DENIED` to `APPEALED`".
    PRD §3.8: "An appealed claim can then be resubmitted, advancing its status from
    `APPEALED` back to `SUBMITTED` and resetting its `allowed_amount_cents` and
    `paid_amount_cents` to zero".

    Design: Difficulty/non_linear_state_machine/claim_cyclic_denied_appeal_resubmit_loop
    """
    org = setup_agency_org()
    t, claim = _denied_primary(org, "CYC1")
    get_success_data(api.appeal_claim(claim["id"], org["biller_h"]))
    resubmitted = get_success_data(api.resubmit_claim(claim["id"], org["biller_h"]))
    assert resubmitted["status"] == "SUBMITTED"


def test_resubmit_resets_allowed_and_paid_to_zero(api):
    """PRD §3.8: "advancing its status from `APPEALED` back to `SUBMITTED` and
    resetting its `allowed_amount_cents` and `paid_amount_cents` to zero".

    Design: Difficulty/non_linear_state_machine/claim_cyclic_denied_appeal_resubmit_loop
    """
    org = setup_agency_org()
    t, claim = _denied_primary(org, "CYC2")
    get_success_data(api.appeal_claim(claim["id"], org["biller_h"]))
    resubmitted = get_success_data(api.resubmit_claim(claim["id"], org["biller_h"]))
    assert resubmitted["allowed_amount_cents"] == 0
    assert resubmitted["paid_amount_cents"] == 0


# ---------------------------------------------------------------------------
# corner / state_machines / appeal_a_paid_claim_returns_invalid_claim_state
# ---------------------------------------------------------------------------

def test_appeal_a_paid_claim_rejected(api):
    """PRD §3.8: "the appeal is admitted only when the claim is `DENIED` and a
    resolvable denial reason exists (the latest `DENIED` remittance line is present),
    and is otherwise rejected with `ERR_INVALID_CLAIM_STATE` (HTTP 409)."

    Design: Corner/state_machines/appeal_a_paid_claim_returns_invalid_claim_state
    """
    org = setup_agency_org()
    med = create_medicare_plan(org)
    pat = create_patient_with_coverages(org, [{"payer_plan_id": med["id"], "policy_rank": 1}])
    t = setup_documentation_complete(org, pat["id"], "AP1", "ALS1",
                                     loaded_miles=12.0, emergency_indicator=True)
    claim = submit_primary_claim(org, t["id"], med["id"])
    get_success_data(api.create_remittance(
        claim["id"], F.create_remittance_payload("PAID", 40480), org["biller_h"]))  # -> PAID
    resp = api.appeal_claim(claim["id"], org["biller_h"])
    validate_error(resp, ApiErrorId.ERR_INVALID_CLAIM_STATE.value)


# ---------------------------------------------------------------------------
# corner / validations  (remittance gates)
# ---------------------------------------------------------------------------

def test_denial_reason_required_on_denied_remittance(api):
    """PRD §3.7: "A `DENIED` remittance that omits the `denial_reason`, or a `PAID`
    or `PARTIAL` remittance that carries one, is rejected with
    `ERR_DENIAL_REASON_REQUIRED` (HTTP 422)."

    Design: Corner/validations/denial_reason_required_on_denied_remittance
    """
    org = setup_agency_org()
    med = create_medicare_plan(org)
    pat = create_patient_with_coverages(org, [{"payer_plan_id": med["id"], "policy_rank": 1}])
    t = setup_documentation_complete(org, pat["id"], "DR1", "ALS1",
                                     loaded_miles=12.0, emergency_indicator=True)
    claim = submit_primary_claim(org, t["id"], med["id"])
    resp = api.create_remittance(claim["id"], F.create_remittance_payload("DENIED", 0), org["biller_h"])
    validate_error(resp, ApiErrorId.ERR_DENIAL_REASON_REQUIRED.value)


def test_paid_exceeds_allowed_rejected(api):
    """PRD §3.7: "The paid amount may never exceed what the payer allows: a remittance
    whose `paid_cents` exceeds the claim's derived or reported allowed amount is
    rejected with `ERR_PAID_EXCEEDS_ALLOWED` (HTTP 422)."

    Design: Corner/validations/paid_exceeds_allowed_rejected
    """
    org = setup_agency_org()
    med = create_medicare_plan(org)
    pat = create_patient_with_coverages(org, [{"payer_plan_id": med["id"], "policy_rank": 1}])
    t = setup_documentation_complete(org, pat["id"], "PE1", "ALS1",
                                     loaded_miles=12.0, emergency_indicator=True)
    claim = submit_primary_claim(org, t["id"], med["id"])
    # derived Medicare allowed is 50600; paid 60000 exceeds it
    resp = api.create_remittance(claim["id"], F.create_remittance_payload("PAID", 60000), org["biller_h"])
    validate_error(resp, ApiErrorId.ERR_PAID_EXCEEDS_ALLOWED.value)
