"""Validation-priority conflict resolution and the two resource-occupation
geometries: the fund-capacity over-cap rejection and the cy-pres exact-partition
unbalanced-shares rejection.

Queue A (Difficulty): priority_pair_validation_conflict, resource_temporal_overlap.
"""
from test_helpers import (
    get_success_data,
    validate_error,
    fixtures,
    ApiErrorId,
)
from test_helpers.api_client import api_client
from test_helpers.test_users import (
    make_claims_reviewer_headers,
    make_fund_controller_headers,
)

ADMIN = fixtures.ADMIN
ADMINISTRATOR = fixtures.ADMINISTRATOR
CONTROLLER = fixtures.CONTROLLER


# ─── priority_pair_validation_conflict: posture_invalid_beats_claim_window_closed ─
def test_posture_invalid_beats_claim_window_closed():
    """PRD §2.12: "then the state-transition legality check (`ERR_INVALID_STATE`), then the owning-settlement posture check (`ERR_SETTLEMENT_POSTURE_INVALID`), then the timing windows (claim window, then objection/opt-out window, then cure window)"

    Design: Difficulty/priority_pair_validation_conflict/posture_invalid_beats_claim_window_closed
    """
    fixtures.set_clock("2026-03-01T00:00:00Z")  # already past the filing deadline
    settlement = fixtures.create_settlement(
        claim_filing_deadline="2026-02-01T00:00:00Z",
        objection_deadline="2026-01-20T00:00:00Z",
        cy_pres_floor_cents=0,
        case_caption="In re Conflict1",
    )
    s_id = settlement["id"]
    get_success_data(api_client.open_notice(s_id, ADMIN))  # settlement now NOTICE_OPEN, not CLAIMS_OPEN
    member = fixtures.register_member(s_id, full_name="M", email="m@x.com", tin_on_file=True)

    resp = api_client.create_claim(
        {"settlement_id": s_id, "class_member_id": member["id"], "claimed_loss_cents": 5000},
        ADMINISTRATOR,
    )
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_POSTURE_INVALID.value)


def test_posture_invalid_reported_not_window_closed_when_both_fail():
    """PRD §2.12: "the owning-settlement posture check (`ERR_SETTLEMENT_POSTURE_INVALID`), then the timing windows (claim window, then objection/opt-out window, then cure window)"

    Design: Difficulty/priority_pair_validation_conflict/posture_invalid_beats_claim_window_closed
    """
    fixtures.set_clock("2026-03-01T00:00:00Z")
    settlement = fixtures.create_settlement(
        claim_filing_deadline="2026-02-01T00:00:00Z",
        objection_deadline="2026-01-20T00:00:00Z",
        cy_pres_floor_cents=0,
        case_caption="In re Conflict1b",
    )
    s_id = settlement["id"]
    get_success_data(api_client.open_notice(s_id, ADMIN))
    member = fixtures.register_member(s_id, full_name="M", email="m@x.com", tin_on_file=True)

    resp = api_client.create_claim(
        {"settlement_id": s_id, "class_member_id": member["id"], "claimed_loss_cents": 5000},
        ADMINISTRATOR,
    )
    body = resp.json()
    assert body["data"]["error_id"] != ApiErrorId.ERR_CLAIM_WINDOW_CLOSED.value
    assert body["data"]["error_id"] == ApiErrorId.ERR_SETTLEMENT_POSTURE_INVALID.value


# ─── priority_pair_validation_conflict: segregation_beats_fund_exceeded_on_post ─
def _setup_dual_hat_overcap_computed(dual_hat_id="dual-hat-user"):
    """DISTRIBUTING TIERED net=100, one TIER_A claim flat-awarded 200 (over-cap),
    validated by `dual_hat_id`, COMPUTED batch ready to post. Returns (s_id, batch_id)."""
    fixtures.set_clock("2026-01-01T00:00:00Z")
    settlement = fixtures.create_settlement(
        gross_fund_cents=100,
        distribution_method="TIERED",
        tier_a_amount_cents=200,
        tier_b_amount_cents=200,
        claim_filing_deadline="2026-02-01T00:00:00Z",
        objection_deadline="2026-01-20T00:00:00Z",
        cy_pres_floor_cents=0,
        case_caption="In re Conflict2",
    )
    s_id = settlement["id"]
    get_success_data(api_client.open_notice(s_id, ADMIN))
    member = fixtures.register_member(
        s_id, full_name="M", email="m@x.com", claimant_tier="TIER_A", tin_on_file=True)
    get_success_data(api_client.open_claims(s_id, ADMIN))
    claim = fixtures.file_claim(s_id, member["id"], claimed_loss_cents=999999)
    # validate AS the dual-hat user (records reviewer id = dual_hat_id)
    get_success_data(api_client.validate_claim(
        claim["id"], 999999, make_claims_reviewer_headers(dual_hat_id)))
    fixtures.set_clock("2026-02-01T00:00:00Z")
    get_success_data(api_client.close_claims(s_id, ADMIN))
    fixtures.begin_distribution(s_id)
    batch = fixtures.create_batch(s_id)
    batch = get_success_data(api_client.compute_batch(batch["id"], CONTROLLER))
    return s_id, batch["id"]


def test_segregation_beats_fund_exceeded_on_post():
    """PRD §3.6: "Posting is gated on three further conditions evaluated in this order: the segregation-of-duties rule of §2.10 (the posting controller must not be the reviewer who validated any claim in the batch, else `ERR_SEGREGATION_OF_DUTIES`); the stale-version guard (`ERR_STALE_SETTLEMENT_VERSION` on mismatch); and the fund-capacity check — the batch's `planned_total_cents` must not exceed the remaining headroom (`net_distributable_cents` minus `allocated_cents`), or the post is rejected with `ERR_FUND_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_fund_exceeded_on_post
    """
    s_id, batch_id = _setup_dual_hat_overcap_computed("dual-hat-user")
    version = fixtures.get_settlement_version(s_id)
    resp = api_client.post_batch(batch_id, version, make_fund_controller_headers("dual-hat-user"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


def test_fund_exceeded_reported_when_posting_controller_is_distinct():
    """PRD §3.6: "the fund-capacity check — the batch's `planned_total_cents` must not exceed the remaining headroom (`net_distributable_cents` minus `allocated_cents`), or the post is rejected with `ERR_FUND_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/segregation_beats_fund_exceeded_on_post
    """
    # Same over-cap batch, but validated by a reviewer distinct from the poster,
    # so segregation passes and the lower-priority fund-exceeded rule surfaces.
    s_id, batch_id = _setup_dual_hat_overcap_computed("reviewer-only")
    version = fixtures.get_settlement_version(s_id)
    resp = api_client.post_batch(batch_id, version, make_fund_controller_headers("controller-only"))
    validate_error(resp, ApiErrorId.ERR_FUND_EXCEEDED.value)


# ─── resource_temporal_overlap: fund_allocation_capacity_overflow_on_post ────
def test_fund_capacity_overflow_rejected_at_post():
    """PRD §3.6: "the batch's `planned_total_cents` must not exceed the remaining headroom (`net_distributable_cents` minus `allocated_cents`), or the post is rejected with `ERR_FUND_EXCEEDED` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/fund_allocation_capacity_overflow_on_post
    """
    fixtures.set_clock("2026-01-01T00:00:00Z")
    settlement = fixtures.create_settlement(
        gross_fund_cents=300,
        distribution_method="TIERED",
        tier_a_amount_cents=200,
        tier_b_amount_cents=200,
        claim_filing_deadline="2026-02-01T00:00:00Z",
        objection_deadline="2026-01-20T00:00:00Z",
        cy_pres_floor_cents=0,
        case_caption="In re FundCap",
    )
    s_id = settlement["id"]
    get_success_data(api_client.open_notice(s_id, ADMIN))
    m1 = fixtures.register_member(s_id, full_name="M1", email="m1@x.com", claimant_tier="TIER_A", tin_on_file=True)
    m2 = fixtures.register_member(s_id, full_name="M2", email="m2@x.com", claimant_tier="TIER_A", tin_on_file=True)
    get_success_data(api_client.open_claims(s_id, ADMIN))
    c1 = fixtures.file_claim(s_id, m1["id"], claimed_loss_cents=999999)
    c2 = fixtures.file_claim(s_id, m2["id"], claimed_loss_cents=999999)
    get_success_data(api_client.validate_claim(c1["id"], 999999, make_claims_reviewer_headers("reviewer-1")))
    get_success_data(api_client.validate_claim(c2["id"], 999999, make_claims_reviewer_headers("reviewer-1")))
    fixtures.set_clock("2026-02-01T00:00:00Z")
    get_success_data(api_client.close_claims(s_id, ADMIN))
    fixtures.begin_distribution(s_id)
    batch = fixtures.create_batch(s_id)
    batch = get_success_data(api_client.compute_batch(batch["id"], CONTROLLER))
    assert batch["planned_total_cents"] == 400  # un-capped 200+200 > cap 300

    version = fixtures.get_settlement_version(s_id)
    resp = api_client.post_batch(batch["id"], version, make_fund_controller_headers("controller-1"))
    validate_error(resp, ApiErrorId.ERR_FUND_EXCEEDED.value)
    settlement = get_success_data(api_client.get_settlement(s_id, ADMIN))
    assert settlement["allocated_cents"] == 0


def test_over_cap_batch_planned_total_uncapped_at_compute():
    """PRD §3.6: "The tiered awards are summed into `planned_total_cents` un-capped — the batch is not truncated at compute time. The resulting tiered total may come out below the remaining headroom, in which case the shortfall stands as a residual eligible for cy pres, or above it, in which case the batch is not silently trimmed but is rejected later at post time as described below."

    Design: Difficulty/resource_temporal_overlap/fund_allocation_capacity_overflow_on_post
    """
    fixtures.set_clock("2026-01-01T00:00:00Z")
    settlement = fixtures.create_settlement(
        gross_fund_cents=300,
        distribution_method="TIERED",
        tier_a_amount_cents=200,
        tier_b_amount_cents=200,
        claim_filing_deadline="2026-02-01T00:00:00Z",
        objection_deadline="2026-01-20T00:00:00Z",
        cy_pres_floor_cents=0,
        case_caption="In re FundCapUncapped",
    )
    s_id = settlement["id"]
    get_success_data(api_client.open_notice(s_id, ADMIN))
    m1 = fixtures.register_member(s_id, full_name="M1", email="m1@x.com", claimant_tier="TIER_A", tin_on_file=True)
    m2 = fixtures.register_member(s_id, full_name="M2", email="m2@x.com", claimant_tier="TIER_A", tin_on_file=True)
    get_success_data(api_client.open_claims(s_id, ADMIN))
    c1 = fixtures.file_claim(s_id, m1["id"], claimed_loss_cents=999999)
    c2 = fixtures.file_claim(s_id, m2["id"], claimed_loss_cents=999999)
    get_success_data(api_client.validate_claim(c1["id"], 999999, make_claims_reviewer_headers("reviewer-1")))
    get_success_data(api_client.validate_claim(c2["id"], 999999, make_claims_reviewer_headers("reviewer-1")))
    fixtures.set_clock("2026-02-01T00:00:00Z")
    get_success_data(api_client.close_claims(s_id, ADMIN))
    fixtures.begin_distribution(s_id)
    batch = fixtures.create_batch(s_id)
    batch = get_success_data(api_client.compute_batch(batch["id"], CONTROLLER))
    assert batch["planned_total_cents"] == 400


# ─── resource_temporal_overlap: cy_pres_exact_partition_collision_at_reconcile ─
def test_cy_pres_unbalanced_shares_reject_reconcile():
    """PRD §3.8: "Its precondition is that the basis-point shares of all approved designations sum to exactly 10000; if they do not, reconciliation is rejected with `ERR_CY_PRES_SHARES_UNBALANCED` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/cy_pres_exact_partition_collision_at_reconcile
    """
    ctx = fixtures.setup_posted_batch(
        distribution_method="TIERED",
        gross_fund_cents=760000,
        attorney_fee_cents=100000,
        admin_cost_cents=100000,
        tier_a_amount_cents=250000,
        tier_b_amount_cents=150000,
        cy_pres_floor_cents=20000,
        approve_cy_pres=[{"recipient_name": "R1", "share_bps": 9000}],  # sums to 9000, not 10000
        members=[
            {"email": "x@x.com", "full_name": "X", "claimant_tier": "TIER_A", "claimed_loss_cents": 999999, "recognized_loss_cents": 999999},
            {"email": "y@x.com", "full_name": "Y", "claimant_tier": "TIER_B", "claimed_loss_cents": 999999, "recognized_loss_cents": 999999},
            {"email": "z@x.com", "full_name": "Z", "claimant_tier": "TIER_B", "claimed_loss_cents": 999999, "recognized_loss_cents": 999999},
        ],
    )
    s_id = ctx["settlement"]["id"]
    version = fixtures.get_settlement_version(s_id)
    resp = api_client.reconcile(s_id, version, CONTROLLER)
    validate_error(resp, ApiErrorId.ERR_CY_PRES_SHARES_UNBALANCED.value)
    settlement = get_success_data(api_client.get_settlement(s_id, ADMIN))
    assert settlement["status"] == "DISTRIBUTING"


def test_cy_pres_unbalanced_leaves_settlement_distributing():
    """PRD §3.7: "Reconciliation is refused if the cy pres shares are unbalanced
    (§3.8) or if the stale-version guard fires."

    Design: Difficulty/resource_temporal_overlap/cy_pres_exact_partition_collision_at_reconcile
    """
    ctx = fixtures.setup_posted_batch(
        distribution_method="TIERED",
        gross_fund_cents=760000,
        attorney_fee_cents=100000,
        admin_cost_cents=100000,
        tier_a_amount_cents=250000,
        tier_b_amount_cents=150000,
        cy_pres_floor_cents=20000,
        approve_cy_pres=[{"recipient_name": "R1", "share_bps": 9000}],
        members=[
            {"email": "x@x.com", "full_name": "X", "claimant_tier": "TIER_A", "claimed_loss_cents": 999999, "recognized_loss_cents": 999999},
            {"email": "y@x.com", "full_name": "Y", "claimant_tier": "TIER_B", "claimed_loss_cents": 999999, "recognized_loss_cents": 999999},
            {"email": "z@x.com", "full_name": "Z", "claimant_tier": "TIER_B", "claimed_loss_cents": 999999, "recognized_loss_cents": 999999},
        ],
    )
    s_id = ctx["settlement"]["id"]
    version = fixtures.get_settlement_version(s_id)
    api_client.reconcile(s_id, version, CONTROLLER)
    settlement = get_success_data(api_client.get_settlement(s_id, ADMIN))
    assert settlement["status"] == "DISTRIBUTING"
