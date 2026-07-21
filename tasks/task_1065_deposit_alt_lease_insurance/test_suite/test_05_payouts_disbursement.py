"""Payout disbursement, the segregation-of-duties gate, the 3-hop disbursement cascade, the
gross-vs-net coverage dual view, and the reversal compensating invariant (PRD §2.8, §2.9, §3.6)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID, ApiErrorId,
    setup_active_policy, file_claim, approve_claim, get_payout_for_claim,
    disburse_payout, reverse_payout,
    make_landlord_headers, make_claims_adjuster_headers,
)


def test_payout_transition_not_found(api):
    """PRD §2.5: "an unresolvable ... a payout yields `ERR_PAYOUT_NOT_FOUND` ... all at
    HTTP 404."

    Design: Corner/entities/payout_transition_not_found
    """
    res = api.payout_transition(NON_EXISTENT_UUID, {"action": "DISBURSE"}, make_claims_adjuster_headers("adjuster-900"))
    validate_error(res, ApiErrorId.ERR_PAYOUT_NOT_FOUND, expected_status=404)


def test_payout_disburse_cascades_policy_then_property_depth_3(api):
    """PRD §2.9: "Disbursing a payout is also this system's deepest cascade: a single
    disbursement action mutates the payout itself, then the policy that funds it, then the
    property that the underlying claim traces back to, and finally bubbles a state change up to
    the claim. Concretely, disbursing a `PENDING` payout (1) marks the payout `DISBURSED` and
    records who disbursed it and when; (2) recomputes the funding policy's net available
    coverage to reflect the newly-moved cash; (3) recomputes the property's
    `total_paid_claims_cents` (aggregated across every payout on every claim on every policy
    tracing back to that property, filtered to `DISBURSED` status) to include the new amount."

    Design: Difficulty/transitive_cascade/payout_disburse_cascades_policy_then_property_depth_3
    """
    ctx = setup_active_policy(coverage_limit_cents=500000)
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"],
                        line_items=[{"description": "Broken window", "amount_cents": 100000}])
    claim = approve_claim(claim["id"], "adjuster-001")
    payout = get_payout_for_claim(claim["id"], ctx["landlord"]["id"])
    payout = disburse_payout(payout["id"], "adjuster-002")
    assert payout["status"] == "DISBURSED"

    policy_after = validate_success(api.get_policy(ctx["policy"]["id"], make_landlord_headers(ctx["landlord"]["id"])), 200)
    assert policy_after["net_available_coverage_cents"] == 405000
    property_after = validate_success(api.get_property(ctx["property"]["id"], make_landlord_headers(ctx["landlord"]["id"])), 200)
    assert property_after["total_paid_claims_cents"] == 95000


def test_payout_disburse_cascade_also_closes_the_claim(api):
    """PRD §2.9: "...and finally bubbles a state change up to the claim." "(4) closes the
    underlying claim from `APPROVED` to `CLOSED` as a system-driven bubble-up once its payout has
    actually landed."

    Design: Difficulty/transitive_cascade/payout_disburse_cascades_policy_then_property_depth_3
    """
    ctx = setup_active_policy(coverage_limit_cents=500000)
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"],
                        line_items=[{"description": "Broken window", "amount_cents": 100000}])
    claim = approve_claim(claim["id"], "adjuster-001")
    payout = get_payout_for_claim(claim["id"], ctx["landlord"]["id"])
    disburse_payout(payout["id"], "adjuster-002")

    claim_after = validate_success(api.get_claim(claim["id"], make_landlord_headers(ctx["landlord"]["id"])), 200)
    assert claim_after["status"] == "CLOSED"


def test_policy_available_coverage_gross_vs_net_diverge_on_pending_payout(api):
    """PRD §2.8: "The gross available coverage is a forward-looking reservation: it subtracts
    every claim that has reached `APPROVED` or `CLOSED` from the policy's coverage limit, whether
    or not that claim's payout has actually been paid out yet. The net available coverage is a
    cash-actually-moved view: it subtracts only the payouts that have actually reached
    `DISBURSED` status. These two figures necessarily diverge whenever a claim has been approved
    but its payout is still sitting in `PENDING` — gross has already reserved the exposure, net
    has not yet felt it."

    Design: Difficulty/dual_variant_calc/policy_available_coverage_gross_vs_net_diverge_on_pending_payout
    """
    ctx = setup_active_policy(coverage_limit_cents=500000)
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"],
                        line_items=[{"description": "Broken window", "amount_cents": 100000}])
    approve_claim(claim["id"], "adjuster-001")  # payout stays PENDING, not disbursed

    policy = validate_success(api.get_policy(ctx["policy"]["id"], make_landlord_headers(ctx["landlord"]["id"])), 200)
    assert policy["gross_available_coverage_cents"] == 405000
    assert policy["net_available_coverage_cents"] == 500000
    assert policy["gross_available_coverage_cents"] != policy["net_available_coverage_cents"]


def test_policy_available_coverage_gross_and_net_converge_after_disbursement(api):
    """PRD §2.8: "Both are recomputed from scratch off the underlying claim and payout records,
    never incrementally patched, whenever a claim is approved, whenever a payout is disbursed or
    reversed..." Once the payout actually disburses, net catches up to gross for that claim.

    Design: Difficulty/dual_variant_calc/policy_available_coverage_gross_vs_net_diverge_on_pending_payout
    """
    ctx = setup_active_policy(coverage_limit_cents=500000)
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"],
                        line_items=[{"description": "Broken window", "amount_cents": 100000}])
    claim = approve_claim(claim["id"], "adjuster-001")
    payout = get_payout_for_claim(claim["id"], ctx["landlord"]["id"])
    disburse_payout(payout["id"], "adjuster-002")

    policy = validate_success(api.get_policy(ctx["policy"]["id"], make_landlord_headers(ctx["landlord"]["id"])), 200)
    assert policy["gross_available_coverage_cents"] == 405000
    assert policy["net_available_coverage_cents"] == 405000


def test_sod_violation_same_adjuster_cannot_disburse_own_decision(api):
    """PRD §2.9: "The `ClaimsAdjuster` identity recorded when a claim is approved or denied is
    compared, at disbursement time, against the `ClaimsAdjuster` identity attempting to disburse
    that claim's payout; if the two `X-User-ID` values match, the disbursement is rejected with
    `ERR_SOD_VIOLATION` (HTTP 403) regardless of how correct the underlying payout amount is."

    Design: Corner/validations/sod_violation_same_adjuster_cannot_disburse_own_decision
    """
    ctx = setup_active_policy()
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"],
                        line_items=[{"description": "Fence repair", "amount_cents": 60000}])
    claim = approve_claim(claim["id"], "adjuster-601")
    payout = get_payout_for_claim(claim["id"], ctx["landlord"]["id"])

    res = api.payout_transition(payout["id"], {"action": "DISBURSE"}, make_claims_adjuster_headers("adjuster-601"))
    validate_error(res, ApiErrorId.ERR_SOD_VIOLATION, expected_status=403)
    payouts, _meta = validate_paginated(api.list_claim_payouts(claim["id"], make_landlord_headers(ctx["landlord"]["id"])))
    assert payouts[0]["status"] == "PENDING"


def test_payout_disburse_reverse_conserves_policy_net_available_coverage(api):
    """PRD §2.8: "A conserved-quantity invariant ties the policy's coverage limit to its
    net-available figure at all times: the coverage limit always equals the net available
    coverage plus the sum of every non-reversed, disbursed payout's amount for that policy.
    Reversing a payout is the compensating action that restores this invariant — it recomputes
    `net_available_coverage_cents` back to its pre-disbursement value..."

    Design: Difficulty/compensating_invariant/payout_disburse_reverse_conserves_policy_net_available_coverage
    """
    ctx = setup_active_policy(coverage_limit_cents=500000)
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"],
                        line_items=[{"description": "Broken window", "amount_cents": 100000}])
    claim = approve_claim(claim["id"], "adjuster-001")
    payout = get_payout_for_claim(claim["id"], ctx["landlord"]["id"])
    disburse_payout(payout["id"], "adjuster-002")
    disbursed_policy = validate_success(api.get_policy(ctx["policy"]["id"], make_landlord_headers(ctx["landlord"]["id"])), 200)
    assert disbursed_policy["net_available_coverage_cents"] == 405000

    reversed_payout = reverse_payout(payout["id"], "Fraud investigation confirmed no damage occurred.")
    assert reversed_payout["status"] == "REVERSED"
    restored_policy = validate_success(api.get_policy(ctx["policy"]["id"], make_landlord_headers(ctx["landlord"]["id"])), 200)
    assert restored_policy["net_available_coverage_cents"] == 500000


def test_payout_reverse_does_not_affect_gross_coverage_or_reopen_claim(api):
    """PRD §2.8: "The gross available coverage is a forward-looking reservation: it subtracts
    every claim that has reached `APPROVED` or `CLOSED` from the policy's coverage limit, whether
    or not that claim's payout has actually been paid out yet." PRD §3.6: "Reversal does not
    reopen the underlying claim, which remains `CLOSED`."

    Design: Difficulty/compensating_invariant/payout_disburse_reverse_conserves_policy_net_available_coverage
    """
    ctx = setup_active_policy(coverage_limit_cents=500000)
    claim = file_claim(ctx["policy"]["id"], ctx["landlord"]["id"],
                        line_items=[{"description": "Broken window", "amount_cents": 100000}])
    claim = approve_claim(claim["id"], "adjuster-001")
    payout = get_payout_for_claim(claim["id"], ctx["landlord"]["id"])
    disburse_payout(payout["id"], "adjuster-002")
    reverse_payout(payout["id"])

    policy_after = validate_success(api.get_policy(ctx["policy"]["id"], make_landlord_headers(ctx["landlord"]["id"])), 200)
    assert policy_after["gross_available_coverage_cents"] == 405000
    claim_after = validate_success(api.get_claim(claim["id"], make_landlord_headers(ctx["landlord"]["id"])), 200)
    assert claim_after["status"] == "CLOSED"
