"""Total-loss evaluation/settlement and rental reimbursement.

Covers: the 0.75 total-loss ratio boundary (inclusive at exactly 0.75, false at
0.7499), total-loss settlement variants (salvage retained vs returned, the nested
min/max combinatorial form), rental computation, total-loss curtailment to 5 days,
rental interval/overlap validation, and rental approve/reject.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    create_policy, add_collision_coverage, add_rental_coverage,
    create_adjuster, file_claim, verify_claim, assign_claim, submit_estimate,
    author_total_loss_evaluation,
    setup_total_loss_ready, decide_total_loss,
    setup_verified_claim_with_rental_coverage, setup_verified_claim_no_rental_coverage,
    create_rental,
    make_claims_adjuster_headers, make_total_loss_adjuster_headers,
    TOTAL_LOSS_THRESHOLD, TOTAL_LOSS_RENTAL_MAX_DAYS,
    TEST_USERS,
)

SUP = TEST_USERS["supervisor_headers"]


# ─── Total-loss ratio boundary (boundary_precision_check + calculations corner) ───

class TestTotalLossRatioBoundary:
    def _evaluate(self, api, repair_total_cents, vehicle_acv_cents=800_000):
        policy = create_policy(comparative_fault_rule="PURE")
        add_collision_coverage(policy["id"])
        adj1 = create_adjuster(license_tier="STANDARD")
        adjS = create_adjuster(license_tier="SENIOR")
        claim = file_claim(policy["id"], adj1["id"], loss_type="COLLISION", vehicle_acv_cents=vehicle_acv_cents)
        verified = verify_claim(claim["id"], adj1["id"])
        assign_claim(claim["id"], adj1["id"], verified["version"])
        submit_estimate(claim["id"], adj1["id"], repair_total_cents=repair_total_cents)
        headers = make_total_loss_adjuster_headers(adjS["id"])
        return validate_success(api.create_total_loss_evaluation(
            {"claim_id": claim["id"], "salvage_retained_by_insurer": True}, headers), 201)

    def test_total_loss_ratio_inclusive_at_exactly_0_75(self, api):
        """PRD §3.5: "a ratio of exactly 0.7500 **is** a total loss because the boundary
        is inclusive". PRD §3.5: "The `total_loss_ratio` is the snapshot
        `repair_total_cents` divided by the snapshot `acv_cents`, rounded to four
        decimal places half-up."

        Design: Difficulty/boundary_precision_check/total_loss_ratio_inclusive_at_exactly_0_75
        """
        # 600000 / 800000 = 0.7500 exactly.
        ev = self._evaluate(api, repair_total_cents=600_000, vehicle_acv_cents=800_000)
        assert ev["total_loss_ratio"] == pytest.approx(0.75, abs=1e-9)
        assert ev["is_total_loss"] is True

    def test_total_loss_ratio_below_threshold_not_total_loss(self, api):
        """PRD §3.5: "while a ratio of 0.7499 stays just below the boundary and remains
        on the repair path. The boundary comparison is at-or-above, never
        strictly-above."

        Design: Corner/calculations/total_loss_ratio_below_threshold_not_total_loss
        """
        # 599900 / 800000 = 0.749875 -> rounded half-up to 4 places = 0.7499.
        ev = self._evaluate(api, repair_total_cents=599_900, vehicle_acv_cents=800_000)
        assert ev["total_loss_ratio"] == pytest.approx(0.7499, abs=1e-9)
        assert ev["is_total_loss"] is False

    def test_total_loss_ratio_above_threshold_is_total_loss(self, api):
        """PRD §3.5: "The boolean `is_total_loss` is true when `total_loss_ratio` is at
        or above the total-loss threshold". A ratio clearly above 0.75 is a total loss.

        Design: Difficulty/boundary_precision_check/total_loss_ratio_inclusive_at_exactly_0_75
        """
        # 700000 / 800000 = 0.8750 > 0.75.
        ev = self._evaluate(api, repair_total_cents=700_000, vehicle_acv_cents=800_000)
        assert ev["total_loss_ratio"] == pytest.approx(0.875, abs=1e-9)
        assert ev["is_total_loss"] is True
        assert TOTAL_LOSS_THRESHOLD == 0.75


# ─── Total-loss settlement variants (combinatorial_formula + calculations corner) ───

def test_total_loss_settlement_salvage_retained_nested_min_max(api):
    """PRD §3.6: "That payout begins from the evaluation's snapshot `acv_cents`; if the
    evaluation's `salvage_retained_by_insurer` is true the claim's `salvage_value_cents`
    is subtracted (the insurer keeps the wreck), and if it is false no salvage is
    subtracted (the insured keeps the wreck, so the payout is higher by the salvage
    amount); the deductible is then withheld with a floor of zero; and finally the
    result is capped at the coverage `limit_cents`."

    Design: Difficulty/combinatorial_formula/total_loss_settlement_nested_min_max_with_salvage_branch
    """
    # ACV 800000 - salvage 120000 - deductible 50000 = 630000, under limit 1000000.
    ctx = setup_total_loss_ready(
        vehicle_acv_cents=800_000, repair_total_cents=600_000,
        salvage_value_cents=120_000, deductible_cents=50_000, limit_cents=1_000_000,
        salvage_retained_by_insurer=True)
    decided = decide_total_loss(ctx["claim"]["id"], ctx["adjS"]["id"], ctx["version"])
    assert decided["settlement_cents"] == 630_000


def test_total_loss_settlement_limit_caps_nested_min(api):
    """PRD §3.6: "the after-deductible figure is the greater of zero and after-salvage
    minus the deductible, and the settlement is the lesser of after-deductible and the
    limit." With ACV 2000000, no salvage, deductible 50000 -> after_deductible 1950000,
    capped at limit 1000000 -> 1000000 (the nested min selects the limit).

    Design: Difficulty/combinatorial_formula/total_loss_settlement_nested_min_max_with_salvage_branch
    """
    # ratio = repair_total 1700000 / ACV 2000000 = 0.85 >= 0.75 -> total loss.
    ctx = setup_total_loss_ready(
        vehicle_acv_cents=2_000_000, repair_total_cents=1_700_000,
        salvage_value_cents=0, deductible_cents=50_000, limit_cents=1_000_000,
        salvage_retained_by_insurer=True)
    decided = decide_total_loss(ctx["claim"]["id"], ctx["adjS"]["id"], ctx["version"])
    assert decided["settlement_cents"] == 1_000_000


def test_total_loss_salvage_to_insured_raises_payout(api):
    """PRD §3.6: "if it is false no salvage is subtracted (the insured keeps the wreck,
    so the payout is higher by the salvage amount)". With salvage returned: ACV 800000 -
    deductible 50000 = 750000 (vs 630000 when retained).

    Design: Corner/calculations/total_loss_salvage_to_insured_raises_payout
    """
    ctx = setup_total_loss_ready(
        vehicle_acv_cents=800_000, repair_total_cents=600_000,
        salvage_value_cents=120_000, deductible_cents=50_000, limit_cents=1_000_000,
        salvage_retained_by_insurer=False)
    decided = decide_total_loss(ctx["claim"]["id"], ctx["adjS"]["id"], ctx["version"])
    assert decided["settlement_cents"] == 750_000


# ─── Rental computation, approval, rejection (cross_entity_state_dependency + state_machines) ───

def test_rental_approve_requires_verified_coverage_and_rental_coverage(api):
    """PRD §3.7: "Approving a rental moves it `PENDING → APPROVED`, but only when the
    parent claim has a `VERIFIED` coverage verification and the policy actually carries
    a `RENTAL` coverage, and only when the rental's `reimbursement_cents` is greater
    than zero." Per-day = min(6000, 5000)=5000; days = ceil(7) capped at max 10 = 7;
    reimbursement = 7 * 5000 = 35000.

    Design: Difficulty/cross_entity_state_dependency/rental_approve_requires_verified_coverage_and_rental_coverage
    """
    ctx = setup_verified_claim_with_rental_coverage(rental_max_days=10, rental_daily_cap_cents=5_000)
    rental = create_rental(
        ctx["claim"]["id"], ctx["adjuster"]["id"],
        "2026-06-01T00:00:00.000Z", "2026-06-08T00:00:00.000Z", daily_rate_cents=6_000)
    assert rental["reimbursement_cents"] == 35_000
    headers = make_claims_adjuster_headers(ctx["adjuster"]["id"])
    approved = validate_success(api.approve_rental_reimbursement(rental["id"], headers), 200)
    assert approved["status"] == "APPROVED"


def test_rental_approve_creates_rental_disbursement_and_updates_ledger(api):
    """PRD §3.7: "Approval creates a `RENTAL` disbursement in `APPROVED` status whose
    `amount_cents` is the positive `reimbursement_cents`, then recomputes the parent
    claim's `total_disbursed_cents`." reimbursement 35000 -> a +35000 RENTAL disbursement
    and total_disbursed_cents 35000.

    Design: Difficulty/cross_entity_state_dependency/rental_approve_requires_verified_coverage_and_rental_coverage
    """
    ctx = setup_verified_claim_with_rental_coverage(rental_max_days=10, rental_daily_cap_cents=5_000)
    claim_id = ctx["claim"]["id"]
    rental = create_rental(
        claim_id, ctx["adjuster"]["id"],
        "2026-06-01T00:00:00.000Z", "2026-06-08T00:00:00.000Z", daily_rate_cents=6_000)
    assert rental["reimbursement_cents"] == 35_000
    headers = make_claims_adjuster_headers(ctx["adjuster"]["id"])
    validate_success(api.approve_rental_reimbursement(rental["id"], headers), 200)

    disbursements, _meta = _list(api.list_claim_disbursements(claim_id, SUP))
    rental_disb = [d for d in disbursements if d["disbursement_type"] == "RENTAL"]
    assert len(rental_disb) == 1
    assert rental_disb[0]["amount_cents"] == 35_000
    assert rental_disb[0]["status"] == "APPROVED"
    claim_after = validate_success(api.get_claim(claim_id, SUP), 200)
    assert claim_after["total_disbursed_cents"] == 35_000


def test_rental_reject_when_no_rental_coverage(api):
    """PRD §3.7: "a rental is rejected, moving `PENDING → REJECTED`, precisely when its
    `reimbursement_cents` is zero or the policy carries no `RENTAL` coverage." With no
    RENTAL coverage the per-day cap is 0, so reimbursement_cents is 0.

    Design: Corner/state_machines/rental_reject_when_no_rental_coverage
    """
    ctx = setup_verified_claim_no_rental_coverage()
    rental = create_rental(
        ctx["claim"]["id"], ctx["adjuster"]["id"],
        "2026-06-01T00:00:00.000Z", "2026-06-08T00:00:00.000Z", daily_rate_cents=6_000)
    assert rental["reimbursement_cents"] == 0
    headers = make_claims_adjuster_headers(ctx["adjuster"]["id"])
    rejected = validate_success(api.reject_rental_reimbursement(rental["id"], headers), 200)
    assert rejected["status"] == "REJECTED"


def test_rental_total_loss_curtailment_to_5_days(api):
    """PRD §3.7: "if the parent claim's `disposition` is `TOTAL_LOSS`, the day cap is
    lowered to the smaller of `rental_max_days` and five days". PRD §3.7: "when a claim
    flips to `TOTAL_LOSS`, each still-`PENDING` rental is recomputed with the
    five-day-curtailed cap, lowering both its `reimbursable_days` and its
    `reimbursement_cents`."

    Design: Corner/calculations/rental_total_loss_curtailment_to_5_days
    """
    # Set up a total-loss-ready claim with COLLISION + RENTAL coverage (cap 5000/day, max 10).
    ctx = setup_total_loss_ready(
        vehicle_acv_cents=800_000, repair_total_cents=600_000,
        salvage_value_cents=0, deductible_cents=50_000, limit_cents=1_000_000,
        salvage_retained_by_insurer=True, with_rental=True, rental_max_days=10)
    # Pre-disposition PENDING 7-day rental: per_day min(6000,5000)=5000, days=7 -> 35000.
    rental = create_rental(
        ctx["claim"]["id"], ctx["adj1"]["id"],
        "2026-06-01T00:00:00.000Z", "2026-06-08T00:00:00.000Z", daily_rate_cents=6_000)
    assert rental["reimbursement_cents"] == 35_000, "pre-disposition reimbursement should be 35000"

    # Decide TOTAL_LOSS -> curtails PENDING rentals to min(10, 5) = 5 days.
    decide_total_loss(ctx["claim"]["id"], ctx["adjS"]["id"], ctx["version"])
    headers = make_claims_adjuster_headers(ctx["adj1"]["id"])
    post = validate_success(api.get_rental_reimbursement(rental["id"], headers), 200)
    assert post["reimbursable_days"] == 5
    assert post["reimbursement_cents"] == 25_000
    assert TOTAL_LOSS_RENTAL_MAX_DAYS == 5


def test_rental_invalid_interval_rejected(api):
    """PRD §3.7: "The window must be a positive interval: `rental_end_date` must be
    strictly after `rental_start_date`, or the request is rejected with
    `ERR_INVALID_RENTAL_INTERVAL`."

    Design: Corner/validations/rental_invalid_interval_rejected
    """
    ctx = setup_verified_claim_with_rental_coverage()
    headers = make_claims_adjuster_headers(ctx["adjuster"]["id"])
    res = api.create_rental_reimbursement(
        {"claim_id": ctx["claim"]["id"],
         "rental_start_date": "2026-06-01T00:00:00.000Z",
         "rental_end_date": "2026-06-01T00:00:00.000Z",
         "daily_rate_cents": 6_000},
        headers)
    validate_error(res, "ERR_INVALID_RENTAL_INTERVAL", expected_status=422)


# ─── Rental temporal overlap (resource_temporal_overlap, difficulty) ───

def test_rental_period_overlap_half_open_rejected(api):
    """PRD §3.7: "A new rental is rejected with `ERR_RENTAL_PERIOD_OVERLAP` if its
    half-open interval overlaps that of any existing `PENDING` or `APPROVED` rental on
    the same claim. Overlap holds when the new rental's start is strictly before the
    existing rental's end **and** the existing rental's start is strictly before the new
    rental's end".

    Design: Difficulty/resource_temporal_overlap/rental_period_overlap_half_open_adjacency_allowed
    """
    ctx = setup_verified_claim_with_rental_coverage(rental_max_days=30)
    headers = make_claims_adjuster_headers(ctx["adjuster"]["id"])
    create_rental(
        ctx["claim"]["id"], ctx["adjuster"]["id"],
        "2026-06-01T00:00:00.000Z", "2026-06-08T00:00:00.000Z", daily_rate_cents=6_000)
    # [2026-06-05, 2026-06-10) overlaps [2026-06-01, 2026-06-08).
    res = api.create_rental_reimbursement(
        {"claim_id": ctx["claim"]["id"],
         "rental_start_date": "2026-06-05T00:00:00.000Z",
         "rental_end_date": "2026-06-10T00:00:00.000Z",
         "daily_rate_cents": 6_000},
        headers)
    validate_error(res, "ERR_RENTAL_PERIOD_OVERLAP", expected_status=409)


def test_rental_period_adjacency_allowed(api):
    """PRD §3.7: "adjacency is allowed, so one rental ending exactly when another begins
    is not a collision." A second rental whose start equals the first's end must NOT
    collide.

    Design: Difficulty/resource_temporal_overlap/rental_period_overlap_half_open_adjacency_allowed
    """
    ctx = setup_verified_claim_with_rental_coverage(rental_max_days=30)
    headers = make_claims_adjuster_headers(ctx["adjuster"]["id"])
    create_rental(
        ctx["claim"]["id"], ctx["adjuster"]["id"],
        "2026-06-01T00:00:00.000Z", "2026-06-08T00:00:00.000Z", daily_rate_cents=6_000)
    # [2026-06-08, 2026-06-12) touches the prior end (2026-06-08) -> allowed.
    res = api.create_rental_reimbursement(
        {"claim_id": ctx["claim"]["id"],
         "rental_start_date": "2026-06-08T00:00:00.000Z",
         "rental_end_date": "2026-06-12T00:00:00.000Z",
         "daily_rate_cents": 6_000},
        headers)
    rental2 = validate_success(res, 201)
    assert rental2["status"] == "PENDING"


def _list(response):
    body = response.json()
    return body["data"], body["meta"]
