"""Establishing claims: threshold boundary, cross-entity gate, precedence, adjustments, OCC."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    setup_calculated_overpayment,
    setup_established_overpayment,
    add_established_overpayment,
    post_adjustment_payload,
    assert_overpayment,
)

SUPERVISOR = TEST_USERS["supervisor_headers"]


def _single_month(final_cents):
    """A one-month claim whose verified over-issuance (hence final) equals final_cents."""
    return [{
        "benefit_month": "2025-05",
        "benefits_issued_cents": 30000,
        "benefits_entitled_reported_cents": 30000 - final_cents,
        "benefits_entitled_verified_cents": 30000 - final_cents,
    }]


# --------------------------------------------------------------------------- #
# Establishment threshold boundary (IHE/AE threshold = 12500, uses >=)
# --------------------------------------------------------------------------- #
def test_establish_at_exact_threshold_succeeds(api):
    """PRD 3.4: "And the claim's `final_amount_cents` must meet the establishment
    threshold for its `claim_type`: for an `IPV` claim the threshold is 0 cents, so any
    amount qualifies; for an `IHE` or `AE` claim the threshold is 12,500 cents (that is,
    $125.00). A final amount below the applicable threshold is rejected with
    `ERR_BELOW_ESTABLISHMENT_THRESHOLD` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/establishment_threshold_exact_boundary
    """
    ctx = setup_calculated_overpayment(api, claim_type="IHE", months=_single_month(12500))
    op_id = ctx["overpayment"]["id"]
    data = validate_success(api.establish_overpayment(op_id, SUPERVISOR))
    assert_overpayment(data)
    assert data["final_amount_cents"] == 12500
    assert data["status"] == "ESTABLISHED", f"expected ESTABLISHED, got {data['status']}"


def test_establish_one_below_threshold_rejected(api):
    """PRD 3.4: "And the claim's `final_amount_cents` must meet the establishment
    threshold for its `claim_type`: for an `IPV` claim the threshold is 0 cents, so any
    amount qualifies; for an `IHE` or `AE` claim the threshold is 12,500 cents (that is,
    $125.00). A final amount below the applicable threshold is rejected with
    `ERR_BELOW_ESTABLISHMENT_THRESHOLD` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/establishment_threshold_exact_boundary
    """
    ctx = setup_calculated_overpayment(api, claim_type="IHE", months=_single_month(12499))
    resp = api.establish_overpayment(ctx["overpayment"]["id"], SUPERVISOR)
    validate_error(resp, ApiErrorId.ERR_BELOW_ESTABLISHMENT_THRESHOLD.value)


def test_establish_one_above_threshold_succeeds(api):
    """PRD 3.4: "And the claim's `final_amount_cents` must meet the establishment
    threshold for its `claim_type`: for an `IPV` claim the threshold is 0 cents, so any
    amount qualifies; for an `IHE` or `AE` claim the threshold is 12,500 cents (that is,
    $125.00). A final amount below the applicable threshold is rejected with
    `ERR_BELOW_ESTABLISHMENT_THRESHOLD` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/establishment_threshold_exact_boundary
    """
    ctx = setup_calculated_overpayment(api, claim_type="IHE", months=_single_month(12501))
    data = validate_success(api.establish_overpayment(ctx["overpayment"]["id"], SUPERVISOR))
    assert data["status"] == "ESTABLISHED"


# --------------------------------------------------------------------------- #
# Cross-entity gate: establish requires SUBSTANTIATED case
# --------------------------------------------------------------------------- #
def test_establish_requires_substantiated_case(api):
    """PRD 3.4: "The linked case must be `SUBSTANTIATED`, otherwise the request is
    rejected with `ERR_CASE_NOT_SUBSTANTIATED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/establish_requires_case_substantiated
    """
    # Case left in PENDING_REVIEW; claim above threshold to isolate the cross-entity gate.
    ctx = setup_calculated_overpayment(api, claim_type="IHE", substantiate=False)
    resp = api.establish_overpayment(ctx["overpayment"]["id"], SUPERVISOR)
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_SUBSTANTIATED.value)


def test_establish_succeeds_once_case_substantiated(api):
    """PRD 3.4: "The linked case must be `SUBSTANTIATED`, otherwise the request is
    rejected with `ERR_CASE_NOT_SUBSTANTIATED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/establish_requires_case_substantiated
    """
    ctx = setup_calculated_overpayment(api, claim_type="IHE", substantiate=True)
    data = validate_success(api.establish_overpayment(ctx["overpayment"]["id"], SUPERVISOR))
    assert data["status"] == "ESTABLISHED"


# --------------------------------------------------------------------------- #
# Priority pair: state/cross-entity gate beats fiscal threshold
# --------------------------------------------------------------------------- #
def test_case_not_substantiated_beats_below_threshold(api):
    """PRD 2.9: "In short: authentication before authorization before existence before
    shape before enum/format before pagination before state before cross-entity
    preconditions before segregation of duties before domain constraints before temporal
    before fiscal before concurrency."
    PRD 3.4: "The linked case must be `SUBSTANTIATED`, otherwise the request is rejected
    with `ERR_CASE_NOT_SUBSTANTIATED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_establish
    """
    # Both violated: case not SUBSTANTIATED (cross-entity) AND final 8000 < 12500 (fiscal).
    ctx = setup_calculated_overpayment(api, claim_type="IHE", substantiate=False,
                                       months=_single_month(8000))
    resp = api.establish_overpayment(ctx["overpayment"]["id"], SUPERVISOR)
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_SUBSTANTIATED.value)


def test_below_threshold_fires_when_case_substantiated(api):
    """PRD 2.9: "In short: authentication before authorization before existence before
    shape before enum/format before pagination before state before cross-entity
    preconditions before segregation of duties before domain constraints before temporal
    before fiscal before concurrency."
    PRD 3.4: "A final amount below the applicable threshold is rejected with
    `ERR_BELOW_ESTABLISHMENT_THRESHOLD` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_establish
    """
    # Cross-entity gate satisfied (SUBSTANTIATED); only the fiscal threshold now fails.
    ctx = setup_calculated_overpayment(api, claim_type="IHE", substantiate=True,
                                       months=_single_month(8000))
    resp = api.establish_overpayment(ctx["overpayment"]["id"], SUPERVISOR)
    validate_error(resp, ApiErrorId.ERR_BELOW_ESTABLISHMENT_THRESHOLD.value)


def test_establish_below_threshold_pure(api):
    """PRD 3.4: "A final amount below the applicable threshold is rejected with
    `ERR_BELOW_ESTABLISHMENT_THRESHOLD` (HTTP 422)."

    Design: Corner/validations/establish_below_threshold_pure
    """
    ctx = setup_calculated_overpayment(api, claim_type="IHE", substantiate=True,
                                       months=_single_month(8000))
    resp = api.establish_overpayment(ctx["overpayment"]["id"], SUPERVISOR)
    validate_error(resp, ApiErrorId.ERR_BELOW_ESTABLISHMENT_THRESHOLD.value)


# --------------------------------------------------------------------------- #
# Fair-hearing adjustments + OCC
# --------------------------------------------------------------------------- #
def test_adjustment_recomputes_final_amount(api):
    """PRD 3.4: "Posting an adjustment adds `adjustment_amount_cents` to the running
    `total_adjustments_cents`, recomputes `final_amount_cents` (the verified-income sum
    plus the new `total_adjustments_cents`), and increments the overpayment's `version`
    by 1."

    Design: Corner/cross_cutting_complexity_layers/adjustment_recomputes_final_amount
    """
    ctx = setup_established_overpayment(api, claim_type="IHE")  # final 45050
    op = ctx["overpayment"]
    resp = api.post_adjustment(
        op["id"], post_adjustment_payload(5000, op["version"]), SUPERVISOR
    )
    data = validate_success(resp)
    assert data["total_adjustments_cents"] == 5000, (
        f"expected total_adjustments 5000, got {data['total_adjustments_cents']}"
    )
    assert data["final_amount_cents"] == 50050, (
        f"expected final 50050, got {data['final_amount_cents']}"
    )


def test_stale_version_adjustment_rejected(api):
    """PRD 2.8: "If `expected_overpayment_version` does not equal the overpayment's
    current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412), and
    the client must re-read the overpayment and retry against the fresh version."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_overpayment_adjustment_conflict
    """
    ctx = setup_established_overpayment(api, claim_type="IHE")
    op = ctx["overpayment"]
    observed_version = op["version"]
    # First adjustment against the observed version succeeds and advances version.
    validate_success(
        api.post_adjustment(op["id"], post_adjustment_payload(5000, observed_version), SUPERVISOR)
    )
    # Second adjustment carrying the now-stale observed version is refused.
    resp = api.post_adjustment(
        op["id"], post_adjustment_payload(-2000, observed_version), SUPERVISOR
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
