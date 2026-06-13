"""Proof-of-purchase validation, rejection-reason ordering, and the
proof -> registration activation cascade (PRD §3.3)."""
from test_helpers import set_clock, validate_error, validate_success
from test_helpers import fixtures as F


# ─── Difficulty: transitive_cascade (depth-2 proof -> registration) ──────────
def test_proof_validate_activates_registration_cascade(api):
    """PRD §3.3: "When both checks pass, the proof becomes `VALIDATED`, its
    `rejection_reason` is set to null, and the parent registration's
    `proof_status` is set to `VALIDATED`."
    PRD §3.3: "If the registration was in `REGISTERED` at the moment its proof is
    validated, it advances from `REGISTERED` to `ACTIVE`, becoming claim-eligible."

    Design: Difficulty/transitive_cascade/proof_validate_cascades_proof_then_registration_activation
    """
    set_clock("2024-01-15T00:00:00Z")
    product = F.create_product()
    F.create_tier(product["id"], tier_name="BASE", coverage_cap_cents=20000)
    owner = F.create_owner()
    reg = F.create_registration(product["id"], owner["id"], purchase_date="2024-01-15T00:00:00Z")
    proof = F.submit_proof(
        reg["id"], owner["id"], stated_purchase_date="2024-01-15T00:00:00Z", stated_amount_cents=50000
    )
    validated = F.validate_proof(proof["id"])
    assert validated["status"] == "VALIDATED"
    reg_after = F.get_registration(reg["id"], owner["id"])
    assert reg_after["proof_status"] == "VALIDATED"
    assert reg_after["status"] == "ACTIVE"


def test_proof_validate_sets_proof_status_and_clears_rejection_reason(api):
    """PRD §3.3: "When both checks pass, the proof becomes `VALIDATED`, its
    `rejection_reason` is set to null, and the parent registration's
    `proof_status` is set to `VALIDATED`."

    Design: Difficulty/transitive_cascade/proof_validate_cascades_proof_then_registration_activation
    """
    set_clock("2024-01-15T00:00:00Z")
    product = F.create_product()
    F.create_tier(product["id"], tier_name="BASE", coverage_cap_cents=20000)
    owner = F.create_owner()
    reg = F.create_registration(product["id"], owner["id"], purchase_date="2024-01-15T00:00:00Z")
    proof = F.submit_proof(
        reg["id"], owner["id"], stated_purchase_date="2024-01-15T00:00:00Z", stated_amount_cents=50000
    )
    validated = F.validate_proof(proof["id"])
    assert validated["status"] == "VALIDATED"
    assert validated["rejection_reason"] is None


# ─── Corner: state machine — validate already-validated proof ────────────────
def test_validate_already_validated_proof_returns_invalid_state(api):
    """PRD §3.3: "A proof can only be validated while it is `SUBMITTED`."
    PRD §2.10: "the target resource's state is checked fourth, yielding
    `ERR_INVALID_STATE` (HTTP 409) when the resource is not in a state from which
    the requested transition is legal."

    Design: Corner/state_machines/validate_proof_from_already_validated_returns_invalid_state
    """
    set_clock("2024-01-15T00:00:00Z")
    product = F.create_product()
    F.create_tier(product["id"], tier_name="BASE", coverage_cap_cents=20000)
    owner = F.create_owner()
    reg = F.create_registration(product["id"], owner["id"], purchase_date="2024-01-15T00:00:00Z")
    proof = F.submit_proof(reg["id"], owner["id"], stated_amount_cents=50000)
    F.validate_proof(proof["id"])
    resp = api.validate_proof(proof["id"], F.ADMIN)
    validate_error(resp, "ERR_INVALID_STATE")
    assert F.get_registration(reg["id"], owner["id"])["proof_status"] == "VALIDATED"


# ─── Corner: rejection-reason outcomes ───────────────────────────────────────
def test_proof_amount_beyond_tolerance_rejected_amount_mismatch(api):
    """PRD §3.3: "the absolute difference between the stated amount and the
    registration's purchase price must be no more than 500 cents."
    PRD §3.3: "the amount differs by more than the 500-cent tolerance — the proof
    becomes `REJECTED`, the parent registration's `proof_status` is set to
    `REJECTED`, and `rejection_reason` is set to the first failing check ...
    with the available reason codes being `DATE_MISMATCH`, `AMOUNT_MISMATCH`, and
    `EXPIRED_WINDOW`".

    Design: Corner/validations/proof_validate_amount_beyond_tolerance_rejected_amount_mismatch
    """
    set_clock("2024-01-15T00:00:00Z")
    product = F.create_product()
    F.create_tier(product["id"], tier_name="BASE", coverage_cap_cents=20000)
    owner = F.create_owner()
    reg = F.create_registration(
        product["id"], owner["id"], purchase_date="2024-01-15T00:00:00Z", purchase_price_cents=50000
    )
    # Date in window, amount off by 1000 (> 500 tolerance).
    proof = F.submit_proof(
        reg["id"], owner["id"], stated_purchase_date="2024-01-20T00:00:00Z", stated_amount_cents=51000
    )
    rejected = F.validate_proof(proof["id"])
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "AMOUNT_MISMATCH"
    assert F.get_registration(reg["id"], owner["id"])["proof_status"] == "REJECTED"


def test_proof_date_outside_window_rejected_date_checked_first(api):
    """PRD §3.3: "`rejection_reason` is set to the first failing check evaluated
    in this order: the date check is evaluated before the amount check, which is
    evaluated before the window check".
    PRD §3.3: "The stated purchase date must fall within 90 days of the
    registration's purchase date".

    Design: Corner/validations/proof_validate_date_outside_window_rejected_date_checked_first
    """
    set_clock("2024-01-15T00:00:00Z")
    product = F.create_product()
    F.create_tier(product["id"], tier_name="BASE", coverage_cap_cents=20000)
    owner = F.create_owner()
    reg = F.create_registration(
        product["id"], owner["id"], purchase_date="2024-01-15T00:00:00Z", purchase_price_cents=50000
    )
    # Date >90 days off AND amount mismatched; date is the first failing check.
    proof = F.submit_proof(
        reg["id"], owner["id"], stated_purchase_date="2024-06-01T00:00:00Z", stated_amount_cents=60000
    )
    rejected = F.validate_proof(proof["id"])
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "DATE_MISMATCH"
