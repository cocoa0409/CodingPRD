"""Ledger reconciliation cascades, patient responsibility, payments, and the
charity / No-Surprises / discretionary write-offs.

Translates difficulty queue (transitive_cascade, dual_variant_calc patient
liability, combinatorial_formula charity, boundary_precision_check charity,
compensating_invariant) and corner queue (validations fiscal gates,
state_machines void terminal lockdown).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    setup_agency_org,
    create_medicare_plan,
    create_plan,
    create_patient_with_coverages,
    setup_documentation_complete,
    import_and_code,
    submit_primary_claim,
    submit_secondary_claim,
    post_remittance,
    setup_medicare_patient_balance,
    transport_version,
)
from test_helpers import factories as F


# ---------------------------------------------------------------------------
# transitive_cascade / remittance_to_claim_to_transport_to_billing_status_depth3
# (queue A, 2 tests)
# ---------------------------------------------------------------------------

def test_remittance_cascades_to_patient_balance(api):
    """PRD §3.7: "the system reconciles the transport ledger and advances the billing
    dimension if the payer sequence is now exhausted."
    PRD §3.8: "As part of leaving `BILLING_IN_PROGRESS`, a settled claim whose status
    is `PAID` automatically transitions to the terminal `CLOSED`".
    PRD §3.8: "When `patient_responsibility_cents` is greater than zero after the
    final payer adjudicates, the transport transitions from `BILLED` to
    `PATIENT_BALANCE`."

    Design: Difficulty/transitive_cascade/remittance_to_claim_to_transport_to_billing_status_depth3
    """
    org = setup_agency_org()
    med = create_medicare_plan(org)
    pat = create_patient_with_coverages(org, [{"payer_plan_id": med["id"], "policy_rank": 1}])
    t = setup_documentation_complete(org, pat["id"], "CASC1", "ALS1",
                                     loaded_miles=12.0, emergency_indicator=True)
    claim = submit_primary_claim(org, t["id"], med["id"])
    post_remittance(org, claim["id"], "PAID", 40480)
    adjudicated = get_success_data(api.get_claim(claim["id"], org["biller_h"]))
    transport = get_success_data(api.get_transport(t["id"], org["biller_h"]))
    # single Medicare coverage -> sequence exhausted; leaving BILLING_IN_PROGRESS
    # transitions the settled PAID claim to terminal CLOSED (PRD §3.8).
    assert adjudicated["status"] == "CLOSED"
    assert transport["billing_status"] == "PATIENT_BALANCE"


def test_remittance_cascade_recomputes_ledger_totals(api):
    """PRD §3.7: "For a primary claim (`sequence_rank` 1) on a `MEDICARE` or
    `MEDICAID` plan, the full gap is automatically written off: the contractual
    adjustment is the claim's `billed_amount_cents` minus its `allowed_amount_cents`,
    floored at zero."
    PRD §3.9: "then `total_paid_cents` as the sum of all payment `amount_cents` (both
    payer and patient)".

    Design: Difficulty/transitive_cascade/remittance_to_claim_to_transport_to_billing_status_depth3
    """
    org = setup_agency_org()
    med = create_medicare_plan(org)
    pat = create_patient_with_coverages(org, [{"payer_plan_id": med["id"], "policy_rank": 1}])
    t = setup_documentation_complete(org, pat["id"], "CASC2", "ALS1",
                                     loaded_miles=12.0, emergency_indicator=True)
    claim = submit_primary_claim(org, t["id"], med["id"])
    post_remittance(org, claim["id"], "PAID", 40480)
    transport = get_success_data(api.get_transport(t["id"], org["biller_h"]))
    # billed 101000, allowed 50600, contractual 50400, paid 40480, patient_resp 10120
    assert transport["total_paid_cents"] == 40480
    assert transport["total_writeoff_cents"] == 50400
    assert transport["patient_responsibility_cents"] == 10120


# ---------------------------------------------------------------------------
# transitive_cascade / patient_payment_to_ledger_to_closed_depth2  (queue A, 2 tests)
# ---------------------------------------------------------------------------

def test_patient_payment_drives_transport_to_closed(api):
    """PRD §3.8: "A transport in `PATIENT_BALANCE` later transitions to `CLOSED`
    automatically once its remaining patient balance reaches zero through a patient
    payment, a charity write-off, a balance-billing cap, or an uncollectible
    write-off".

    Design: Difficulty/transitive_cascade/patient_payment_to_ledger_to_closed_depth2
    """
    org = setup_agency_org()
    med = create_medicare_plan(org)
    pat = create_patient_with_coverages(org, [{"payer_plan_id": med["id"], "policy_rank": 1}])
    res = setup_medicare_patient_balance(org, pat["id"], "PAY1", med["id"])
    tid = res["transport"]["id"]
    get_success_data(api.create_payment(tid, F.create_payment_payload("PATIENT", 10120), org["biller_h"]))
    transport = get_success_data(api.get_transport(tid, org["biller_h"]))
    assert transport["patient_responsibility_cents"] == 0
    assert transport["billing_status"] == "CLOSED"


def test_patient_payment_reconciles_total_paid(api):
    """PRD §3.9: "then `total_paid_cents` as the sum of all payment `amount_cents`
    (both payer and patient)".

    Design: Difficulty/transitive_cascade/patient_payment_to_ledger_to_closed_depth2
    """
    org = setup_agency_org()
    med = create_medicare_plan(org)
    pat = create_patient_with_coverages(org, [{"payer_plan_id": med["id"], "policy_rank": 1}])
    res = setup_medicare_patient_balance(org, pat["id"], "PAY2", med["id"])
    tid = res["transport"]["id"]
    get_success_data(api.create_payment(tid, F.create_payment_payload("PATIENT", 10120), org["biller_h"]))
    transport = get_success_data(api.get_transport(tid, org["biller_h"]))
    # payer 40480 + patient 10120 = 50600
    assert transport["total_paid_cents"] == 50600


# ---------------------------------------------------------------------------
# dual_variant_calc / patient_responsibility_standard_vs_no_surprises  (queue A, 2 tests)
# ---------------------------------------------------------------------------

def _commercial_paid_transport(org, run_number):
    """Commercial primary (qpa 1.2, allows_balance_billing true) ALS1-emergency 12mi,
    PAID 48576 (allowed 60720)."""
    comm = create_plan(org, "COMMERCIAL", name="Commercial PPO",
                       qpa_multiplier=1.2, allows_balance_billing=True)
    pat = create_patient_with_coverages(org, [{"payer_plan_id": comm["id"], "policy_rank": 1}])
    t = setup_documentation_complete(org, pat["id"], run_number, "ALS1",
                                     loaded_miles=12.0, emergency_indicator=True)
    claim = submit_primary_claim(org, t["id"], comm["id"])
    post_remittance(org, claim["id"], "PAID", 48576)
    return t, comm, claim


def test_patient_responsibility_standard_balance_bill(api):
    """PRD §3.10: "For a `COMMERCIAL` or `AUTO` primary that is not protected —
    `allows_balance_billing` true and the agency not in a No Surprises state — no
    contractual write-off is recorded and no cap is permitted, so the patient owes the
    full gap (billed minus payer-paid): the standard balance-bill outcome."

    Design: Difficulty/dual_variant_calc/patient_responsibility_standard_vs_no_surprises
    """
    org = setup_agency_org(state_code="TX", base_state_is_no_surprises=False)
    t, comm, claim = _commercial_paid_transport(org, "S1")
    transport = get_success_data(api.get_transport(t["id"], org["biller_h"]))
    # billed 101000 - payer_paid 48576 - 0 writeoff = 52424
    assert transport["patient_responsibility_cents"] == 52424


def test_patient_responsibility_no_surprises_cap(api):
    """PRD §3.10: "for a protected commercial or auto patient whose primary remittance
    recorded no contractual write-off, the cap adjustment writes the gap down to the
    cost share."
    PRD §3.10: "the write-off is the transport's current `patient_responsibility_cents`
    minus that cost share, floored at zero."

    Design: Difficulty/dual_variant_calc/patient_responsibility_standard_vs_no_surprises
    """
    org = setup_agency_org(state_code="CA", base_state_is_no_surprises=True)
    t, comm, claim = _commercial_paid_transport(org, "N1")
    adj = get_success_data(api.create_adjustment(
        t["id"], F.create_adjustment_payload("BALANCE_BILLING_CAP"), org["compliance_h"]))
    transport = get_success_data(api.get_transport(t["id"], org["biller_h"]))
    # cost_share = allowed 60720 - payer_paid 48576 = 12144; cap = 52424 - 12144 = 40280
    assert adj["amount_cents"] == 40280
    assert transport["patient_responsibility_cents"] == 12144


# ---------------------------------------------------------------------------
# combinatorial_formula / charity_fpl_threshold_three_input_branch  (queue A, 2 tests)
# ---------------------------------------------------------------------------

def test_charity_writeoff_full_balance_when_qualified(api):
    """PRD §3.10: "The patient's income as a percent of that FPL base is the income
    multiplied by 100, divided by the FPL base, and rounded half up to a whole
    percent. When that whole-percent figure is at or below the agency's
    `charity_fpl_threshold_pct`, the patient qualifies and the write-off equals the
    transport's current `patient_responsibility_cents`".

    Design: Difficulty/combinatorial_formula/charity_fpl_threshold_three_input_branch
    """
    org = setup_agency_org(charity_fpl_threshold_pct=200)
    med = create_medicare_plan(org)
    pat = create_patient_with_coverages(
        org, [{"payer_plan_id": med["id"], "policy_rank": 1}],
        household_size=2, annual_household_income_cents=4080000)
    res = setup_medicare_patient_balance(org, pat["id"], "CH1", med["id"])
    tid = res["transport"]["id"]
    adj = get_success_data(api.create_adjustment(
        tid, F.create_adjustment_payload("CHARITY"), org["compliance_h"]))
    # fpl_base 1508000 + 532000 = 2040000; pct = round(4080000*100/2040000) = 200 <= 200 -> qualifies
    assert adj["amount_cents"] == 10120


def test_charity_writeoff_closes_transport(api):
    """PRD §3.10: "Every adjustment posting reconciles the ledger, recomputes patient
    responsibility, and may advance the transport to `CLOSED` when the balance reaches
    zero."

    Design: Difficulty/combinatorial_formula/charity_fpl_threshold_three_input_branch
    """
    org = setup_agency_org(charity_fpl_threshold_pct=200)
    med = create_medicare_plan(org)
    pat = create_patient_with_coverages(
        org, [{"payer_plan_id": med["id"], "policy_rank": 1}],
        household_size=2, annual_household_income_cents=4080000)
    res = setup_medicare_patient_balance(org, pat["id"], "CH2", med["id"])
    tid = res["transport"]["id"]
    get_success_data(api.create_adjustment(tid, F.create_adjustment_payload("CHARITY"), org["compliance_h"]))
    transport = get_success_data(api.get_transport(tid, org["biller_h"]))
    assert transport["patient_responsibility_cents"] == 0
    assert transport["billing_status"] == "CLOSED"


# ---------------------------------------------------------------------------
# boundary_precision_check / charity_fpl_at_threshold_qualifies_one_cent_over_rejected
# (queue A, 2 tests)
# ---------------------------------------------------------------------------

def test_charity_at_exact_threshold_qualifies(api):
    """PRD §3.10: "When that whole-percent figure is at or below the agency's
    `charity_fpl_threshold_pct`, the patient qualifies and the write-off equals the
    transport's current `patient_responsibility_cents`".

    Design: Difficulty/boundary_precision_check/charity_fpl_at_threshold_qualifies_one_cent_over_rejected
    """
    org = setup_agency_org(charity_fpl_threshold_pct=200)
    med = create_medicare_plan(org)
    pat = create_patient_with_coverages(
        org, [{"payer_plan_id": med["id"], "policy_rank": 1}],
        household_size=2, annual_household_income_cents=4080000)  # exactly 200%
    res = setup_medicare_patient_balance(org, pat["id"], "FPL0", med["id"])
    tid = res["transport"]["id"]
    adj = get_success_data(api.create_adjustment(
        tid, F.create_adjustment_payload("CHARITY"), org["compliance_h"]))
    assert adj["amount_cents"] == 10120


def test_charity_one_percent_over_threshold_rejected(api):
    """PRD §3.10: "when it exceeds the threshold, the request is rejected with
    `ERR_CHARITY_NOT_QUALIFIED` (HTTP 409). The rounding to a whole percent occurs
    before the comparison."

    Design: Difficulty/boundary_precision_check/charity_fpl_at_threshold_qualifies_one_cent_over_rejected
    """
    org = setup_agency_org(charity_fpl_threshold_pct=200)
    med = create_medicare_plan(org)
    pat = create_patient_with_coverages(
        org, [{"payer_plan_id": med["id"], "policy_rank": 1}],
        household_size=2, annual_household_income_cents=4100000)  # 201%
    res = setup_medicare_patient_balance(org, pat["id"], "FPL1", med["id"])
    tid = res["transport"]["id"]
    resp = api.create_adjustment(tid, F.create_adjustment_payload("CHARITY"), org["compliance_h"])
    validate_error(resp, ApiErrorId.ERR_CHARITY_NOT_QUALIFIED.value)


# ---------------------------------------------------------------------------
# compensating_invariant / void_transport_drains_total_billed_receivable_to_zero
# (queue A, 2 tests)
# ---------------------------------------------------------------------------

def test_void_drains_total_billed_to_zero(api):
    """PRD §3.5: "Voiding deletes the synthesized charge rows and resets
    `total_billed_cents` to zero."
    PRD §3.5: "advancing `billing_status` from `UNBILLED` to the terminal `VOID`."

    Design: Difficulty/compensating_invariant/void_transport_drains_total_billed_receivable_to_zero
    """
    org = setup_agency_org(with_compliance=False)
    pat = create_patient_with_coverages(org, [])
    t = import_and_code(org, pat["id"], "VOID1", "ALS1", loaded_miles=12.0, emergency_indicator=True)
    assert t["total_billed_cents"] == 101000
    voided = get_success_data(api.void_transport(t["id"], org["biller_h"]))
    assert voided["billing_status"] == "VOID"
    assert voided["total_billed_cents"] == 0


def test_void_deletes_synthesized_charges(api):
    """PRD §3.5: "Voiding deletes the synthesized charge rows and resets
    `total_billed_cents` to zero."

    Design: Difficulty/compensating_invariant/void_transport_drains_total_billed_receivable_to_zero
    """
    org = setup_agency_org(with_compliance=False)
    pat = create_patient_with_coverages(org, [])
    t = import_and_code(org, pat["id"], "VOID2", "ALS1", loaded_miles=12.0, emergency_indicator=True)
    get_success_data(api.void_transport(t["id"], org["biller_h"]))
    charges, meta = validate_paginated(api.list_transport_charges(t["id"], org["biller_h"]))
    assert meta["total_count"] == 0


# ---------------------------------------------------------------------------
# compensating_invariant / payer_payments_conserve_against_claim_paid_amounts
# (queue A, 2 tests) — patient_responsibility literal is internally inconsistent
# with the instance payload (emergency BLS billed 109875, not 94875), so that
# specific assertion is omitted; the conserved-cash invariant is fully asserted.
# ---------------------------------------------------------------------------

def _commercial_then_medicaid_cob(org, run_number):
    comm = create_plan(org, "COMMERCIAL", name="Commercial",
                       qpa_multiplier=1.0, allows_balance_billing=True)
    mcaid = create_plan(org, "MEDICAID", name="Medicaid", allows_balance_billing=False)
    pat = create_patient_with_coverages(org, [
        {"payer_plan_id": comm["id"], "policy_rank": 1},
        {"payer_plan_id": mcaid["id"], "policy_rank": 2},
    ])
    t = setup_documentation_complete(org, pat["id"], run_number, "BLS",
                                     origin_modifier="R", destination_modifier="H",
                                     loaded_miles=20.0, is_rural_pickup=True, emergency_indicator=True)
    claim1 = submit_primary_claim(org, t["id"], comm["id"])
    post_remittance(org, claim1["id"], "PAID", 30000)
    claim2 = submit_secondary_claim(org, t["id"], mcaid["id"], claim1["id"])
    post_remittance(org, claim2["id"], "PAID", 20000)
    return t, claim1, claim2


def test_cob_claim_paid_amounts_recorded(api):
    """PRD §3.7: "Posting a `PAID` or `PARTIAL` remittance sets the claim's
    `allowed_amount_cents` to the computed allowed amount and its `paid_amount_cents`
    to the remittance's `paid_cents`".

    Design: Difficulty/compensating_invariant/payer_payments_conserve_against_claim_paid_amounts
    """
    org = setup_agency_org(base_state_is_no_surprises=False)
    t, claim1, claim2 = _commercial_then_medicaid_cob(org, "CASH1")
    c1 = get_success_data(api.get_claim(claim1["id"], org["biller_h"]))
    c2 = get_success_data(api.get_claim(claim2["id"], org["biller_h"]))
    assert c1["paid_amount_cents"] == 30000
    assert c2["paid_amount_cents"] == 20000


def test_cob_total_paid_conserves_payer_cash(api):
    """PRD §3.9: "then `total_paid_cents` as the sum of all payment `amount_cents`
    (both payer and patient)".
    PRD §3.7: "creates a payer `Payment` (a `Payment` with `source` `PAYER` and this
    claim's `claim_id`) for the paid amount".

    Design: Difficulty/compensating_invariant/payer_payments_conserve_against_claim_paid_amounts
    """
    org = setup_agency_org(base_state_is_no_surprises=False)
    t, claim1, claim2 = _commercial_then_medicaid_cob(org, "CASH2")
    transport = get_success_data(api.get_transport(t["id"], org["biller_h"]))
    assert transport["total_paid_cents"] == 50000  # 30000 + 20000


# ---------------------------------------------------------------------------
# corner / state_machines / void_after_void_returns_invalid_billing_state
# ---------------------------------------------------------------------------

def test_void_after_void_rejected(api):
    """PRD §3.5: "Voiding is admitted only while the transport's `billing_status` is
    `UNBILLED`; once any claim exists the transport's billing status no longer admits
    the void transition and the attempt is rejected with `ERR_INVALID_BILLING_STATE`
    (HTTP 409)."

    Design: Corner/state_machines/void_after_void_returns_invalid_billing_state
    """
    org = setup_agency_org(with_compliance=False)
    pat = create_patient_with_coverages(org, [])
    t = import_and_code(org, pat["id"], "VV1", "ALS1", loaded_miles=10.0, emergency_indicator=True)
    get_success_data(api.void_transport(t["id"], org["biller_h"]))
    resp = api.void_transport(t["id"], org["biller_h"])
    validate_error(resp, ApiErrorId.ERR_INVALID_BILLING_STATE.value)


# ---------------------------------------------------------------------------
# corner / validations  (fiscal write-off / payment gates)
# ---------------------------------------------------------------------------

def test_patient_payment_exceeds_balance_rejected(api):
    """PRD §3.9: "A patient payment may not overpay the patient's current balance: an
    `amount_cents` for a `PATIENT`-source payment that exceeds the transport's current
    `patient_responsibility_cents` is rejected with `ERR_PAYMENT_EXCEEDS_BALANCE`
    (HTTP 422)."

    Design: Corner/validations/patient_payment_exceeds_balance_rejected
    """
    org = setup_agency_org()
    med = create_medicare_plan(org)
    pat = create_patient_with_coverages(org, [{"payer_plan_id": med["id"], "policy_rank": 1}])
    res = setup_medicare_patient_balance(org, pat["id"], "PB1", med["id"])
    tid = res["transport"]["id"]
    resp = api.create_payment(tid, F.create_payment_payload("PATIENT", 20000), org["biller_h"])
    validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value)


def test_writeoff_exceeds_balance_rejected(api):
    """PRD §3.10: "for both, the applied `amount_cents` is the `requested_amount_cents`,
    which must not exceed the transport's current `patient_responsibility_cents`, or
    the request is rejected with `ERR_WRITEOFF_EXCEEDS_BALANCE` (HTTP 422)."

    Design: Corner/validations/writeoff_exceeds_balance_rejected
    """
    org = setup_agency_org()
    med = create_medicare_plan(org)
    pat = create_patient_with_coverages(org, [{"payer_plan_id": med["id"], "policy_rank": 1}])
    res = setup_medicare_patient_balance(org, pat["id"], "WE1", med["id"])
    tid = res["transport"]["id"]
    resp = api.create_adjustment(
        tid, F.create_adjustment_payload("UNCOLLECTIBLE", requested_amount_cents=20000),
        org["compliance_h"])
    validate_error(resp, ApiErrorId.ERR_WRITEOFF_EXCEEDS_BALANCE.value)


def test_charity_income_required_when_null(api):
    """PRD §3.10: "The patient's annual household income must be provided; a charity
    request when `annual_household_income_cents` is null is rejected with
    `ERR_CHARITY_INCOME_REQUIRED` (HTTP 422)."

    Design: Corner/validations/charity_income_required_when_null
    """
    org = setup_agency_org(charity_fpl_threshold_pct=200)
    med = create_medicare_plan(org)
    pat = create_patient_with_coverages(org, [{"payer_plan_id": med["id"], "policy_rank": 1}])  # income null
    res = setup_medicare_patient_balance(org, pat["id"], "CI1", med["id"])
    tid = res["transport"]["id"]
    resp = api.create_adjustment(tid, F.create_adjustment_payload("CHARITY"), org["compliance_h"])
    validate_error(resp, ApiErrorId.ERR_CHARITY_INCOME_REQUIRED.value)


def test_balance_billing_cap_not_protected_rejected(api):
    """PRD §3.10: "A balance-billing cap requested when the primary payer is
    `COMMERCIAL` or `AUTO` but balance billing is not barred — neither the plan flag
    is false nor is the agency in a No Surprises state — is rejected with
    `ERR_BALANCE_BILLING_NOT_PROTECTED` (HTTP 409)."

    Design: Corner/validations/balance_billing_cap_not_protected_rejected
    """
    org = setup_agency_org(base_state_is_no_surprises=False)
    t, comm, claim = _commercial_paid_transport(org, "BP1")
    resp = api.create_adjustment(
        t["id"], F.create_adjustment_payload("BALANCE_BILLING_CAP"), org["compliance_h"])
    validate_error(resp, ApiErrorId.ERR_BALANCE_BILLING_NOT_PROTECTED.value)
