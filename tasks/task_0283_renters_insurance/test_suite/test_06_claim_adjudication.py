"""Claim adjudication loop: review, approve/ledger, deny, appeal, reverse, pay."""
from test_helpers import (
    add_claim_item,
    api_client,
    file_pp_claim,
    make_policyholder_headers,
    set_clock,
    setup_active_policy,
    setup_approved_claim,
    setup_claim_under_review,
    setup_lapsed_policy,
    validate_error,
    validate_success,
    TEST_USERS,
)

UW = TEST_USERS["underwriter_headers"]
ADJ = TEST_USERS["adjuster_headers"]


# ---------------------------------------------------------------------------
# Queue A: transitive_cascade — approve debits ledger then exhausts coverage
# ---------------------------------------------------------------------------
def test_approve_debits_then_exhausts_coverage(api):
    """PRD §3.8: "On approval the claim settlement re-runs in final mode to
    recompute `settlement_cents`, and the settlement ledger debits each
    referenced coverage line by its waterfall share per §3.6, recomputing each
    line's `remaining_limit_cents` and flipping any fully consumed line to
    `EXHAUSTED`."

    Design: Difficulty/transitive_cascade/claim_approve_debits_then_exhausts_coverage_depth2
    """
    _ph, policy, lines, claim, _items = setup_claim_under_review(
        pp_limit=100000, deductible_cents=0, pp_valuation_method="RCV",
        items=[{"replacement_cost_cents": 125000, "age_months": 0, "useful_life_months": 60}],
        email="exh@x.com",
    )
    approved = validate_success(api.approve_claim(claim["id"], ADJ), 200)
    assert approved["settlement_cents"] == 100000, approved["settlement_cents"]
    cl = validate_success(api.list_coverage_lines(policy["id"], UW), 200)
    pp = next(l for l in cl if l["coverage_type"] == "PERSONAL_PROPERTY")
    assert pp["settled_cents"] == 100000, pp["settled_cents"]
    assert pp["remaining_limit_cents"] == 0, pp["remaining_limit_cents"]
    assert pp["status"] == "EXHAUSTED", pp["status"]


def test_approve_partial_debit_leaves_line_open(api):
    """PRD §3.6: "On approval, that share is added to the line's `settled_cents`;
    on a reversal, the prior share is subtracted back out."
    PRD §3.6: "After each adjustment the line's `remaining_limit_cents` is
    recomputed as `limit_cents` minus `settled_cents`, and the line is marked
    `EXHAUSTED` if its remaining limit is zero or `OPEN` if it is greater than
    zero."

    Design: Difficulty/transitive_cascade/claim_approve_debits_then_exhausts_coverage_depth2
    """
    _ph, policy, lines, claim, _items = setup_claim_under_review(
        pp_limit=3000000, deductible_cents=25000, pp_valuation_method="RCV",
        items=[{"replacement_cost_cents": 120000, "age_months": 0, "useful_life_months": 60}],
        email="exh2@x.com",
    )
    validate_success(api.approve_claim(claim["id"], ADJ), 200)
    cl = validate_success(api.list_coverage_lines(policy["id"], UW), 200)
    pp = next(l for l in cl if l["coverage_type"] == "PERSONAL_PROPERTY")
    assert pp["settled_cents"] == 95000, pp["settled_cents"]
    assert pp["remaining_limit_cents"] == 2905000, pp["remaining_limit_cents"]
    assert pp["status"] == "OPEN", pp["status"]


# ---------------------------------------------------------------------------
# Queue A: compensating_invariant — reverse-approval restores coverage exactly
# ---------------------------------------------------------------------------
def test_reverse_approval_restores_coverage_limit_exactly(api):
    """PRD §3.8: "reversing an approval advances `APPROVED → DENIED`, requires a
    `denial_reason` (else `ERR_DENIAL_REASON_REQUIRED`), and as a compensation
    credits back each referenced coverage line by the share it was previously
    debited — recomputing each line's `remaining_limit_cents` and restoring a
    line to `OPEN` whenever its remaining limit becomes greater than zero — then
    sets `settlement_cents` to zero."

    Design: Difficulty/compensating_invariant/reverse_approval_restores_coverage_limit_exactly
    """
    _ph, policy, lines, claim, _items = setup_approved_claim(
        pp_limit=3000000, deductible_cents=25000,
        items=[{"replacement_cost_cents": 120000, "age_months": 0, "useful_life_months": 60}],
        email="ci1@x.com",
    )
    out = validate_success(
        api.reverse_approval(claim["id"], {"denial_reason": "fraud re-investigation"}, ADJ),
        200,
    )
    assert out["settlement_cents"] == 0, out["settlement_cents"]
    cl = validate_success(api.list_coverage_lines(policy["id"], UW), 200)
    pp = next(l for l in cl if l["coverage_type"] == "PERSONAL_PROPERTY")
    assert pp["settled_cents"] == 0, pp["settled_cents"]
    assert pp["remaining_limit_cents"] == 3000000, pp["remaining_limit_cents"]
    assert pp["status"] == "OPEN", pp["status"]


def test_reverse_approval_moves_claim_to_denied(api):
    """PRD §3.8: "reversing an approval advances `APPROVED → DENIED`, requires a
    `denial_reason` (else `ERR_DENIAL_REASON_REQUIRED`)".

    Design: Difficulty/compensating_invariant/reverse_approval_restores_coverage_limit_exactly
    """
    _ph, _policy, _lines, claim, _items = setup_approved_claim(
        pp_limit=3000000, deductible_cents=25000,
        items=[{"replacement_cost_cents": 120000, "age_months": 0, "useful_life_months": 60}],
        email="ci1b@x.com",
    )
    out = validate_success(
        api.reverse_approval(claim["id"], {"denial_reason": "audit"}, ADJ), 200
    )
    assert out["status"] == "DENIED", out["status"]


# ---------------------------------------------------------------------------
# Queue A: non_linear_state_machine — deny -> appeal -> approve fork-join
# ---------------------------------------------------------------------------
def test_claim_deny_then_appeal_then_approve(api):
    """PRD §3.8: "Appealing advances `DENIED → UNDER_REVIEW`."
    PRD §3.8: "A successful appeal increments `appeal_count` by one, clears the
    `denial_reason`, and re-runs the claim settlement in provisional mode."
    PRD §3.8: "Approving advances `UNDER_REVIEW → APPROVED`."

    Design: Difficulty/non_linear_state_machine/claim_branch_deny_then_appeal_then_approve_forkjoin
    """
    _ph, _policy, _lines, claim, _items = setup_claim_under_review(
        pp_limit=3000000, deductible_cents=25000, pp_valuation_method="RCV",
        items=[{"replacement_cost_cents": 120000, "age_months": 0, "useful_life_months": 60}],
        email="brn@x.com",
    )
    validate_success(api.deny_claim(claim["id"], {"denial_reason": "insufficient documentation"}, ADJ), 200)
    appealed = validate_success(api.appeal_claim(claim["id"], ADJ), 200)
    assert appealed["appeal_count"] == 1, appealed["appeal_count"]
    approved = validate_success(api.approve_claim(claim["id"], ADJ), 200)
    assert approved["status"] == "APPROVED", approved["status"]
    assert approved["settlement_cents"] == 95000, approved["settlement_cents"]


def test_deny_zeroes_settlement_without_debit(api):
    """PRD §3.8: "Denying instead advances `UNDER_REVIEW → DENIED`; it requires
    a `denial_reason` (else `ERR_DENIAL_REASON_REQUIRED`) and sets
    `settlement_cents` to zero with no coverage-line debit."

    Design: Difficulty/non_linear_state_machine/claim_branch_deny_then_appeal_then_approve_forkjoin
    """
    _ph, policy, _lines, claim, _items = setup_claim_under_review(
        pp_limit=3000000, deductible_cents=25000, pp_valuation_method="RCV",
        items=[{"replacement_cost_cents": 120000, "age_months": 0, "useful_life_months": 60}],
        email="brn2@x.com",
    )
    out = validate_success(api.deny_claim(claim["id"], {"denial_reason": "no proof"}, ADJ), 200)
    assert out["status"] == "DENIED", out["status"]
    assert out["settlement_cents"] == 0, out["settlement_cents"]
    cl = validate_success(api.list_coverage_lines(policy["id"], UW), 200)
    pp = next(l for l in cl if l["coverage_type"] == "PERSONAL_PROPERTY")
    assert pp["settled_cents"] == 0, pp["settled_cents"]


# ---------------------------------------------------------------------------
# Queue A: cross_entity_state_dependency — review requires active policy
# ---------------------------------------------------------------------------
def test_claim_review_requires_policy_active(api):
    """PRD §3.8: "Starting review advances a claim `FILED → UNDER_REVIEW`. It
    requires the owning policy to be `ACTIVE` (else `ERR_POLICY_NOT_ACTIVE`)".

    Design: Difficulty/cross_entity_state_dependency/claim_review_requires_policy_active
    """
    s = setup_lapsed_policy(email="cx1@x.com", add_filed_claim=True)
    # The claim was suspended by the lapse; starting review on a non-ACTIVE
    # policy is rejected with the cross-entity policy-state error.
    resp = api.start_review(s["claim"]["id"], ADJ)
    validate_error(resp, "ERR_POLICY_NOT_ACTIVE", 409)


def test_claim_pay_requires_policy_active(api):
    """PRD §3.8: "The final forward move is payment: paying a claim advances
    `APPROVED → SETTLED` and requires the owning policy to be `ACTIVE` (else
    `ERR_POLICY_NOT_ACTIVE`)".

    Design: Difficulty/cross_entity_state_dependency/claim_review_requires_policy_active
    """
    set_clock("2026-01-01T00:00:00Z")
    _ph, policy, _lines, claim, _items = setup_approved_claim(
        pp_limit=3000000, deductible_cents=25000,
        items=[{"replacement_cost_cents": 120000, "age_months": 0, "useful_life_months": 60}],
        email="cx1b@x.com",
    )
    # Lapse the policy out from under the APPROVED claim (clock past due+14
    # grace but before expiry, with the issue invoice unpaid), then attempt pay.
    set_clock("2026-02-01T00:00:00Z")
    lapsed = validate_success(api.process_billing(policy["id"], UW), 200)
    assert lapsed["status"] == "LAPSED", lapsed["status"]
    resp = api.pay_claim(claim["id"], TEST_USERS["adjuster_headers_2"])
    validate_error(resp, "ERR_POLICY_NOT_ACTIVE", 409)


# ---------------------------------------------------------------------------
# Queue B: adjudication validations
# ---------------------------------------------------------------------------
def test_deny_without_reason_rejected(api):
    """PRD §3.8: "Denying instead advances `UNDER_REVIEW → DENIED`; it requires
    a `denial_reason` (else `ERR_DENIAL_REASON_REQUIRED`)".

    Design: Corner/validations/deny_without_reason_rejected
    """
    _ph, _policy, _lines, claim, _items = setup_claim_under_review(email="v4@x.com")
    validate_error(api.deny_claim(claim["id"], {}, ADJ), "ERR_DENIAL_REASON_REQUIRED", 422)


def test_start_review_empty_claim_rejected(api):
    """PRD §3.8: "It requires the owning policy to be `ACTIVE` (else
    `ERR_POLICY_NOT_ACTIVE`) and the claim to have at least one claim item (else
    `ERR_CLAIM_EMPTY`)."

    Design: Corner/validations/start_review_empty_claim_rejected
    """
    _ph, policy, _lines, _inv = setup_active_policy(email="v5@x.com")
    claim = file_pp_claim(policy["id"], _ph["id"])
    validate_error(api.start_review(claim["id"], ADJ), "ERR_CLAIM_EMPTY", 422)


def test_appeal_limit_reached_after_two_appeals(api):
    """PRD §3.8: "requires that `appeal_count` be below the maximum of two
    appeals (else `ERR_APPEAL_LIMIT_REACHED`)."

    Design: Corner/state_machines/appeal_limit_reached_after_two_appeals
    """
    _ph, _policy, _lines, claim, _items = setup_claim_under_review(
        items=[{"replacement_cost_cents": 120000, "age_months": 0, "useful_life_months": 60}],
        email="s6@x.com",
    )
    cid = claim["id"]
    validate_success(api.deny_claim(cid, {"denial_reason": "r1"}, ADJ), 200)
    validate_success(api.appeal_claim(cid, ADJ), 200)   # appeal_count 1
    validate_success(api.deny_claim(cid, {"denial_reason": "r2"}, ADJ), 200)
    validate_success(api.appeal_claim(cid, ADJ), 200)   # appeal_count 2
    validate_success(api.deny_claim(cid, {"denial_reason": "r3"}, ADJ), 200)
    validate_error(api.appeal_claim(cid, ADJ), "ERR_APPEAL_LIMIT_REACHED", 409)


def test_terminal_settled_claim_cannot_be_paid_again(api):
    """PRD §3.8: "any transition requested from a state where it is not defined
    is rejected with `ERR_INVALID_STATE`."
    PRD §3.8: "paying a claim advances `APPROVED → SETTLED`".

    Design: Corner/state_machines/terminal_settled_claim_cannot_be_paid_again
    """
    _ph, _policy, _lines, claim, _items = setup_approved_claim(
        pp_limit=3000000, deductible_cents=25000,
        items=[{"replacement_cost_cents": 120000, "age_months": 0, "useful_life_months": 60}],
        email="s5@x.com",
    )
    # pay once (different adjuster id than the reviewer to satisfy SoD), then
    # attempt a second pay against the terminal SETTLED claim.
    paid = validate_success(api.pay_claim(claim["id"], TEST_USERS["adjuster_headers_2"]), 200)
    assert paid["status"] == "SETTLED", paid["status"]
    validate_error(
        api.pay_claim(claim["id"], TEST_USERS["adjuster_headers_2"]),
        "ERR_INVALID_STATE", 409,
    )


# ---------------------------------------------------------------------------
# Queue B: RBAC peer-role separation on the claim path
# ---------------------------------------------------------------------------
def test_underwriter_cannot_approve_claim(api):
    """PRD §2.1: "The `ClaimsAdjuster` is a claims operator who starts review on
    a claim, approves, denies, appeals, reverses, and pays it."
    PRD §2.1: "When an authenticated role is not permitted to perform the
    requested operation, the request is rejected with `ERR_FORBIDDEN`."

    Design: Corner/rbac/underwriter_cannot_approve_claim
    """
    _ph, _policy, _lines, claim, _items = setup_claim_under_review(
        items=[{"replacement_cost_cents": 120000}], email="rb2@x.com"
    )
    validate_error(api.approve_claim(claim["id"], UW), "ERR_FORBIDDEN", 403)
