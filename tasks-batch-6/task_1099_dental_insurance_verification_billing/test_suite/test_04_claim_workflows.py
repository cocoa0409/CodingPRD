"""Claim lifecycle: appeal loop, adjudication cascade, cross-entity submit gates.

Difficulty: non_linear_state_machine (claim cycle), transitive_cascade
(insurance posting), cross_entity_state_dependency (x2).
Corner: appeal_on_submitted, patient_balance_collections, claim_aging.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_biller_headers, make_manager_headers,
)
from test_helpers import fixtures as fx


# --------------------------------------------------------------------------
# non_linear_state_machine / claim_denied_appealed_adjudicated_cycle
# --------------------------------------------------------------------------
def _denied_crown_claim(api):
    """Crown claim submitted then denied. Returns (pid, claim_id)."""
    sc, submitted = fx.submitted_crown_claim(api, submit_user="biller_alice")
    fx.post_insurance_denial(api, sc["patient"]["id"], submitted["id"], post_user="mgr_bob")
    return sc["patient"]["id"], submitted["id"]


def test_appeal_moves_denied_to_appealed(api):
    """PRD §3.6: "Both a denied claim and an under-paid adjudicated claim can be
    **appealed**, moving the claim to `APPEALED` and incrementing `appeal_count`
    by one."

    Design: Difficulty/non_linear_state_machine/claim_denied_appealed_adjudicated_cycle
    """
    _pid, claim_id = _denied_crown_claim(api)
    resp = api.appeal_claim(claim_id, make_biller_headers("biller_alice"))
    data = validate_success(resp, 200)
    assert data["status"] == "APPEALED", f"expected APPEALED, got {data['status']}"
    assert data["appeal_count"] == 1, f"expected 1, got {data['appeal_count']}"


def test_post_appeal_eob_readjudicates(api):
    """PRD §3.6: "a non-denial posting moves it from `APPEALED` back to
    `ADJUDICATED`."

    Design: Difficulty/non_linear_state_machine/claim_denied_appealed_adjudicated_cycle
    """
    pid, claim_id = _denied_crown_claim(api)
    fx.get_success_data(api.appeal_claim(claim_id, make_biller_headers("biller_alice")))
    fx.post_insurance_eob(api, pid, claim_id, amount_cents=57500, allowed_cents=120000,
                          paid_cents=57500, deductible_applied_cents=5000, post_user="mgr_bob")
    claim = get_success_data(api.get_claim(claim_id, make_biller_headers()))
    assert claim["status"] == "ADJUDICATED", f"expected ADJUDICATED, got {claim['status']}"
    assert claim["paid_insurance_cents"] == 57500, \
        f"expected 57500, got {claim['paid_insurance_cents']}"


# --------------------------------------------------------------------------
# transitive_cascade / insurance_posting_cascade_...
# --------------------------------------------------------------------------
def test_adjudication_cascade_claim_and_patient_balance(api):
    """PRD §3.6: "`final_patient_portion_cents` becomes `total_billed_cents` minus
    `paid_insurance_cents`. ... Adjudication then cascades: the patient's
    `balance_cents` is re-derived to fold in the newly opened patient portion."

    Design: Difficulty/transitive_cascade/insurance_posting_cascade_payment_claim_patientbalance_patientstatus
    """
    sc, claim, _pay = fx.adjudicated_crown_claim(api)
    assert claim["status"] == "ADJUDICATED"
    assert claim["final_patient_portion_cents"] == 72500, \
        f"expected 72500, got {claim['final_patient_portion_cents']}"
    patient = get_success_data(api.get_patient(sc["patient"]["id"], make_biller_headers()))
    assert patient["balance_cents"] == 72500, \
        f"expected 72500, got {patient['balance_cents']}"


def test_adjudication_cascade_patient_status_and_coverage(api):
    """PRD §3.6: "the patient's `status` is recomputed (`COLLECTIONS` above 50,000
    cents, else `ACTIVE`), and — in parallel — the billing coverage's
    `benefits_used_cents` is increased by the paid amount."

    Design: Difficulty/transitive_cascade/insurance_posting_cascade_payment_claim_patientbalance_patientstatus
    """
    sc, _claim, _pay = fx.adjudicated_crown_claim(api)
    patient = get_success_data(api.get_patient(sc["patient"]["id"], make_biller_headers()))
    assert patient["status"] == "COLLECTIONS", \
        f"expected COLLECTIONS (balance 72500 > 50000), got {patient['status']}"
    coverage = get_success_data(api.get_coverage(sc["coverage"]["id"], make_biller_headers()))
    assert coverage["benefits_used_cents"] == 57500, \
        f"expected 57500, got {coverage['benefits_used_cents']}"


# --------------------------------------------------------------------------
# cross_entity_state_dependency / claim_submit_depends_on_coverage_verification
# --------------------------------------------------------------------------
def test_submit_without_verification_rejected(api):
    """PRD §3.5: "The coverage must have at least one verification record on file,
    or the submission is rejected with `ERR_VERIFICATION_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/claim_submit_depends_on_coverage_verification
    """
    patient = fx.new_patient(api)
    plan = fx.new_plan(api, annual_maximum_cents=150000, major_coinsurance_pct=50,
                       deductible_cents=5000)
    fx.new_procedure(api)
    cov = fx.new_coverage(api, patient["id"], plan["id"])  # no verification
    claim = fx.new_claim(api, patient["id"], cov["id"],
                         [{"cdt_code": "D2740", "billed_fee_cents": 130000}])
    resp = api.submit_claim(claim["id"], make_biller_headers("biller_alice"))
    validate_error(resp, ApiErrorId.ERR_VERIFICATION_REQUIRED.value)


def test_submit_succeeds_after_verification(api):
    """PRD §3.5: "Submitting a claim advances it from `DRAFT` to `SUBMITTED`."
    PRD §3.2: "Benefits must be verified before they can be billed."

    Design: Difficulty/cross_entity_state_dependency/claim_submit_depends_on_coverage_verification
    """
    patient = fx.new_patient(api)
    plan = fx.new_plan(api, annual_maximum_cents=150000, major_coinsurance_pct=50,
                       deductible_cents=5000)
    fx.new_procedure(api)
    cov = fx.new_coverage(api, patient["id"], plan["id"])
    fx.new_verification(api, cov)
    claim = fx.new_claim(api, patient["id"], cov["id"],
                         [{"cdt_code": "D2740", "billed_fee_cents": 130000}])
    resp = api.submit_claim(claim["id"], make_biller_headers("biller_alice"))
    data = validate_success(resp, 200)
    assert data["status"] == "SUBMITTED", f"expected SUBMITTED, got {data['status']}"


# --------------------------------------------------------------------------
# cross_entity_state_dependency / secondary_claim_depends_on_primary_adjudicated
# --------------------------------------------------------------------------
def _secondary_setup(api):
    """Primary crown claim only SUBMITTED (not paid); a secondary claim referencing
    it, still DRAFT. Returns (pid, primary_id, secondary_id)."""
    patient = fx.new_patient(api)
    pa = fx.new_plan(api, payer_name="PrimaryCo", plan_name="PA",
                     annual_maximum_cents=150000, deductible_cents=5000,
                     major_coinsurance_pct=50)
    sb = fx.new_plan(api, payer_name="SecCo", plan_name="SB",
                     annual_maximum_cents=150000, deductible_cents=5000,
                     major_coinsurance_pct=50, cob_method="STANDARD")
    fx.new_procedure(api, cdt_code="D2740", description="Crown", category="MAJOR",
                     ucr_fee_cents=120000)
    covp = fx.new_coverage(api, patient["id"], pa["id"], priority="PRIMARY",
                           subscriber_id="SA")
    fx.new_verification(api, covp)
    covs = fx.new_coverage(api, patient["id"], sb["id"], priority="SECONDARY",
                           subscriber_id="SB")
    fx.new_verification(api, covs)
    c0 = fx.new_claim(api, patient["id"], covp["id"],
                      [{"cdt_code": "D2740", "billed_fee_cents": 130000}])
    fx.submit_claim(api, c0["id"], submit_user="biller_alice")
    c1 = fx.new_claim(api, patient["id"], covs["id"],
                      [{"cdt_code": "D2740", "billed_fee_cents": 130000}],
                      primary_claim_id=c0["id"])
    return patient["id"], c0["id"], c1["id"]


def test_secondary_before_primary_adjudicated_rejected(api):
    """PRD §3.5: "When `primary_claim_id` is set, the referenced primary claim
    must already be `ADJUDICATED`, `DENIED`, or `CLOSED`, or the submission is
    rejected with `ERR_PRIMARY_CLAIM_NOT_ADJUDICATED`."

    Design: Difficulty/cross_entity_state_dependency/secondary_claim_depends_on_primary_adjudicated
    """
    _pid, _c0, c1 = _secondary_setup(api)
    resp = api.submit_claim(c1, make_biller_headers("biller_alice"))
    validate_error(resp, ApiErrorId.ERR_PRIMARY_CLAIM_NOT_ADJUDICATED.value)


def test_secondary_succeeds_after_primary_adjudicated(api):
    """PRD §3.5: "the referenced primary claim must already be `ADJUDICATED`,
    `DENIED`, or `CLOSED`" (once satisfied the secondary submits).

    Design: Difficulty/cross_entity_state_dependency/secondary_claim_depends_on_primary_adjudicated
    """
    pid, c0, c1 = _secondary_setup(api)
    fx.post_insurance_eob(api, pid, c0, amount_cents=57500, allowed_cents=120000,
                          paid_cents=57500, deductible_applied_cents=5000, post_user="mgr_bob")
    resp = api.submit_claim(c1, make_biller_headers("biller_alice"))
    data = validate_success(resp, 200)
    assert data["status"] == "SUBMITTED", f"expected SUBMITTED, got {data['status']}"


# --------------------------------------------------------------------------
# Corner: state_machines / appeal_on_submitted_claim_not_allowed
# --------------------------------------------------------------------------
def test_appeal_on_submitted_claim_not_allowed(api):
    """PRD §3.6: "a claim may be appealed only while it is `DENIED` or
    `ADJUDICATED` and only while its `appeal_count` is below the limit of 2; an
    attempt outside those conditions is rejected with `ERR_APPEAL_NOT_ALLOWED`."

    Design: Corner/state_machines/appeal_on_submitted_claim_not_allowed
    """
    _sc, submitted = fx.submitted_crown_claim(api, submit_user="biller_alice")
    resp = api.appeal_claim(submitted["id"], make_biller_headers("biller_alice"))
    validate_error(resp, ApiErrorId.ERR_APPEAL_NOT_ALLOWED.value)


# --------------------------------------------------------------------------
# Corner: calculations / patient_balance_collections_threshold
# --------------------------------------------------------------------------
def test_patient_balance_collections_threshold(api):
    """PRD §3.6: "On a denial, `paid_insurance_cents` is 0 ... and
    `final_patient_portion_cents` becomes the full `total_billed_cents`; the
    patient's balance is re-derived to reflect that the entire billed amount is
    now their responsibility."
    PRD §3.1: "A patient's `status` becomes `COLLECTIONS` whenever the derived
    `balance_cents` rises above the collections threshold of 50,000 cents."

    Design: Corner/calculations/patient_balance_collections_threshold
    """
    sc, submitted = fx.submitted_crown_claim(api, billed_fee_cents=130000,
                                             submit_user="biller_alice")
    fx.post_insurance_denial(api, sc["patient"]["id"], submitted["id"], post_user="mgr_bob")
    patient = get_success_data(api.get_patient(sc["patient"]["id"], make_biller_headers()))
    assert patient["balance_cents"] == 130000, \
        f"expected 130000, got {patient['balance_cents']}"
    assert patient["status"] == "COLLECTIONS", \
        f"expected COLLECTIONS, got {patient['status']}"


# --------------------------------------------------------------------------
# Corner: calculations / claim_aging_bucket_31_60
# --------------------------------------------------------------------------
def test_claim_aging_bucket_31_60(api):
    """PRD §2.11: "`aging_days` value is the whole number of days between the
    claim's `submitted_at` and the current logical clock ... `DAYS_31_60` when it
    is between 31 and 60 inclusive."

    Design: Corner/calculations/claim_aging_bucket_31_60
    """
    sc, submitted = fx.submitted_crown_claim(api, clock="2026-05-01T00:00:00Z",
                                             submit_user="biller_alice")
    fx.set_clock(api, "2026-06-15T00:00:00Z")
    fx.run_billing(api)
    claim = get_success_data(api.get_claim(submitted["id"], make_biller_headers()))
    assert claim["aging_days"] == 45, f"expected 45, got {claim['aging_days']}"
    assert claim["aging_bucket"] == "DAYS_31_60", \
        f"expected DAYS_31_60, got {claim['aging_bucket']}"
