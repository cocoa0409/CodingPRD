"""Claims, deposit settlement, resolution cascades, OCC, RBAC, and conservation."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, make_renter_headers, assert_deposit_conserved,
    platform_headers as _platform_headers,
    setup_open_claim, setup_claim_under_review,
)


def _resolve(api, claim_id, payload):
    return api.resolve_claim(claim_id, payload, _platform_headers())


# --- Deposit settlement: provisional vs final (Difficulty/dual_variant_calc) --

def test_deposit_capture_diverges_from_provisional_on_partial(api):
    """PRD §3.7: "Opening a claim creates it in OPEN status and computes the provisional
    form of the deposit settlement rule: provisional_capture_cents is the smaller of
    claimed_amount_cents and the deposit's current held_cents."
    PRD §3.7: "For an approved or partially-approved claim, the final deposit settlement is
    computed identically with the branch's award: deposit_capture_cents is the smaller of
    approved_amount_cents and the deposit's current held_cents."

    Design: Difficulty/dual_variant_calc/deposit_settlement_provisional_vs_final_on_deposit
    """
    sc = setup_claim_under_review(api, claimed_amount_cents=40000, deposit_cents=50000)
    assert sc["claim"]["provisional_capture_cents"] == 40000, sc["claim"]["provisional_capture_cents"]
    resolved = get_success_data(_resolve(api, sc["claim_id"], {
        "decision": "PARTIAL", "approved_amount_cents": 15000,
        "expected_deposit_version": sc["deposit_version"],
    }))
    assert resolved["provisional_capture_cents"] == 40000, resolved["provisional_capture_cents"]
    assert resolved["deposit_capture_cents"] == 15000, resolved["deposit_capture_cents"]


def test_partial_resolution_sets_partially_approved_status(api):
    """PRD §3.7: "Partial transitions UNDER_REVIEW → PARTIALLY_APPROVED. The resolve payload
    supplies an approved_amount_cents that must be strictly greater than 0 and strictly less
    than claimed_amount_cents ... That payload amount becomes the claim's approved_amount_cents."

    Design: Difficulty/dual_variant_calc/deposit_settlement_provisional_vs_final_on_deposit
    """
    sc = setup_claim_under_review(api, claimed_amount_cents=40000, deposit_cents=50000)
    resolved = get_success_data(_resolve(api, sc["claim_id"], {
        "decision": "PARTIAL", "approved_amount_cents": 15000,
        "expected_deposit_version": sc["deposit_version"],
    }))
    assert resolved["status"] == "PARTIALLY_APPROVED", resolved["status"]
    assert resolved["approved_amount_cents"] == 15000, resolved["approved_amount_cents"]


# --- Claim branching: DENY leaves deposit untouched (Difficulty/non_linear) ---

def test_deny_resolution_captures_nothing(api):
    """PRD §3.7: "Deny transitions UNDER_REVIEW → DENIED. The approved_amount_cents,
    deposit_capture_cents, and coverage_paid_cents are all set to 0 and the deposit is left
    untouched."

    Design: Difficulty/non_linear_state_machine/claim_branching_denied_leaves_deposit_untouched
    """
    sc = setup_claim_under_review(api, claimed_amount_cents=30000, deposit_cents=50000)
    resolved = get_success_data(_resolve(api, sc["claim_id"], {
        "decision": "DENY", "expected_deposit_version": sc["deposit_version"],
    }))
    assert resolved["status"] == "DENIED", resolved["status"]
    assert resolved["deposit_capture_cents"] == 0, resolved["deposit_capture_cents"]


def test_deny_resolution_leaves_deposit_fully_held(api):
    """PRD §3.7: "A deny resolution performs none of these captures ..."
    PRD §3.7: "Deny transitions UNDER_REVIEW → DENIED. The approved_amount_cents,
    deposit_capture_cents, and coverage_paid_cents are all set to 0 and the deposit is left
    untouched."

    Design: Difficulty/non_linear_state_machine/claim_branching_denied_leaves_deposit_untouched
    """
    sc = setup_claim_under_review(api, claimed_amount_cents=30000, deposit_cents=50000)
    get_success_data(_resolve(api, sc["claim_id"], {
        "decision": "DENY", "expected_deposit_version": sc["deposit_version"],
    }))
    deposit = get_success_data(api.get_deposit(sc["booking_id"], sc["owner_headers"]))[0]
    assert deposit["held_cents"] == 50000, deposit["held_cents"]
    assert deposit["captured_cents"] == 0, deposit["captured_cents"]


# --- Resolve-capture cascade depth (Difficulty/transitive_cascade) -----------

def test_approve_resolution_captures_and_recomputes_payout(api):
    """PRD §3.7: "It captures deposit_capture_cents from the deposit: those cents move out
    of held_cents and into captured_cents, and the deposit's version increments."
    PRD §3.7: "The booking's payout is then updated: damage_reimbursement_cents accumulates
    the sum, over the booking's resolved (approved or partially-approved) claims, of each
    claim's deposit_capture_cents plus coverage_paid_cents, and net_payout_cents is
    recomputed accordingly."

    Design: Difficulty/transitive_cascade/claim_resolve_capture_cascade_depth3
    """
    sc = setup_claim_under_review(api, claimed_amount_cents=30000, deposit_cents=50000,
                                  base_daily_rate_cents=10000)
    get_success_data(_resolve(api, sc["claim_id"], {
        "decision": "APPROVE", "expected_deposit_version": sc["deposit_version"],
    }))
    deposit = get_success_data(api.get_deposit(sc["booking_id"], sc["owner_headers"]))[0]
    assert deposit["held_cents"] == 20000, deposit["held_cents"]
    assert deposit["captured_cents"] == 30000, deposit["captured_cents"]
    payout = get_success_data(api.get_payout(sc["booking_id"], sc["owner_headers"]))[0]
    assert payout["damage_reimbursement_cents"] == 30000, payout["damage_reimbursement_cents"]
    assert payout["net_payout_cents"] == 86610, payout["net_payout_cents"]


def test_approve_resolution_penalizes_renter_upheld_claim(api):
    """PRD §3.7: "Finally the renter's upheld_claim_count is incremented by 1 and their
    trust_score is recomputed."
    PRD §3.9: "subtract 40 points for each upheld claim against them as a renter
    (upheld_claim_count)."

    Design: Difficulty/transitive_cascade/claim_resolve_capture_cascade_depth3
    """
    sc = setup_claim_under_review(api, claimed_amount_cents=30000, deposit_cents=50000,
                                  base_daily_rate_cents=10000)
    get_success_data(_resolve(api, sc["claim_id"], {
        "decision": "APPROVE", "expected_deposit_version": sc["deposit_version"],
    }))
    profile = get_success_data(api.get_user(sc["renter_id"], _platform_headers()))
    assert profile["upheld_claim_count"] == 1, profile["upheld_claim_count"]
    assert profile["trust_score"] == 260, profile["trust_score"]


# --- Validation precedence: state (4) beats fiscal (13) (Difficulty) ---------

def test_state_beats_fiscal_award_exceeds_on_open_claim(api):
    """PRD §2.7: "State legality — the target resource is in a state from which the
    requested transition is defined, else ERR_INVALID_STATE (409)."
    PRD §2.7: "Award legality — a claim resolution award is within the claimed amount and,
    for a partial award, strictly inside its bounds, else ERR_INVALID_AWARD (422)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_claim_resolve
    """
    sc = setup_open_claim(api, claimed_amount_cents=30000, deposit_cents=50000)
    resp = _resolve(api, sc["claim_id"], {
        "decision": "PARTIAL", "approved_amount_cents": 99999,
        "expected_deposit_version": sc["deposit_version"],
    })
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_state_beats_fiscal_boundary_award_on_open_claim(api):
    """PRD §2.7: "State legality — the target resource is in a state from which the
    requested transition is defined, else ERR_INVALID_STATE (409)."
    PRD §2.7: "Award legality — a claim resolution award is within the claimed amount and,
    for a partial award, strictly inside its bounds, else ERR_INVALID_AWARD (422)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_claim_resolve
    """
    sc = setup_open_claim(api, claimed_amount_cents=30000, deposit_cents=50000)
    # approved_amount == claimed_amount is an out-of-bounds PARTIAL award (fiscal), but the
    # claim is still OPEN (state) — the state check must win.
    resp = _resolve(api, sc["claim_id"], {
        "decision": "PARTIAL", "approved_amount_cents": 30000,
        "expected_deposit_version": sc["deposit_version"],
    })
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --- Award legality (Corner/validations) -------------------------------------

def test_partial_award_exceeds_claim_rejected(api):
    """PRD §3.7: "The resolve payload supplies an approved_amount_cents that must be
    strictly greater than 0 and strictly less than claimed_amount_cents; a value outside
    those bounds is rejected with ERR_INVALID_AWARD."

    Design: Corner/validations/partial_award_exceeds_claim_rejected
    """
    sc = setup_claim_under_review(api, claimed_amount_cents=30000, deposit_cents=50000)
    resp = _resolve(api, sc["claim_id"], {
        "decision": "PARTIAL", "approved_amount_cents": 40000,
        "expected_deposit_version": sc["deposit_version"],
    })
    validate_error(resp, ApiErrorId.ERR_INVALID_AWARD.value)


# --- RBAC: only Platform resolves (Corner/rbac) ------------------------------

def test_renter_cannot_resolve_claim_forbidden(api):
    """PRD §2.1: "When a caller is authenticated but not permitted to perform the requested
    operation — either because their role is not authorized for it ... the request is
    rejected with ERR_FORBIDDEN."

    Design: Corner/rbac/renter_cannot_resolve_claim_forbidden
    """
    sc = setup_claim_under_review(api, claimed_amount_cents=20000, deposit_cents=50000)
    resp = api.resolve_claim(sc["claim_id"], {
        "decision": "APPROVE", "expected_deposit_version": sc["deposit_version"],
    }, make_renter_headers(sc["renter_id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# --- OCC on deposit version (Corner/cross_cutting) ---------------------------

def test_occ_stale_deposit_version_on_resolve_rejected(api):
    """PRD §2.6: "When the platform resolves a claim, it must submit expected_deposit_version
    carrying the version of the Deposit it last read. If another claim has already captured
    from that deposit in the meantime, the deposit's version will have advanced and the
    resolve is rejected with ERR_STALE_DEPOSIT_VERSION (HTTP 412) ..."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_deposit_version_on_resolve_rejected
    """
    sc = setup_claim_under_review(api, claimed_amount_cents=20000, deposit_cents=50000)
    resp = _resolve(api, sc["claim_id"], {
        "decision": "APPROVE", "expected_deposit_version": sc["deposit_version"] - 1,
    })
    validate_error(resp, ApiErrorId.ERR_STALE_DEPOSIT_VERSION.value)


# --- Compensating invariant: deposit money conserved (Difficulty) ------------

def _partial_capture_then_release(api, claimed, approved):
    sc = setup_claim_under_review(api, claimed_amount_cents=claimed, deposit_cents=50000)
    get_success_data(_resolve(api, sc["claim_id"], {
        "decision": "PARTIAL", "approved_amount_cents": approved,
        "expected_deposit_version": sc["deposit_version"],
    }))
    get_success_data(api.release_payout(sc["payout_id"], _platform_headers()))
    return sc, get_success_data(api.get_deposit(sc["booking_id"], sc["owner_headers"]))[0]


def test_deposit_buckets_after_partial_capture_and_release(api):
    """PRD §3.8: "Release also settles the deposit remainder: whatever is still in held_cents
    moves into released_cents and held_cents becomes 0, so the deposit ends RELEASED when
    nothing was ever captured, or CAPTURED with its remainder released when some funds were
    captured, always preserving the conservation invariant."

    Design: Difficulty/compensating_invariant/deposit_money_conserved_across_capture_and_release
    """
    sc, deposit = _partial_capture_then_release(api, claimed=40000, approved=15000)
    assert deposit["captured_cents"] == 15000, deposit["captured_cents"]
    assert deposit["released_cents"] == 35000, deposit["released_cents"]
    assert deposit["held_cents"] == 0, deposit["held_cents"]


def test_deposit_money_conserved_after_capture_and_release(api):
    """PRD §2.10: "Each security Deposit is a small ledger whose three balances — held_cents,
    captured_cents, and released_cents — always sum to original_amount_cents. This
    conservation invariant holds at every point in the deposit's life ..."

    Design: Difficulty/compensating_invariant/deposit_money_conserved_across_capture_and_release
    """
    sc, deposit = _partial_capture_then_release(api, claimed=40000, approved=15000)
    assert_deposit_conserved(deposit)
    total = deposit["held_cents"] + deposit["captured_cents"] + deposit["released_cents"]
    assert total == 50000, total
