"""Claim submission, the payer sequence, cross-dimension billing guards, OCC, and
the documentation/billing state precedence conflicts.

Translates difficulty queue (cross_entity_state_dependency,
priority_pair_validation_conflict, cross_cutting OCC) and corner queue
(state_machines valid transition, validations referential).
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
    import_and_code,
    submit_primary_claim,
    post_remittance,
    transport_version,
)
from test_helpers import factories as F


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / claim_creation_blocked_until_transport_documentation_complete
# (queue A, 2 tests)
# ---------------------------------------------------------------------------

def test_claim_blocked_before_documentation_complete(api):
    """PRD §3.6: "First, the transport must have reached `DOCUMENTATION_COMPLETE`; a
    claim attempted before then is rejected with `ERR_DOCUMENTATION_INCOMPLETE`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/claim_creation_blocked_until_transport_documentation_complete
    """
    org = setup_agency_org()
    med = create_medicare_plan(org)
    pat = create_patient_with_coverages(org, [{"payer_plan_id": med["id"], "policy_rank": 1}])
    t = import_and_code(org, pat["id"], "X1", "ALS1", loaded_miles=12.0, emergency_indicator=True)
    get_success_data(api.attest_necessity(t["id"], org["coder_h"]))  # NECESSITY_REVIEW, not complete
    v = transport_version(org, t["id"])
    resp = api.create_claim(t["id"], F.create_claim_payload(med["id"], v), org["biller_h"])
    validate_error(resp, ApiErrorId.ERR_DOCUMENTATION_INCOMPLETE.value)


def test_claim_blocked_while_still_coded(api):
    """PRD §3.6: "First, the transport must have reached `DOCUMENTATION_COMPLETE`; a
    claim attempted before then is rejected with `ERR_DOCUMENTATION_INCOMPLETE`
    (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/claim_creation_blocked_until_transport_documentation_complete
    """
    org = setup_agency_org()
    med = create_medicare_plan(org)
    pat = create_patient_with_coverages(org, [{"payer_plan_id": med["id"], "policy_rank": 1}])
    t = import_and_code(org, pat["id"], "X2", "ALS1", loaded_miles=12.0, emergency_indicator=True)
    v = transport_version(org, t["id"])  # documentation_status == CODED
    resp = api.create_claim(t["id"], F.create_claim_payload(med["id"], v), org["biller_h"])
    validate_error(resp, ApiErrorId.ERR_DOCUMENTATION_INCOMPLETE.value)


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / claim_creation_blocked_by_inactive_payer_plan
# (queue A, 2 tests)
# ---------------------------------------------------------------------------

def test_claim_blocked_by_inactive_payer_plan(api):
    """PRD §3.6: "The named payer plan must be `ACTIVE`, or the request is rejected
    with `ERR_PAYER_PLAN_INACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/claim_creation_blocked_by_inactive_payer_plan
    """
    org = setup_agency_org()
    med = create_medicare_plan(org)
    pat = create_patient_with_coverages(org, [{"payer_plan_id": med["id"], "policy_rank": 1}])
    t = setup_documentation_complete(org, pat["id"], "Y1", "ALS1",
                                     loaded_miles=12.0, emergency_indicator=True)
    get_success_data(api.deactivate_payer_plan(med["id"], org["admin_h"]))
    v = transport_version(org, t["id"])
    resp = api.create_claim(t["id"], F.create_claim_payload(med["id"], v), org["biller_h"])
    validate_error(resp, ApiErrorId.ERR_PAYER_PLAN_INACTIVE.value)


def test_active_payer_plan_claim_succeeds_after_deactivating_another(api):
    """PRD §2.9: "A `PayerPlan` has a `status` of `ACTIVE` or `INACTIVE`; an
    `INACTIVE` plan cannot be named on a new claim."
    PRD §3.6: "The named payer plan must be `ACTIVE`, or the request is rejected
    with `ERR_PAYER_PLAN_INACTIVE` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/claim_creation_blocked_by_inactive_payer_plan
    """
    org = setup_agency_org()
    active_med = create_medicare_plan(org, name="Active Medicare")
    other = create_medicare_plan(org, name="Other Medicare")
    get_success_data(api.deactivate_payer_plan(other["id"], org["admin_h"]))  # unrelated deactivation
    pat = create_patient_with_coverages(org, [{"payer_plan_id": active_med["id"], "policy_rank": 1}])
    t = setup_documentation_complete(org, pat["id"], "Y2", "ALS1",
                                     loaded_miles=12.0, emergency_indicator=True)
    v = transport_version(org, t["id"])
    resp = api.create_claim(t["id"], F.create_claim_payload(active_med["id"], v), org["biller_h"])
    claim = validate_success(resp, expected_status=201)
    assert claim["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / state_beats_business_safety_on_claim_creation
# (queue A, 2 tests) — voiding a BILLING_IN_PROGRESS transport
# ---------------------------------------------------------------------------

def test_void_after_billing_started_rejected_invalid_billing_state(api):
    """PRD §3.5: "Voiding is admitted only while the transport's `billing_status` is
    `UNBILLED`; once any claim exists the transport's billing status no longer admits
    the void transition and the attempt is rejected with `ERR_INVALID_BILLING_STATE`
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_claim_creation
    """
    org = setup_agency_org()
    med = create_medicare_plan(org)
    pat = create_patient_with_coverages(org, [{"payer_plan_id": med["id"], "policy_rank": 1}])
    t = setup_documentation_complete(org, pat["id"], "PC1", "ALS1",
                                     loaded_miles=12.0, emergency_indicator=True)
    submit_primary_claim(org, t["id"], med["id"])  # billing_status -> BILLING_IN_PROGRESS
    resp = api.void_transport(t["id"], org["biller_h"])
    validate_error(resp, ApiErrorId.ERR_INVALID_BILLING_STATE.value)


def test_void_unbilled_transport_succeeds(api):
    """PRD §3.5: "Before any claim exists, a `Biller` may void a transport, advancing
    `billing_status` from `UNBILLED` to the terminal `VOID`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_safety_on_claim_creation
    """
    org = setup_agency_org(with_compliance=False)
    pat = create_patient_with_coverages(org, [])
    t = import_and_code(org, pat["id"], "PC2", "ALS1", loaded_miles=12.0, emergency_indicator=True)
    voided = get_success_data(api.void_transport(t["id"], org["biller_h"]))
    assert voided["billing_status"] == "VOID"


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / business_referential_beats_business_fiscal_on_secondary_claim
# (queue A, 2 tests) — secondary claim with payer not matching coverage rank 2
# ---------------------------------------------------------------------------

def _setup_denied_primary_with_secondary_coverage(org, run_number, secondary_plan_id):
    """Helper: Medicare primary (rank 1), a secondary plan at rank 2; primary DENIED."""
    med = create_medicare_plan(org)
    pat = create_patient_with_coverages(org, [
        {"payer_plan_id": med["id"], "policy_rank": 1},
        {"payer_plan_id": secondary_plan_id, "policy_rank": 2},
    ])
    t = setup_documentation_complete(org, pat["id"], run_number, "ALS1",
                                     loaded_miles=12.0, emergency_indicator=True)
    claim1 = submit_primary_claim(org, t["id"], med["id"])
    post_remittance(org, claim1["id"], "DENIED", 0, denial_reason="NON_COVERED_DESTINATION")
    return t, med, claim1


def test_secondary_claim_payer_mismatch_rejected(api):
    """PRD §3.6: "the named payer must match the patient's coverage entry whose
    `policy_rank` equals the new claim's `sequence_rank`; a mismatch is rejected with
    `ERR_PAYER_SEQUENCE_MISMATCH` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/business_referential_beats_business_fiscal_on_secondary_claim
    """
    org = setup_agency_org()
    mcaid = create_plan(org, "MEDICAID", name="Medicaid", allows_balance_billing=False)
    wrong = create_plan(org, "COMMERCIAL", name="Wrong Commercial",
                        qpa_multiplier=1.2, allows_balance_billing=True)
    t, med, claim1 = _setup_denied_primary_with_secondary_coverage(org, "SEQ1", mcaid["id"])
    v = transport_version(org, t["id"])
    # Patient's rank-2 coverage is Medicaid, but we name the Commercial plan.
    resp = api.create_claim(t["id"], F.create_claim_payload(wrong["id"], v, prior_claim_id=claim1["id"]),
                            org["biller_h"])
    validate_error(resp, ApiErrorId.ERR_PAYER_SEQUENCE_MISMATCH.value)


def test_secondary_claim_matching_payer_accepted(api):
    """PRD §3.6: "the named payer must match the patient's coverage entry whose
    `policy_rank` equals the new claim's `sequence_rank`".
    PRD §3.6: "The system assigns the new claim a `sequence_rank` derived from the
    `prior_claim_id` chain depth — 1 for the primary, 2 for the secondary".

    Design: Difficulty/priority_pair_validation_conflict/business_referential_beats_business_fiscal_on_secondary_claim
    """
    org = setup_agency_org()
    mcaid = create_plan(org, "MEDICAID", name="Medicaid", allows_balance_billing=False)
    t, med, claim1 = _setup_denied_primary_with_secondary_coverage(org, "SEQ2", mcaid["id"])
    v = transport_version(org, t["id"])
    resp = api.create_claim(t["id"], F.create_claim_payload(mcaid["id"], v, prior_claim_id=claim1["id"]),
                            org["biller_h"])
    claim2 = validate_success(resp, expected_status=201)
    assert claim2["sequence_rank"] == 2
    assert claim2["status"] == "SUBMITTED"


# ---------------------------------------------------------------------------
# cross_cutting / occ_stale_transport_version_on_claim_create  (queue B, 1 test)
# ---------------------------------------------------------------------------

def test_occ_stale_transport_version_on_claim_create(api):
    """PRD §2.7: "If `expected_transport_version` does not equal the transport's
    current `version`, the request is rejected with `ERR_STALE_TRANSPORT_VERSION`
    (HTTP 412)."
    PRD §3.6: "Submitting the primary claim sets `billing_status` to
    `BILLING_IN_PROGRESS` and increments the transport's `version` by one."

    Design: Corner/cross_cutting/occ_stale_transport_version_on_claim_create
    """
    org = setup_agency_org()
    med = create_medicare_plan(org)
    pat = create_patient_with_coverages(org, [{"payer_plan_id": med["id"], "policy_rank": 1}])
    t = setup_documentation_complete(org, pat["id"], "OCC1", "ALS1",
                                     loaded_miles=12.0, emergency_indicator=True)
    stale_v = transport_version(org, t["id"])  # observed before first claim
    get_success_data(api.create_claim(t["id"], F.create_claim_payload(med["id"], stale_v), org["biller_h"]))
    # second claim still carries the pre-claim version -> stale
    resp = api.create_claim(t["id"], F.create_claim_payload(med["id"], stale_v), org["biller_h"])
    validate_error(resp, ApiErrorId.ERR_STALE_TRANSPORT_VERSION.value)


# ---------------------------------------------------------------------------
# corner / state_machines / claim_creation_from_completed_documentation_succeeds
# ---------------------------------------------------------------------------

def test_primary_claim_creation_succeeds_from_complete_documentation(api):
    """PRD §3.6: "Billing begins when a `Biller` submits the first, primary claim
    against a transport, which advances `billing_status` from `UNBILLED` to
    `BILLING_IN_PROGRESS`."
    PRD §3.6: "records its `transport_id`, sets its `billed_amount_cents` equal to
    the transport's `total_billed_cents` at submission".

    Design: Corner/state_machines/claim_creation_from_completed_documentation_succeeds
    """
    org = setup_agency_org()
    med = create_medicare_plan(org)
    pat = create_patient_with_coverages(org, [{"payer_plan_id": med["id"], "policy_rank": 1}])
    t = setup_documentation_complete(org, pat["id"], "OK1", "ALS1",
                                     loaded_miles=12.0, emergency_indicator=True)
    v = transport_version(org, t["id"])
    claim = validate_success(api.create_claim(t["id"], F.create_claim_payload(med["id"], v),
                                              org["biller_h"]), expected_status=201)
    assert claim["sequence_rank"] == 1
    assert claim["status"] == "SUBMITTED"
    assert claim["billed_amount_cents"] == 101000  # A0427 80000 + 12*1750 21000
    transport = get_success_data(api.get_transport(t["id"], org["biller_h"]))
    assert transport["billing_status"] == "BILLING_IN_PROGRESS"


# ---------------------------------------------------------------------------
# corner / validations / prior_claim_not_adjudicated_blocks_secondary
# ---------------------------------------------------------------------------

def test_prior_claim_not_adjudicated_blocks_secondary(api):
    """PRD §3.6: "The named `prior_claim_id` must resolve to a claim of the same
    transport whose status is `PAID` or `DENIED`; an unadjudicated prior claim is
    rejected with `ERR_PRIOR_CLAIM_NOT_ADJUDICATED` (HTTP 409)."

    Design: Corner/validations/prior_claim_not_adjudicated_blocks_secondary
    """
    org = setup_agency_org()
    med = create_medicare_plan(org)
    mcaid = create_plan(org, "MEDICAID", name="Medicaid", allows_balance_billing=False)
    pat = create_patient_with_coverages(org, [
        {"payer_plan_id": med["id"], "policy_rank": 1},
        {"payer_plan_id": mcaid["id"], "policy_rank": 2},
    ])
    t = setup_documentation_complete(org, pat["id"], "PN1", "ALS1",
                                     loaded_miles=12.0, emergency_indicator=True)
    claim1 = submit_primary_claim(org, t["id"], med["id"])  # still SUBMITTED, not adjudicated
    v = transport_version(org, t["id"])
    resp = api.create_claim(t["id"], F.create_claim_payload(mcaid["id"], v, prior_claim_id=claim1["id"]),
                            org["biller_h"])
    validate_error(resp, ApiErrorId.ERR_PRIOR_CLAIM_NOT_ADJUDICATED.value)
