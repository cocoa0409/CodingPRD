"""Validation precedence conflicts and boundary precision on claim submit.

Difficulty: priority_pair_validation_conflict (x2), boundary_precision_check
(frequency limit).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_biller_headers,
)
from test_helpers import fixtures as fx


# --------------------------------------------------------------------------
# priority_pair_validation_conflict / coverage_inactive_beats_annual_maximum
# --------------------------------------------------------------------------
def _inactive_and_exhausted(api):
    """Clock 2026-06-01; coverage terminated (term 2026-05-01) AND verified annual
    maximum 0. Returns claim_id."""
    fx.set_clock(api, "2026-06-01T00:00:00Z")
    patient = fx.new_patient(api)
    plan = fx.new_plan(api, annual_maximum_cents=150000, deductible_cents=5000,
                       major_coinsurance_pct=50)
    fx.new_procedure(api)
    cov = fx.new_coverage(api, patient["id"], plan["id"], term_date="2026-05-01")
    fx.new_verification(api, cov, verified_annual_maximum_cents=0,
                        verified_deductible_cents=0)
    claim = fx.new_claim(api, patient["id"], cov["id"],
                         [{"cdt_code": "D2740", "billed_fee_cents": 130000}],
                         service_date="2026-06-01")
    return claim["id"]


def test_coverage_inactive_wins_over_annual_maximum(api):
    """PRD §2.7: "the business rules that follow well-formedness are evaluated in
    this order: coverage active (`ERR_COVERAGE_INACTIVE`), a verification record
    exists on the coverage (`ERR_VERIFICATION_REQUIRED`), the latest verification
    is not expired (`ERR_VERIFICATION_EXPIRED`), per-code frequency limits
    (`ERR_FREQUENCY_LIMIT_EXCEEDED`), required narrative present
    (`ERR_MISSING_NARRATIVE`), required attachment present
    (`ERR_MISSING_ATTACHMENT`), a secondary claim's primary is adjudicated
    (`ERR_PRIMARY_CLAIM_NOT_ADJUDICATED`), and remaining annual maximum available
    (`ERR_ANNUAL_MAXIMUM_EXCEEDED`)."

    Design: Difficulty/priority_pair_validation_conflict/coverage_inactive_beats_annual_maximum
    """
    claim_id = _inactive_and_exhausted(api)
    resp = api.submit_claim(claim_id, make_biller_headers("biller_alice"))
    validate_error(resp, ApiErrorId.ERR_COVERAGE_INACTIVE.value)


def test_annual_maximum_does_not_pre_empt_coverage_inactive(api):
    """PRD §3.5: "The billing coverage must be `ACTIVE`, or the submission is
    rejected with `ERR_COVERAGE_INACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/coverage_inactive_beats_annual_maximum
    """
    claim_id = _inactive_and_exhausted(api)
    resp = api.submit_claim(claim_id, make_biller_headers("biller_alice"))
    err = validate_error(resp, ApiErrorId.ERR_COVERAGE_INACTIVE.value)
    assert err["error_id"] != ApiErrorId.ERR_ANNUAL_MAXIMUM_EXCEEDED.value


# --------------------------------------------------------------------------
# priority_pair_validation_conflict / verification_expired_beats_frequency_limit
# --------------------------------------------------------------------------
def _expired_and_frequency_exceeded(api):
    """Verify at 2026-05-01 (expires 2026-05-31); submit 2 prophy while valid;
    advance to 2026-06-15 (expired) and stage a 3rd prophy (freq 2 also exceeded).
    Returns c3_id."""
    fx.set_clock(api, "2026-05-01T00:00:00Z")
    patient = fx.new_patient(api)
    plan = fx.new_plan(api, annual_maximum_cents=150000, deductible_cents=0,
                       preventive_coinsurance_pct=100)
    fx.new_procedure(api, cdt_code="D1110", description="Prophy", category="PREVENTIVE",
                     ucr_fee_cents=10000, frequency_limit_per_year=2)
    cov = fx.new_coverage(api, patient["id"], plan["id"])
    fx.new_verification(api, cov, verified_deductible_cents=0)
    c1 = fx.new_claim(api, patient["id"], cov["id"],
                      [{"cdt_code": "D1110", "billed_fee_cents": 12000}],
                      service_date="2026-05-01")
    fx.submit_claim(api, c1["id"], submit_user="biller_alice")
    c2 = fx.new_claim(api, patient["id"], cov["id"],
                      [{"cdt_code": "D1110", "billed_fee_cents": 12000}],
                      service_date="2026-05-02")
    fx.submit_claim(api, c2["id"], submit_user="biller_alice")
    fx.set_clock(api, "2026-06-15T00:00:00Z")
    c3 = fx.new_claim(api, patient["id"], cov["id"],
                      [{"cdt_code": "D1110", "billed_fee_cents": 12000}],
                      service_date="2026-06-15")
    return c3["id"]


def test_verification_expired_wins_over_frequency_limit(api):
    """PRD §2.7: "the latest verification is not expired (`ERR_VERIFICATION_EXPIRED`),
    per-code frequency limits (`ERR_FREQUENCY_LIMIT_EXCEEDED`)" (expired precedes
    frequency in the fixed order).

    Design: Difficulty/priority_pair_validation_conflict/verification_expired_beats_frequency_limit
    """
    c3 = _expired_and_frequency_exceeded(api)
    resp = api.submit_claim(c3, make_biller_headers("biller_alice"))
    validate_error(resp, ApiErrorId.ERR_VERIFICATION_EXPIRED.value)


def test_frequency_limit_does_not_pre_empt_expired_verification(api):
    """PRD §3.5: "that latest verification must not be expired at the current
    clock, or it is rejected with `ERR_VERIFICATION_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/verification_expired_beats_frequency_limit
    """
    c3 = _expired_and_frequency_exceeded(api)
    resp = api.submit_claim(c3, make_biller_headers("biller_alice"))
    err = validate_error(resp, ApiErrorId.ERR_VERIFICATION_EXPIRED.value)
    assert err["error_id"] != ApiErrorId.ERR_FREQUENCY_LIMIT_EXCEEDED.value


# --------------------------------------------------------------------------
# boundary_precision_check / frequency_limit_exact_boundary_on_claim_submit
# --------------------------------------------------------------------------
def _three_prophy_claims(api):
    """Verified coverage; prophy freq 2; three prophy claims created. Returns
    (c1_id, c2_id, c3_id)."""
    fx.set_clock(api, "2026-05-01T00:00:00Z")
    patient = fx.new_patient(api)
    plan = fx.new_plan(api, annual_maximum_cents=150000, deductible_cents=0,
                       preventive_coinsurance_pct=100)
    fx.new_procedure(api, cdt_code="D1110", description="Prophy", category="PREVENTIVE",
                     ucr_fee_cents=10000, frequency_limit_per_year=2)
    cov = fx.new_coverage(api, patient["id"], plan["id"])
    fx.new_verification(api, cov, verified_deductible_cents=0)
    c1 = fx.new_claim(api, patient["id"], cov["id"],
                      [{"cdt_code": "D1110", "billed_fee_cents": 12000}],
                      service_date="2026-05-01")
    fx.submit_claim(api, c1["id"], submit_user="biller_alice")
    c2 = fx.new_claim(api, patient["id"], cov["id"],
                      [{"cdt_code": "D1110", "billed_fee_cents": 12000}],
                      service_date="2026-05-05")
    c3 = fx.new_claim(api, patient["id"], cov["id"],
                      [{"cdt_code": "D1110", "billed_fee_cents": 12000}],
                      service_date="2026-05-10")
    return c1["id"], c2["id"], c3["id"]


def test_frequency_second_submit_allowed_at_limit(api):
    """PRD §3.5: "if that prior count is already at or above the limit, the
    submission is rejected ... In other words, the occurrence numbered equal to
    the limit is permitted and the next one past it is refused."

    Design: Difficulty/boundary_precision_check/frequency_limit_exact_boundary_on_claim_submit
    """
    _c1, c2, _c3 = _three_prophy_claims(api)
    resp = api.submit_claim(c2, make_biller_headers("biller_alice"))
    data = validate_success(resp, 200)
    assert data["status"] == "SUBMITTED", \
        f"prior count 1 < 2 should be allowed; got {data['status']}"


def test_frequency_third_submit_rejected_over_limit(api):
    """PRD §3.5: "the system counts prior occurrences of the same `cdt_code`
    across that patient's claims whose `status` is `SUBMITTED`, `ADJUDICATED`,
    `APPEALED`, or `CLOSED` ... if that prior count is already at or above the
    limit, the submission is rejected with `ERR_FREQUENCY_LIMIT_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/frequency_limit_exact_boundary_on_claim_submit
    """
    _c1, c2, c3 = _three_prophy_claims(api)
    fx.submit_claim(api, c2, submit_user="biller_alice")  # prior now 2
    resp = api.submit_claim(c3, make_biller_headers("biller_alice"))
    validate_error(resp, ApiErrorId.ERR_FREQUENCY_LIMIT_EXCEEDED.value)
