"""Loan approval and activation: guard ordering, empty-appraisal boundary,
segregation of duties, coverage, cross-entity policy state, and carnets."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, make_approver_headers, make_registrar_headers,
    make_client, make_artwork, make_loan,
    setup_submitted_loan, setup_approved_loan,
    REG, APPR, COORD,
    api_client as api,
)


# ==========================================================================
# Priority pair: referential (custody) beats fiscal (coverage) on approve
# ==========================================================================
def test_approve_returns_referential_error_over_fiscal():
    """PRD §3.6: "then the artwork's `custody_status` must be `IN_STORAGE`, else
    `ERR_ARTWORK_NOT_AVAILABLE`; then the artwork must have at least one
    `FINALIZED` appraisal, else `ERR_NO_FINALIZED_APPRAISAL`; and finally the
    artwork must have an `ACTIVE` insurance policy whose `insured_value_cents` is
    at least the loan's `required_value_cents`, else `ERR_INSUFFICIENT_COVERAGE`."

    Design: Difficulty/priority_pair_validation_conflict/loan_approve_referential_beats_fiscal
    """
    s = setup_submitted_loan(placed=False, with_appraisal=True, with_policy=True,
                             insured=500000, required=1000000, coverage="STORAGE_ONLY")
    resp = api.transition_loan(s["loan"]["id"], {"to_status": "APPROVED"}, APPR)
    validate_error(resp, ApiErrorId.ERR_ARTWORK_NOT_AVAILABLE.value, 409)


def test_approve_referential_block_leaves_loan_submitted():
    """PRD §3.6: "then the artwork's `custody_status` must be `IN_STORAGE`, else
    `ERR_ARTWORK_NOT_AVAILABLE`; then the artwork must have at least one
    `FINALIZED` appraisal, else `ERR_NO_FINALIZED_APPRAISAL`; and finally the
    artwork must have an `ACTIVE` insurance policy whose `insured_value_cents` is
    at least the loan's `required_value_cents`, else `ERR_INSUFFICIENT_COVERAGE`."

    Design: Difficulty/priority_pair_validation_conflict/loan_approve_referential_beats_fiscal
    """
    s = setup_submitted_loan(placed=False, with_appraisal=True, with_policy=True,
                             insured=500000, required=1000000, coverage="STORAGE_ONLY")
    api.transition_loan(s["loan"]["id"], {"to_status": "APPROVED"}, APPR)
    loan = validate_success(api.get_loan(s["loan"]["id"], REG))
    assert loan["status"] == "SUBMITTED", loan


# ==========================================================================
# Boundary: loan approve with an empty FINALIZED-appraisal set
# ==========================================================================
def test_approve_zero_appraisals_rejected():
    """PRD §3.6: "then the artwork must have at least one `FINALIZED` appraisal,
    else `ERR_NO_FINALIZED_APPRAISAL`".

    Design: Difficulty/boundary_precision_check/loan_approve_empty_appraisal_set
    """
    s = setup_submitted_loan(placed=True, with_appraisal=False, with_policy=True,
                             insured=2000000, required=1000000, coverage="ALL_RISK")
    resp = api.transition_loan(s["loan"]["id"], {"to_status": "APPROVED"}, APPR)
    validate_error(resp, ApiErrorId.ERR_NO_FINALIZED_APPRAISAL.value, 422)


def test_approve_empty_appraisal_leaves_loan_submitted():
    """PRD §3.6: "then the artwork must have at least one `FINALIZED` appraisal,
    else `ERR_NO_FINALIZED_APPRAISAL`".

    Design: Difficulty/boundary_precision_check/loan_approve_empty_appraisal_set
    """
    s = setup_submitted_loan(placed=True, with_appraisal=False, with_policy=True,
                             insured=2000000, required=1000000, coverage="ALL_RISK")
    api.transition_loan(s["loan"]["id"], {"to_status": "APPROVED"}, APPR)
    loan = validate_success(api.get_loan(s["loan"]["id"], REG))
    assert loan["status"] == "SUBMITTED", loan


# ==========================================================================
# Cross-entity state: activation requires an ACTIVE policy
# ==========================================================================
def test_activate_after_policy_cancel_rejected():
    """PRD §3.6: "Activation requires that the artwork's `custody_status` is still
    `IN_STORAGE` (else `ERR_ARTWORK_NOT_AVAILABLE`); that the artwork has an
    `ACTIVE` policy that is not past its `effective_end` — if there is no active
    policy the activation is rejected with `ERR_POLICY_NOT_ACTIVE`".

    Design: Difficulty/cross_entity_state_dependency/loan_activate_requires_active_policy
    """
    s = setup_approved_loan(is_international=False, with_carnet=False)
    get_success_data(api.transition_policy(s["policy"]["id"], {"to_status": "CANCELLED"}, APPR))
    resp = api.transition_loan(s["loan"]["id"], {"to_status": "ACTIVE"}, COORD)
    validate_error(resp, ApiErrorId.ERR_POLICY_NOT_ACTIVE.value, 409)


def test_activate_policy_block_leaves_loan_approved():
    """PRD §3.6: "Activation requires that the artwork's `custody_status` is still
    `IN_STORAGE` (else `ERR_ARTWORK_NOT_AVAILABLE`); that the artwork has an
    `ACTIVE` policy that is not past its `effective_end` — if there is no active
    policy the activation is rejected with `ERR_POLICY_NOT_ACTIVE`".

    Design: Difficulty/cross_entity_state_dependency/loan_activate_requires_active_policy
    """
    s = setup_approved_loan(is_international=False, with_carnet=False)
    get_success_data(api.transition_policy(s["policy"]["id"], {"to_status": "CANCELLED"}, APPR))
    api.transition_loan(s["loan"]["id"], {"to_status": "ACTIVE"}, COORD)
    loan = validate_success(api.get_loan(s["loan"]["id"], REG))
    assert loan["status"] == "APPROVED", loan


# ==========================================================================
# Corner: single-error approval / activation validations
# ==========================================================================
def test_loan_approve_same_user_returns_segregation_of_duties():
    """PRD §3.6: "first, segregation of duties — the approver's `X-User-ID` must
    differ from the recorded `submitted_by_user_id`, else
    `ERR_SEGREGATION_OF_DUTIES`".

    Design: Corner/validations/loan_approve_same_user_returns_segregation_of_duties
    """
    c = make_client()
    a = make_artwork(c["id"], size_class="SMALL", fragility_class="LOW")
    loan = make_loan(a["id"], c["id"], loan_start="2026-06-01T00:00:00Z",
                     loan_end="2026-07-01T00:00:00Z")
    get_success_data(api.transition_loan(loan["id"], {"to_status": "SUBMITTED"},
                                         make_registrar_headers("u-1")))
    resp = api.transition_loan(loan["id"], {"to_status": "APPROVED"},
                               make_approver_headers("u-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)


def test_loan_approve_insufficient_coverage_when_available():
    """PRD §3.6: "and finally the artwork must have an `ACTIVE` insurance policy
    whose `insured_value_cents` is at least the loan's `required_value_cents`, else
    `ERR_INSUFFICIENT_COVERAGE`."

    Design: Corner/validations/loan_approve_insufficient_coverage_when_available
    """
    s = setup_submitted_loan(placed=True, with_appraisal=True, with_policy=True,
                             insured=500000, required=1000000, coverage="STORAGE_ONLY")
    resp = api.transition_loan(s["loan"]["id"], {"to_status": "APPROVED"}, APPR)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_COVERAGE.value, 422)


def test_international_loan_activate_without_carnet_returns_carnet_required():
    """PRD §3.6: "when the loan is international (`is_international` true), that a
    carnet for the loan exists in `ISSUED` status whose `validity_end` is on or
    after the current clock — a missing issued carnet is rejected with
    `ERR_CARNET_REQUIRED`".

    Design: Corner/validations/international_loan_activate_without_carnet_returns_carnet_required
    """
    s = setup_approved_loan(is_international=True, with_carnet=False)
    resp = api.transition_loan(s["loan"]["id"], {"to_status": "ACTIVE"}, COORD)
    validate_error(resp, ApiErrorId.ERR_CARNET_REQUIRED.value, 422)
