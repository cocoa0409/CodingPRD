"""Cyclic dispute revision loop and the conserved allowed-amount partition."""
from test_helpers import validate_success, validate_error, ApiErrorId, fixtures, TEST_USERS

PROVIDER = TEST_USERS["provider_staff_headers"]


# --------------------------------------------------------------------------
# Difficulty — cyclic ISSUED -> DISPUTED -> ISSUED
# --------------------------------------------------------------------------
def test_uphold_returns_estimate_to_issued(api):
    """PRD §3.5: "Resolution requires a resolution outcome and returns the
    estimate from DISPUTED back to ISSUED in both cases, which is what makes the
    loop cyclic."

    Design: Difficulty/non_linear_state_machine/nlsm_estimate_cyclic_dispute_loop
    """
    b = fixtures.setup_issued_with_dispute_under_review(api)
    assert b["estimate"]["status"] == "DISPUTED"
    validate_success(
        api.resolve_dispute(b["dispute"]["id"],
                            {"resolution": "UPHELD",
                             "resolution_note": "Estimate confirmed accurate"},
                            PROVIDER), 200)
    estimate = validate_success(api.get_estimate(b["estimate"]["id"], PROVIDER), 200)
    assert estimate["status"] == "ISSUED"


def test_uphold_leaves_numbers_unchanged(api):
    """PRD §3.5: "When the outcome upholds the original estimate, the dispute
    settles in RESOLVED_UPHELD, an optional resolution_note may be recorded, and
    the estimate's numbers are left exactly as issued."

    Design: Difficulty/non_linear_state_machine/nlsm_estimate_cyclic_dispute_loop
    """
    b = fixtures.setup_issued_with_dispute_under_review(api)
    dispute = validate_success(
        api.resolve_dispute(b["dispute"]["id"], {"resolution": "UPHELD"}, PROVIDER), 200)
    assert dispute["status"] == "RESOLVED_UPHELD"
    estimate = validate_success(api.get_estimate(b["estimate"]["id"], PROVIDER), 200)
    assert estimate["patient_responsibility_cents"] == 122500


# --------------------------------------------------------------------------
# Corner — adjustment out of range
# --------------------------------------------------------------------------
def test_dispute_adjust_out_of_range(api):
    """PRD §3.5: "The adjusted value must lie between 0 and the estimate's current
    patient_responsibility_cents inclusive; an adjustment outside that range ...
    is rejected with ERR_INVALID_ADJUSTMENT."

    Design: Corner/validations/dispute_adjust_out_of_range_returns_invalid_adjustment
    """
    b = fixtures.setup_issued_with_dispute_under_review(api)
    resp = api.resolve_dispute(
        b["dispute"]["id"],
        {"resolution": "ADJUSTED", "adjusted_patient_responsibility_cents": 999999},
        PROVIDER)
    validate_error(resp, ApiErrorId.ERR_INVALID_ADJUSTMENT.value, 422)


# --------------------------------------------------------------------------
# Difficulty — allowed partition conserved under ADJUSTED
# --------------------------------------------------------------------------
def test_adjust_moves_patient_plan_split(api):
    """PRD §3.5: "the reviewer must supply
    `adjusted_patient_responsibility_cents`, which becomes the estimate's new
    `patient_responsibility_cents`; the estimate's `plan_paid_cents` is then
    recomputed as its `allowed_amount_cents` minus that adjusted value."

    Design: Difficulty/compensating_invariant/ci_allowed_partition_conserved_under_dispute
    """
    b = fixtures.setup_issued_with_dispute_under_review(api, disputed_amount_cents=32500)
    assert b["estimate"]["plan_paid_cents"] == 77500
    validate_success(
        api.resolve_dispute(b["dispute"]["id"],
                            {"resolution": "ADJUSTED",
                             "adjusted_patient_responsibility_cents": 90000,
                             "resolution_note": "Reduced per goodwill"},
                            PROVIDER), 200)
    estimate = validate_success(api.get_estimate(b["estimate"]["id"], PROVIDER), 200)
    assert estimate["patient_responsibility_cents"] == 90000
    assert estimate["plan_paid_cents"] == 110000


def test_adjust_conserves_allowed_amount(api):
    """PRD §3.5: "so the allowed amount is conserved and only the patient/plan
    split moves." PRD §3.5: "Resolution ... returns the estimate from DISPUTED
    back to ISSUED in both cases."

    Design: Difficulty/compensating_invariant/ci_allowed_partition_conserved_under_dispute
    """
    b = fixtures.setup_issued_with_dispute_under_review(api, disputed_amount_cents=32500)
    validate_success(
        api.resolve_dispute(b["dispute"]["id"],
                            {"resolution": "ADJUSTED",
                             "adjusted_patient_responsibility_cents": 90000},
                            PROVIDER), 200)
    estimate = validate_success(api.get_estimate(b["estimate"]["id"], PROVIDER), 200)
    assert estimate["allowed_amount_cents"] == 200000
    assert estimate["status"] == "ISSUED"
    assert estimate["allowed_amount_cents"] == (
        estimate["patient_responsibility_cents"] + estimate["plan_paid_cents"])
