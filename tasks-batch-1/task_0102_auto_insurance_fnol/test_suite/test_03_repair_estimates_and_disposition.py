"""Repair estimates, the disposition fork, and segregation of duties.

Covers: estimate submission/supersession cascade and the single-SUBMITTED
invariant, repair-path settlement math (incl. dual-variant divergence and the
limit cap), the REPAIR branch fork, segregation of duties and senior-tier guards,
and the priority-pair {state vs business_constraint} conflict on REPAIR disposition.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_policy, add_collision_coverage, create_adjuster, file_claim,
    verify_claim, assign_claim, submit_estimate, author_total_loss_evaluation,
    setup_claim_under_review, setup_claim_with_submitted_estimate,
    setup_repair_approved_claim, setup_total_loss_ready, decide_total_loss,
    make_claims_adjuster_headers, make_total_loss_adjuster_headers,
    TEST_USERS,
)

SUP = TEST_USERS["supervisor_headers"]


# ─── Estimate submission / supersession (transitive_cascade + compensating_invariant) ───

def test_estimate_submit_cascade_supersedes_prior(api):
    """PRD §3.4: "an estimate's submission supersedes its predecessor: if another
    repair estimate for the same claim is already `SUBMITTED`, that earlier estimate
    is transitioned `SUBMITTED → SUPERSEDED` as a side effect of the new submission".

    Design: Difficulty/transitive_cascade/estimate_submit_cascade_depth2_supersedes_prior
    """
    ctx = setup_claim_under_review()
    claim_id = ctx["claim"]["id"]
    adj_id = ctx["adjuster"]["id"]
    headers = make_claims_adjuster_headers(adj_id)

    est1 = validate_success(api.create_repair_estimate(
        {"claim_id": claim_id, "lines": [{"description": "v1", "labor_cents": 300_000, "parts_cents": 0}]},
        headers), 201)
    validate_success(api.submit_repair_estimate(est1["id"], headers), 200)
    est2 = validate_success(api.create_repair_estimate(
        {"claim_id": claim_id, "lines": [{"description": "v2", "labor_cents": 500_000, "parts_cents": 0}]},
        headers), 201)

    submitted2 = validate_success(api.submit_repair_estimate(est2["id"], headers), 200)
    assert submitted2["status"] == "SUBMITTED"
    est1_after = validate_success(api.get_repair_estimate(est1["id"], headers), 200)
    assert est1_after["status"] == "SUPERSEDED"


def test_estimate_submit_makes_new_estimate_active(api):
    """PRD §3.4: "Submitting an estimate advances it `DRAFT → SUBMITTED` and makes it
    the active estimate used for disposition." PRD §3.4: "Submission recomputes
    `repair_total_cents`." The newly submitted estimate (repair_total 500000) becomes
    the active SUBMITTED one while the predecessor is SUPERSEDED.

    Design: Difficulty/transitive_cascade/estimate_submit_cascade_depth2_supersedes_prior
    """
    ctx = setup_claim_under_review()
    claim_id = ctx["claim"]["id"]
    headers = make_claims_adjuster_headers(ctx["adjuster"]["id"])
    est1 = validate_success(api.create_repair_estimate(
        {"claim_id": claim_id, "lines": [{"description": "v1", "labor_cents": 300_000, "parts_cents": 0}]},
        headers), 201)
    validate_success(api.submit_repair_estimate(est1["id"], headers), 200)
    est2 = validate_success(api.create_repair_estimate(
        {"claim_id": claim_id, "lines": [{"description": "v2", "labor_cents": 500_000, "parts_cents": 0}]},
        headers), 201)
    submitted2 = validate_success(api.submit_repair_estimate(est2["id"], headers), 200)
    assert submitted2["repair_total_cents"] == 500_000
    assert submitted2["status"] == "SUBMITTED"
    est1_after = validate_success(api.get_repair_estimate(est1["id"], headers), 200)
    assert est1_after["status"] == "SUPERSEDED"


def test_estimate_supersede_conserves_single_submitted_count(api):
    """PRD §3.4: "an estimate's submission supersedes its predecessor: if another
    repair estimate for the same claim is already `SUBMITTED`, that earlier estimate
    is transitioned `SUBMITTED → SUPERSEDED` as a side effect of the new submission,
    leaving exactly one `SUBMITTED` estimate per claim at any time."

    Design: Difficulty/compensating_invariant/estimate_supersede_conserves_single_submitted_count
    """
    ctx = setup_claim_under_review()
    claim_id = ctx["claim"]["id"]
    adj_id = ctx["adjuster"]["id"]
    headers = make_claims_adjuster_headers(adj_id)

    est1 = validate_success(api.create_repair_estimate(
        {"claim_id": claim_id, "lines": [{"description": "v1", "labor_cents": 300_000, "parts_cents": 0}]},
        headers), 201)
    validate_success(api.submit_repair_estimate(est1["id"], headers), 200)
    est2 = validate_success(api.create_repair_estimate(
        {"claim_id": claim_id, "lines": [{"description": "v2", "labor_cents": 500_000, "parts_cents": 0}]},
        headers), 201)
    validate_success(api.submit_repair_estimate(est2["id"], headers), 200)

    res = api.list_repair_estimates(headers, params={"claim_id": claim_id, "status": "SUBMITTED"})
    body = res.json()
    submitted = body["data"]
    assert body["meta"]["total_count"] == 1, "exactly one SUBMITTED estimate per claim"
    assert len(submitted) == 1
    assert submitted[0]["id"] == est2["id"]
    est1_after = validate_success(api.get_repair_estimate(est1["id"], headers), 200)
    assert est1_after["status"] == "SUPERSEDED"
    est2_after = validate_success(api.get_repair_estimate(est2["id"], headers), 200)
    assert est2_after["status"] == "SUBMITTED"


def test_three_submissions_keep_single_submitted_invariant(api):
    """PRD §3.4: "Crucially, an estimate's submission supersedes its predecessor: if
    another repair estimate for the same claim is already `SUBMITTED`, that earlier
    estimate is transitioned `SUBMITTED → SUPERSEDED` as a side effect of the new
    submission, leaving exactly one `SUBMITTED` estimate per claim at any time." After
    three sequential submissions only the last is SUBMITTED; the prior two are SUPERSEDED.

    Design: Difficulty/compensating_invariant/estimate_supersede_conserves_single_submitted_count
    """
    ctx = setup_claim_under_review()
    claim_id = ctx["claim"]["id"]
    headers = make_claims_adjuster_headers(ctx["adjuster"]["id"])
    ids = []
    for amt in (100_000, 200_000, 300_000):
        est = validate_success(api.create_repair_estimate(
            {"claim_id": claim_id, "lines": [{"description": "x", "labor_cents": amt, "parts_cents": 0}]},
            headers), 201)
        validate_success(api.submit_repair_estimate(est["id"], headers), 200)
        ids.append(est["id"])

    res = api.list_repair_estimates(headers, params={"claim_id": claim_id, "status": "SUBMITTED"})
    body = res.json()
    assert body["meta"]["total_count"] == 1
    assert len(body["data"]) == 1
    assert body["data"][0]["id"] == ids[-1]
    # The first two are SUPERSEDED.
    for prior in ids[:-1]:
        assert validate_success(api.get_repair_estimate(prior, headers), 200)["status"] == "SUPERSEDED"


# ─── Repair-path settlement (dual_variant_calc + calculations corner) ───

class TestRepairPathSettlement:
    def test_repair_settlement_under_limit(self, api):
        """PRD §3.6: "the after-deductible amount is the greater of zero and the gross
        minus the deductible, and the settlement is the lesser of that after-deductible
        amount and the coverage limit. When the after-deductible amount is at or below
        the limit, the settlement equals gross minus deductible".

        Design: Difficulty/dual_variant_calc/repair_vs_total_loss_settlement_diverge_on_same_claim
        """
        # gross 600000, deductible 50000, limit 1000000 -> 550000 (under limit).
        ctx = setup_repair_approved_claim(repair_total_cents=600_000)
        assert ctx["claim"]["disposition"] == "REPAIR"
        assert ctx["claim"]["settlement_cents"] == 550_000

    def test_repair_settlement_limit_capped(self, api):
        """PRD §3.6: "when it exceeds the limit, the settlement equals the limit and the
        excess is the insured's own responsibility." Concretely: gross 1200000,
        deductible 50000 -> after_deductible 1150000 > limit 1000000 -> settlement 1000000.

        Design: Corner/calculations/repair_settlement_limit_capped
        """
        policy = create_policy(comparative_fault_rule="PURE")
        add_collision_coverage(policy["id"], limit_cents=1_000_000, deductible_cents=50_000)
        adjuster = create_adjuster(license_tier="STANDARD")
        claim = file_claim(policy["id"], adjuster["id"], loss_type="COLLISION", vehicle_acv_cents=5_000_000)
        verified = verify_claim(claim["id"], adjuster["id"])
        assigned = assign_claim(claim["id"], adjuster["id"], verified["version"])
        submit_estimate(claim["id"], adjuster["id"], repair_total_cents=1_200_000)
        headers = make_claims_adjuster_headers(adjuster["id"])
        decided = validate_success(api.decide_disposition(
            claim["id"], {"decision": "REPAIR", "expected_claim_version": assigned["version"]}, headers), 200)
        assert decided["settlement_cents"] == 1_000_000


def test_repair_and_total_loss_settlement_diverge_on_same_inputs(api):
    """PRD §3.6 repair branch: "the after-deductible amount is the greater of zero and
    the gross minus the deductible, and the settlement is the lesser of that
    after-deductible amount and the coverage limit." PRD §3.6 total-loss branch: "That
    payout begins from the evaluation's snapshot `acv_cents`; if the evaluation's
    `salvage_retained_by_insurer` is true the claim's `salvage_value_cents` is subtracted
    (the insurer keeps the wreck), and if it is false no salvage is subtracted (the
    insured keeps the wreck, so the payout is higher by the salvage amount); the
    deductible is then withheld with a floor of zero; and finally the result is capped at
    the coverage `limit_cents`."

    Design: Difficulty/dual_variant_calc/repair_vs_total_loss_settlement_diverge_on_same_claim
    """
    # Claim A repair path: gross 600000 - deductible 50000 = 550000.
    repair_ctx = setup_repair_approved_claim(repair_total_cents=600_000, vehicle_acv_cents=800_000)
    settlement_a = repair_ctx["claim"]["settlement_cents"]
    assert settlement_a == 550_000

    # Claim B total-loss path: ACV 800000 - salvage 120000 - deductible 50000 = 630000.
    tl_ctx = setup_total_loss_ready(
        vehicle_acv_cents=800_000, repair_total_cents=600_000,
        salvage_value_cents=120_000, deductible_cents=50_000, limit_cents=1_000_000,
        salvage_retained_by_insurer=True)
    decided_b = decide_total_loss(tl_ctx["claim"]["id"], tl_ctx["adjS"]["id"], tl_ctx["version"])
    settlement_b = decided_b["settlement_cents"]
    assert settlement_b == 630_000
    assert settlement_a != settlement_b


# ─── Disposition fork (non_linear_state_machine) ───

def test_repair_branch_fork_sets_disposition_and_status(api):
    """PRD §3.6: "A `ClaimsAdjuster` may decide for repair, advancing the claim
    `UNDER_REVIEW → REPAIR_APPROVED`." PRD §3.6: "On success the claim's `disposition`
    is set to `REPAIR` and its `settlement_cents` is recomputed as the first-party
    repair payout."

    Design: Difficulty/non_linear_state_machine/claim_branching_fork_repair_vs_total_loss_divergent_side_effects
    """
    ctx = setup_claim_with_submitted_estimate(repair_total_cents=600_000)
    headers = make_claims_adjuster_headers(ctx["adjuster"]["id"])
    decided = validate_success(api.decide_disposition(
        ctx["claim"]["id"], {"decision": "REPAIR", "expected_claim_version": ctx["version"]}, headers), 200)
    assert decided["disposition"] == "REPAIR"
    assert decided["status"] == "REPAIR_APPROVED"
    assert decided["settlement_cents"] == 550_000


def test_total_loss_branch_fork_sets_disposition_and_status(api):
    """PRD §3.6: "A `TotalLossAdjuster` may decide for total loss, advancing the claim
    `UNDER_REVIEW → TOTAL_LOSS`." PRD §3.6: "the claim's `disposition` is set to
    `TOTAL_LOSS` and its `settlement_cents` is recomputed as the first-party total-loss
    payout."

    Design: Difficulty/non_linear_state_machine/claim_branching_fork_repair_vs_total_loss_divergent_side_effects
    """
    ctx = setup_total_loss_ready(
        vehicle_acv_cents=800_000, repair_total_cents=600_000,
        salvage_value_cents=120_000, deductible_cents=50_000, limit_cents=1_000_000,
        salvage_retained_by_insurer=True)
    decided = decide_total_loss(ctx["claim"]["id"], ctx["adjS"]["id"], ctx["version"])
    assert decided["disposition"] == "TOTAL_LOSS"
    assert decided["status"] == "TOTAL_LOSS"
    assert decided["settlement_cents"] == 630_000


# ─── Disposition business gates (validations + cross_cutting) ───

def test_repair_disposition_without_submitted_estimate_rejected(api):
    """PRD §3.6: "This branch requires that exactly one repair estimate for the claim is
    in `SUBMITTED` status, and that no total-loss evaluation for the claim has
    `is_total_loss` true; if there is no single submitted estimate the request is
    rejected with `ERR_NO_SUBMITTED_ESTIMATE`."

    Design: Corner/validations/repair_disposition_without_submitted_estimate_rejected
    """
    ctx = setup_claim_under_review()
    claim_id = ctx["claim"]["id"]
    adj_id = ctx["adjuster"]["id"]
    headers = make_claims_adjuster_headers(adj_id)
    # Create a DRAFT estimate but never submit it.
    api.create_repair_estimate(
        {"claim_id": claim_id, "lines": [{"description": "draft", "labor_cents": 100_000, "parts_cents": 0}]},
        headers)
    res = api.decide_disposition(
        claim_id, {"decision": "REPAIR", "expected_claim_version": ctx["version"]}, headers)
    validate_error(res, "ERR_NO_SUBMITTED_ESTIMATE", expected_status=409)


def test_senior_tier_required_for_total_loss_evaluation(api):
    """PRD §3.5: "Authoring is gated: only a `SENIOR`-tier adjuster may author an
    evaluation, and an attempt by a non-senior adjuster is rejected with
    `ERR_SENIOR_TIER_REQUIRED`."

    Design: Corner/validations/senior_tier_required_for_total_loss_evaluation
    """
    ctx = setup_claim_with_submitted_estimate(repair_total_cents=600_000)
    # A second STANDARD-tier adjuster attempts the evaluation.
    std2 = create_adjuster(license_tier="STANDARD")
    headers = make_total_loss_adjuster_headers(std2["id"])
    res = api.create_total_loss_evaluation({"claim_id": ctx["claim"]["id"]}, headers)
    validate_error(res, "ERR_SENIOR_TIER_REQUIRED", expected_status=409)


def test_segregation_of_duties_same_author_blocks_total_loss(api):
    """PRD §3.6: "that the evaluation's `evaluated_by_adjuster_id` differs from the
    `authored_by_adjuster_id` of the submitted repair estimate, enforcing segregation
    of duties; a same-author collision is rejected with `ERR_SEGREGATION_OF_DUTIES`."

    Design: Corner/cross_cutting_complexity_layers/segregation_of_duties_same_author_blocks_total_loss
    """
    # A single SENIOR adjuster authors the estimate AND the evaluation.
    policy = create_policy(comparative_fault_rule="PURE")
    add_collision_coverage(policy["id"])
    adjS = create_adjuster(license_tier="SENIOR")
    claim = file_claim(policy["id"], adjS["id"], loss_type="COLLISION", vehicle_acv_cents=800_000)
    verified = verify_claim(claim["id"], adjS["id"])
    assigned = assign_claim(claim["id"], adjS["id"], verified["version"])
    submit_estimate(claim["id"], adjS["id"], repair_total_cents=600_000)  # authored by adjS
    author_total_loss_evaluation(claim["id"], adjS["id"], salvage_retained_by_insurer=True)  # evaluated by adjS
    headers = make_total_loss_adjuster_headers(adjS["id"])
    res = api.decide_disposition(
        claim["id"], {"decision": "TOTAL_LOSS", "expected_claim_version": assigned["version"]}, headers)
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=409)


# ─── Priority-pair conflict (priority_pair_validation_conflict) ───

def test_state_beats_no_submitted_estimate_on_repair_disposition(api):
    """PRD §3.6: "Only then does it confirm the target resource is in a state from
    which the requested transition is defined, rejecting an out-of-state request with
    `ERR_INVALID_STATE`". The state check (priority 5) precedes the business gate
    (`ERR_NO_SUBMITTED_ESTIMATE`), so a COVERAGE_VERIFIED (not UNDER_REVIEW) claim with
    no estimate surfaces ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_no_submitted_estimate_on_repair_disposition
    """
    # Verify but do NOT assign -> claim is COVERAGE_VERIFIED (decide-disposition is only
    # defined from UNDER_REVIEW). No estimate exists either.
    policy = create_policy(comparative_fault_rule="PURE")
    add_collision_coverage(policy["id"])
    adjuster = create_adjuster(license_tier="STANDARD")
    claim = file_claim(policy["id"], adjuster["id"], loss_type="COLLISION", vehicle_acv_cents=800_000)
    verified = verify_claim(claim["id"], adjuster["id"])
    headers = make_claims_adjuster_headers(adjuster["id"])
    res = api.decide_disposition(
        claim["id"], {"decision": "REPAIR", "expected_claim_version": verified["version"]}, headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_state_beats_no_submitted_estimate_from_fnol_state(api):
    """PRD §3.6: "Only then does it confirm the target resource is in a state from which
    the requested transition is defined, rejecting an out-of-state request with
    `ERR_INVALID_STATE`". From the initial FNOL_SUBMITTED state (not UNDER_REVIEW) with
    no submitted estimate, the state check (priority 5) wins over the missing-estimate
    business check, surfacing ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_no_submitted_estimate_on_repair_disposition
    """
    # File a claim but neither verify nor assign it -> still FNOL_SUBMITTED, no estimate.
    policy = create_policy(comparative_fault_rule="PURE")
    add_collision_coverage(policy["id"])
    adjuster = create_adjuster(license_tier="STANDARD")
    claim = file_claim(policy["id"], adjuster["id"], loss_type="COLLISION", vehicle_acv_cents=800_000)
    headers = make_claims_adjuster_headers(adjuster["id"])
    res = api.decide_disposition(
        claim["id"], {"decision": "REPAIR", "expected_claim_version": claim["version"]}, headers)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
