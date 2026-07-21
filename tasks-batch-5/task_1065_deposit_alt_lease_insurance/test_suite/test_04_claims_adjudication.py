"""Claims intake, the UNDER_REVIEW/NEEDS_INFO revision loop, and claim-payout adjudication
(PRD §3.5)."""
from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID, ApiErrorId,
    setup_active_policy,
    file_claim, approve_claim, deny_claim, request_claim_info, submit_claim_info,
    disburse_payout, get_payout_for_claim,
    make_landlord_headers, make_claims_adjuster_headers,
)


def test_claim_get_not_found(api, compliance_officer_headers):
    """PRD §2.5: "an unresolvable ... a claim yields `ERR_CLAIM_NOT_FOUND` ... all at HTTP 404."

    Design: Corner/entities/claim_get_not_found
    """
    res = api.get_claim(NON_EXISTENT_UUID, compliance_officer_headers)
    validate_error(res, ApiErrorId.ERR_CLAIM_NOT_FOUND, expected_status=404)


def test_claim_denied_terminal_lockdown(api):
    """PRD §3.5: "`DENIED` and `CLOSED` are the claim's only terminal states..." PRD §3.5:
    "From `UNDER_REVIEW`, a `ClaimsAdjuster` can request more information, which moves the claim
    to `NEEDS_INFO`..." — REQUEST_INFO is only declared from `UNDER_REVIEW`.

    Design: Corner/state_machines/claim_denied_terminal_lockdown
    """
    ctx = setup_active_policy()
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"],
                        line_items=[{"description": "Cracked tile", "amount_cents": 20000}])
    claim = deny_claim(claim["id"], "adjuster-201")
    assert claim["status"] == "DENIED"

    res = api.claim_info_transition(claim["id"], {"action": "REQUEST_INFO"}, make_claims_adjuster_headers("adjuster-201"))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_claim(claim["id"], make_landlord_headers(ctx["landlord"]["id"])), 200)
    assert after["status"] == "DENIED"


def test_claim_needs_info_revision_loop_returns_to_under_review(api):
    """PRD §3.5: "The landlord then submits the requested information back — this is a revision
    loop, not a one-way branch — which returns the claim to `UNDER_REVIEW`, appending any newly
    supplied `line_items` to the existing array and recomputing `total_claimed_amount_cents` from
    the combined set."

    Design: Difficulty/non_linear_state_machine/claim_needs_info_revision_loop_returns_to_under_review
    """
    ctx = setup_active_policy()
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"],
                        line_items=[{"description": "Water damage", "amount_cents": 50000}])
    claim = request_claim_info(claim["id"], "adjuster-001", "Please provide contractor estimate.")
    assert claim["status"] == "NEEDS_INFO"

    claim = submit_claim_info(claim["id"], ctx["landlord"]["id"],
                               line_items=[{"description": "Mold remediation", "amount_cents": 20000}])
    assert claim["status"] == "UNDER_REVIEW"
    assert claim["total_claimed_amount_cents"] == 70000


def test_claim_needs_info_revision_loop_cycles_a_second_time(api):
    """PRD §3.5: "A claim can cycle through `UNDER_REVIEW` and `NEEDS_INFO` as many times as
    needed before a decision is reached."

    Design: Difficulty/non_linear_state_machine/claim_needs_info_revision_loop_returns_to_under_review
    """
    ctx = setup_active_policy()
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"],
                        line_items=[{"description": "Water damage", "amount_cents": 50000}])
    claim = request_claim_info(claim["id"], "adjuster-001", "Please provide contractor estimate.")
    claim = submit_claim_info(claim["id"], ctx["landlord"]["id"],
                               line_items=[{"description": "Mold remediation", "amount_cents": 20000}])
    assert claim["total_claimed_amount_cents"] == 70000

    claim = request_claim_info(claim["id"], "adjuster-001", "Please provide a second quote.")
    assert claim["status"] == "NEEDS_INFO"
    claim = submit_claim_info(claim["id"], ctx["landlord"]["id"],
                               line_items=[{"description": "Drywall repair", "amount_cents": 10000}])
    assert claim["status"] == "UNDER_REVIEW"
    assert claim["total_claimed_amount_cents"] == 80000


def test_claim_approval_rejects_zero_line_items(api):
    """PRD §3.5: "Approving a claim (`UNDER_REVIEW` to `APPROVED`) is gated by three checks, and
    they are evaluated in a fixed order: first, `line_items` must be non-empty, or the attempt is
    rejected with `ERR_CLAIM_HAS_NO_LINE_ITEMS` (HTTP 422) — an empty array blocks approval even
    if it did not block filing..."

    Design: Difficulty/boundary_precision_check/claim_approval_rejects_zero_line_items
    """
    ctx = setup_active_policy()
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"], line_items=[])
    assert claim["total_claimed_amount_cents"] == 0

    res = api.decide_claim(claim["id"], {"action": "APPROVE"}, make_claims_adjuster_headers("adjuster-001"))
    validate_error(res, ApiErrorId.ERR_CLAIM_HAS_NO_LINE_ITEMS, expected_status=422)
    after = validate_success(api.get_claim(claim["id"], make_landlord_headers(ctx["landlord"]["id"])), 200)
    assert after["status"] == "UNDER_REVIEW"


def test_claim_approval_succeeds_with_one_minimal_line_item(api):
    """PRD §3.5: "first, `line_items` must be non-empty, or the attempt is rejected with
    `ERR_CLAIM_HAS_NO_LINE_ITEMS`..." — a single non-empty line item satisfies this gate.

    Design: Difficulty/boundary_precision_check/claim_approval_rejects_zero_line_items
    """
    ctx = setup_active_policy()
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"],
                        line_items=[{"description": "Minor scuff", "amount_cents": 6000}])
    claim = approve_claim(claim["id"], "adjuster-001")
    assert claim["status"] == "APPROVED"
    assert claim["deductible_cents"] == 5000
    assert claim["approved_amount_cents"] == 1000


def test_claim_payout_tiered_deductible_pinned_evaluation_order(api):
    """PRD §3.5: "Step two decides which deductible tier actually applies, and it is decided
    from that step-one provisional figure specifically — never from the final amount —
    comparing it against a high-tier threshold of 200,000 cents ($2,000): at or above that
    threshold, the deductible is 1.5 times the flat deductible (7,500 cents); below it, the
    deductible stays at the flat 5,000 cents."

    Design: Difficulty/combinatorial_formula/claim_payout_tiered_deductible_pinned_evaluation_order
    """
    ctx = setup_active_policy(coverage_limit_cents=1000000)
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"],
                        line_items=[{"description": "Fire damage to kitchen", "amount_cents": 300000}])
    claim = approve_claim(claim["id"], "adjuster-001")
    assert claim["deductible_cents"] == 7500
    assert claim["approved_amount_cents"] == 292500


def test_claim_payout_tier_decided_from_gross_capped_provisional_not_naive_claimed(api):
    """PRD §3.5: "Step two decides which deductible tier actually applies, and it is decided
    from that step-one provisional figure specifically — never from the final amount..." PRD
    §3.5: "Step one computes a provisional payout: take the smaller of the total claimed amount
    and the policy's gross available coverage, then subtract a flat deductible of 5,000 cents
    ($50), floored at zero."

    Design: Difficulty/combinatorial_formula/claim_payout_tiered_deductible_pinned_evaluation_order
    """
    ctx = setup_active_policy(coverage_limit_cents=202000)
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"],
                        line_items=[{"description": "Storm damage", "amount_cents": 205000}])
    claim = approve_claim(claim["id"], "adjuster-001")
    # Naive (uncapped) claimed-minus-deductible = 205000-5000 = 200000 >= threshold, which would
    # WRONGLY select the HIGH tier if the tier were decided from the final amount. The
    # gross-capped provisional (202000-5000=197000) stays below threshold -> FLAT deductible.
    assert claim["deductible_cents"] == 5000
    assert claim["approved_amount_cents"] == 200000


def test_claim_payout_flat_deductible_when_provisional_below_high_tier_threshold(api):
    """PRD §3.5: "below it, the deductible stays at the flat 5,000 cents."

    Design: Corner/calculations/claim_payout_flat_deductible_when_provisional_below_high_tier_threshold
    """
    ctx = setup_active_policy(coverage_limit_cents=500000)
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"],
                        line_items=[{"description": "Chipped counter", "amount_cents": 50000}])
    claim = approve_claim(claim["id"], "adjuster-401")
    assert claim["deductible_cents"] == 5000
    assert claim["approved_amount_cents"] == 45000


def test_coverage_limit_exceeded_blocks_claim_approval(api):
    """PRD §3.5: "third, the payout amount the claim would generate must not exceed the
    policy's current gross available coverage, or the attempt is rejected with
    `ERR_COVERAGE_LIMIT_EXCEEDED` (HTTP 422)."

    Design: Corner/validations/coverage_limit_exceeded_blocks_claim_approval
    """
    ctx = setup_active_policy(coverage_limit_cents=50000)
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"],
                        line_items=[{"description": "Total kitchen remodel needed", "amount_cents": 200000}])
    res = api.decide_claim(claim["id"], {"action": "APPROVE"}, make_claims_adjuster_headers("adjuster-501"))
    validate_error(res, ApiErrorId.ERR_COVERAGE_LIMIT_EXCEEDED, expected_status=422)
    after = validate_success(api.get_claim(claim["id"], make_landlord_headers(ctx["landlord"]["id"])), 200)
    assert after["status"] == "UNDER_REVIEW"


def test_claim_decide_state_beats_fiscal_on_already_denied_claim(api):
    """PRD §2.5: "The overall validation order applied to every request, regardless of
    endpoint, is: ...then existence of every referenced resource...then the state or
    transition-eligibility check for the target resource (`ERR_INVALID_STATE`), and only after
    all of that do the endpoint's own business-rule checks run in the order documented in the
    relevant §3 subsection."

    Design: Difficulty/priority_pair_validation_conflict/claim_decide_state_beats_fiscal_on_already_denied_claim
    """
    ctx = setup_active_policy(coverage_limit_cents=50000)
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"],
                        line_items=[{"description": "Roof damage", "amount_cents": 100000}])
    claim = deny_claim(claim["id"], "adjuster-001")
    assert claim["status"] == "DENIED"

    res = api.decide_claim(claim["id"], {"action": "APPROVE"}, make_claims_adjuster_headers("adjuster-001"))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_claim(claim["id"], make_landlord_headers(ctx["landlord"]["id"])), 200)
    assert after["status"] == "DENIED"


def test_claim_decide_state_check_wins_on_already_closed_claim(api):
    """PRD §2.5: "...then the state or transition-eligibility check for the target resource
    (`ERR_INVALID_STATE`), and only after all of that do the endpoint's own business-rule checks
    run..." PRD §3.6: "triggers the full three-hop cascade into the policy's net available
    coverage, the property's paid-claims total, and the claim's closure..."

    Design: Difficulty/priority_pair_validation_conflict/claim_decide_state_beats_fiscal_on_already_denied_claim
    """
    ctx = setup_active_policy(coverage_limit_cents=500000)
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"],
                        line_items=[{"description": "Fence repair", "amount_cents": 60000}])
    claim = approve_claim(claim["id"], "adjuster-601")
    payout = get_payout_for_claim(claim["id"], ctx["landlord"]["id"])
    disburse_payout(payout["id"], "adjuster-602")
    closed = validate_success(api.get_claim(claim["id"], make_landlord_headers(ctx["landlord"]["id"])), 200)
    assert closed["status"] == "CLOSED"

    res = api.decide_claim(claim["id"], {"action": "APPROVE"}, make_claims_adjuster_headers("adjuster-601"))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_claim(claim["id"], make_landlord_headers(ctx["landlord"]["id"])), 200)
    assert after["status"] == "CLOSED"


def test_landlord_cannot_perform_claims_adjuster_exclusive_decide(api):
    """PRD §4 endpoint table: `POST /claims/{id}/decide` is authorized only for
    `ClaimsAdjuster`. PRD §2.1: "A request from an authenticated caller whose role is not
    permitted to perform the specific operation being attempted is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/landlord_cannot_perform_claims_adjuster_exclusive_decide
    """
    ctx = setup_active_policy()
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"],
                        line_items=[{"description": "Gutter damage", "amount_cents": 30000}])
    res = api.decide_claim(claim["id"], {"action": "APPROVE"}, make_landlord_headers(ctx["landlord"]["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
    after = validate_success(api.get_claim(claim["id"], make_landlord_headers(ctx["landlord"]["id"])), 200)
    assert after["status"] == "UNDER_REVIEW"
