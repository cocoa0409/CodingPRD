"""Deal pipeline: the pinned commission waterfall, referral fee tiers, split
agreements (structure, windows, expiry), approval cascades, and disputes."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_deal_as_leader,
    assert_waterfall_conservation,
    create_agent,
    create_deal_as_agent,
    create_split_agreement,
    create_team,
    ctx_claimed_lead_with_campaign,
    ctx_pending_deal,
    enroll_as_leader,
    get_agreement,
    get_agent,
    get_deal,
    get_enrollment,
    get_lead,
    intake_lead,
    log_response_as,
    make_team_leader_headers,
    set_clock,
    split_agreement_payload,
    validate_error,
    validate_success,
    work_lead,
)

ADMIN = TEST_USERS["team_admin_headers"]


def _shares_map(deal):
    return {s["agent_id"]: s["amount_cents"] for s in deal["agent_shares"]}


# ─── Corner: approval state guard ────────────────────────────────────────────


def test_approve_approved_deal_returns_deal_not_approvable(api):
    """PRD §3.6: "Approval is allowed from `PENDING` or `DISPUTED`; from `APPROVED` or `PAID_OUT` the attempt is `ERR_DEAL_NOT_APPROVABLE`."

    Design: Corner/errors/approve_approved_deal_returns_deal_not_approvable
    """
    ctx = ctx_pending_deal(500_000)
    approve_deal_as_leader(ctx["deal"]["id"], ctx["leader"]["id"])
    assert get_agent(ctx["closer"]["id"])["trailing_90d_conversions"] == 1

    res = api.approve_deal(
        ctx["deal"]["id"], {}, make_team_leader_headers(ctx["leader"]["id"])
    )
    validate_error(res, ApiErrorId.ERR_DEAL_NOT_APPROVABLE, expected_status=409)
    assert get_deal(ctx["deal"]["id"])["status"] == "APPROVED"
    assert get_agent(ctx["closer"]["id"])["trailing_90d_conversions"] == 1, (
        "The closure cascade must not re-run on a rejected approval"
    )


# ─── Corner: split structural 422s ───────────────────────────────────────────


def test_split_share_sum_and_agent_pair_structural_errors(api):
    """PRD §3.6: "The two shares must sum to exactly 10000 basis points, else `ERR_SPLIT_SHARE_SUM_INVALID` (HTTP 422), and the pair must be two distinct `ACTIVE` agents of the same team, else `ERR_SPLIT_AGENT_PAIR_INVALID` (HTTP 422)."

    Design: Corner/validations/split_share_sum_and_agent_pair_structural_errors
    """
    team = create_team()
    a1 = create_agent(team["id"], "LIC-A1", display_name="Agent One")
    a2 = create_agent(team["id"], "LIC-A2", display_name="Agent Two")

    bad_sum = api.create_split_agreement(
        split_agreement_payload(team["id"], a1["id"], a2["id"], a_share_bps=4000, b_share_bps=4000),
        ADMIN,
    )
    validate_error(bad_sum, ApiErrorId.ERR_SPLIT_SHARE_SUM_INVALID, expected_status=422)

    self_pair = api.create_split_agreement(
        split_agreement_payload(team["id"], a1["id"], a1["id"]),
        ADMIN,
    )
    validate_error(self_pair, ApiErrorId.ERR_SPLIT_AGENT_PAIR_INVALID, expected_status=422)


# ─── Corner: split agreement expiry at the exclusive end ─────────────────────


def test_split_agreement_expires_at_effective_until_boundary(api):
    """PRD §3.6: "Termination by a leader or admin moves an `ACTIVE` agreement to `TERMINATED` (from any other state, `ERR_INVALID_STATE`), and the sweep moves an agreement whose `effective_until` has been reached or passed to `EXPIRED`; in both cases already-approved deals keep their snapshots."

    Design: Corner/state_machines/split_agreement_expires_at_effective_until_boundary
    """
    team = create_team()
    a1 = create_agent(team["id"], "LIC-A1", display_name="Agent One")
    a2 = create_agent(team["id"], "LIC-A2", display_name="Agent Two")
    agreement = create_split_agreement(
        team["id"], a1["id"], a2["id"], effective_until="2026-08-10T00:00:00Z"
    )

    sweep = set_clock("2026-08-10T00:00:00Z")  # now == effective_until
    assert sweep["expired_agreement_count"] == 1
    assert get_agreement(agreement["id"])["status"] == "EXPIRED"


# ─── Difficulty: ESTIMATED vs ACTUAL waterfall variants ──────────────────────


def test_deal_creation_computes_estimated_waterfall(api):
    """PRD §3.6: "The lead transitions `WORKING → UNDER_CONTRACT`, and the full commission waterfall below is computed immediately on the estimated basis, marked by `split_basis_type` `ESTIMATED`."
    PRD §3.6: "The split basis, `split_basis_cents`, is `gross_commission_cents` while the deal is `PENDING`."
    PRD §3.6: "First the referral fee: `referral_fee_cents` is the basis multiplied by `effective_fee_bps` and divided by 10000, rounded half up to a whole cent — zero when the deal has no referral partner."
    PRD §3.6: "Second the house share: `house_share_cents` is 3000 basis points (thirty percent) of the post-referral remainder, rounded half up."
    PRD §3.6: "Third, `agent_pool_cents` is whatever remains of the basis."

    Design: Difficulty/dual_variant_calc/commission_split_estimated_vs_actual_on_deal
    """
    ctx = ctx_pending_deal(1_000_000, with_partner=True, partner_fee_bps=2500)
    deal = ctx["deal"]
    assert deal["status"] == "PENDING"
    assert deal["split_basis_type"] == "ESTIMATED"
    assert deal["split_basis_cents"] == 1_000_000
    assert deal["effective_fee_bps"] == 2500
    assert deal["referral_fee_cents"] == 250_000
    assert deal["house_share_cents"] == 225_000
    assert deal["agent_pool_cents"] == 525_000
    assert deal["agent_shares"] == [
        {"agent_id": ctx["closer"]["id"], "amount_cents": 525_000}
    ]
    assert_waterfall_conservation(deal)
    assert get_lead(ctx["lead"]["id"])["status"] == "UNDER_CONTRACT"


def test_approval_with_actual_recomputes_waterfall_end_to_end(api):
    """PRD §3.6: "The request may carry `actual_gross_commission_cents` (strictly positive when provided); when provided, the basis switches to the actual figure, `split_basis_type` becomes `ACTUAL`, and every derived split field is recomputed — including the referral tier snapshot and any split-agreement coverage, both re-evaluated at the approval instant."
    PRD §3.6: "Approval cascades to the lead: it becomes `CLOSED_WON`, the closing agent's `active_lead_count` decrements, `trailing_90d_conversions` is recomputed and the agent's tier re-evaluated, and any `ENROLLED` or `PAUSED` nurture enrollment for the lead exits with `exit_reason` `CONVERTED`."

    Design: Difficulty/dual_variant_calc/commission_split_estimated_vs_actual_on_deal
    """
    ctx = ctx_pending_deal(1_000_000, with_partner=True, partner_fee_bps=2500)
    approved = approve_deal_as_leader(
        ctx["deal"]["id"], ctx["leader"]["id"], {"actual_gross_commission_cents": 1_200_000}
    )
    assert approved["status"] == "APPROVED"
    assert approved["split_basis_type"] == "ACTUAL"
    assert approved["split_basis_cents"] == 1_200_000
    assert approved["effective_fee_bps"] == 2500
    assert approved["referral_fee_cents"] == 300_000
    assert approved["house_share_cents"] == 270_000
    assert approved["agent_pool_cents"] == 630_000
    assert approved["agent_shares"] == [
        {"agent_id": ctx["closer"]["id"], "amount_cents": 630_000}
    ]
    assert_waterfall_conservation(approved)
    assert get_lead(ctx["lead"]["id"])["status"] == "CLOSED_WON"


# ─── Difficulty: pinned rounding order with a split agreement ────────────────

SPLIT_SPEC = {
    "agent_b": {"license_number": "LIC-B2", "display_name": "Partner B2", "max_active_leads": 10},
    "a_share_bps": 5001,
    "b_share_bps": 4999,
    "effective_from": "2026-08-01T00:00:00Z",
}


def test_pinned_rounding_order_at_deal_creation(api):
    """PRD §3.6: "Finally the pool is distributed into `agent_shares`: when an `ACTIVE` split agreement covers the closing agent at the computation instant, agent A receives the pool multiplied by `a_share_bps` and divided by 10000, rounded half up, and agent B receives the unrounded remainder; otherwise the closing agent receives the entire pool as a single entry."
    PRD §3.6: "This pinned order — basis, then referral fee, then house share, then pool, then A, then B — guarantees money conservation: the referral fee plus the house share plus the sum of the agent shares always equals the basis exactly."

    Design: Difficulty/combinatorial_formula/commission_split_pinned_rounding_order
    """
    ctx = ctx_pending_deal(7143, split=SPLIT_SPEC)
    deal = ctx["deal"]
    assert deal["referral_fee_cents"] == 0, "No referral partner"
    assert deal["house_share_cents"] == 2143, "round_half_up(7143 * 3000 / 10000) = round_half_up(2142.9)"
    assert deal["agent_pool_cents"] == 5000
    shares = _shares_map(deal)
    assert shares == {ctx["closer"]["id"]: 2501, ctx["agent_b"]["id"]: 2499}, (
        "A = round_half_up(5000 * 5001 / 10000) = 2501; B takes the unrounded remainder 2499"
    )
    assert_waterfall_conservation(deal)


def test_pinned_rounding_order_persists_through_approval_snapshot(api):
    """PRD §3.6: "Finally the pool is distributed into `agent_shares`: when an `ACTIVE` split agreement covers the closing agent at the computation instant, agent A receives the pool multiplied by `a_share_bps` and divided by 10000, rounded half up, and agent B receives the unrounded remainder; otherwise the closing agent receives the entire pool as a single entry."
    PRD §3.6: "The deal's `split_agreement_id` snapshots the agreement applied at approval and is null when none applied."
    PRD §3.6: "When no actual figure is provided, the basis remains the estimated `gross_commission_cents`."

    Design: Difficulty/combinatorial_formula/commission_split_pinned_rounding_order
    """
    ctx = ctx_pending_deal(7143, split=SPLIT_SPEC)
    approved = approve_deal_as_leader(ctx["deal"]["id"], ctx["leader"]["id"])
    assert approved["split_basis_cents"] == 7143
    assert approved["referral_fee_cents"] == 0
    assert approved["house_share_cents"] == 2143
    assert approved["agent_pool_cents"] == 5000
    assert _shares_map(approved) == {ctx["closer"]["id"]: 2501, ctx["agent_b"]["id"]: 2499}
    assert approved["split_agreement_id"] == ctx["agreement"]["id"]
    assert_waterfall_conservation(approved)


# ─── Difficulty: referral fee volume tier excludes the current deal ──────────


def _two_deal_tier_setup(api):
    """Partner (2500 bps); deal1 basis 6,000,000 approved; deal2 basis
    8,000,000 PENDING. Approving deal2 while including its own basis would
    wrongly cross the 10,000,000 volume threshold."""
    ctx = ctx_pending_deal(6_000_000, with_partner=True, partner_fee_bps=2500, phone="+15125550030")
    deal1 = approve_deal_as_leader(ctx["deal"]["id"], ctx["leader"]["id"])

    lead2 = intake_lead(
        ctx["team"]["id"], ctx["source"]["id"], "+15125550031",
        contact_name="Buyer Two", contact_email="b2@x.com",
        expected_close_price_cents=50_000_000,
        referral_partner_id=ctx["partner"]["id"],
    )
    work_lead(lead2["id"], ctx["closer"]["id"])
    deal2 = create_deal_as_agent(lead2["id"], ctx["closer"]["id"], 8_000_000)
    ctx["deal1"] = deal1
    ctx["deal2"] = deal2
    return ctx


def test_first_deal_pays_base_fee_below_volume_threshold(api):
    """PRD §3.6: "When the partner's calendar-year approved volume, measured as the sum of `split_basis_cents` over that partner's other deals in `APPROVED` or `PAID_OUT` status with `approved_at` inside the current calendar year of the logical clock, reaches at least 10000000 cents, the `effective_fee_bps` applied is the base fee plus 500 basis points; below the threshold the base fee applies."

    Design: Difficulty/combinatorial_formula/referral_fee_volume_tier_excludes_current_deal
    """
    ctx = _two_deal_tier_setup(api)
    deal1 = ctx["deal1"]
    assert deal1["status"] == "APPROVED"
    assert deal1["effective_fee_bps"] == 2500, "YTD volume excluding deal1 was 0"
    assert deal1["referral_fee_cents"] == 1_500_000
    assert_waterfall_conservation(deal1)


def test_current_deal_excluded_from_its_own_tier_volume(api):
    """PRD §3.6: "Volume exactly at the threshold qualifies for the premium, and the deal being computed never counts toward the volume that sets its own tier."
    PRD §3.6: "When the partner's calendar-year approved volume, measured as the sum of `split_basis_cents` over that partner's other deals in `APPROVED` or `PAID_OUT` status with `approved_at` inside the current calendar year of the logical clock, reaches at least 10000000 cents, the `effective_fee_bps` applied is the base fee plus 500 basis points; below the threshold the base fee applies."

    Design: Difficulty/combinatorial_formula/referral_fee_volume_tier_excludes_current_deal
    """
    ctx = _two_deal_tier_setup(api)
    approved2 = approve_deal_as_leader(ctx["deal2"]["id"], ctx["leader"]["id"])
    assert approved2["effective_fee_bps"] == 2500, (
        "YTD excluding deal2 is 6,000,000 < 10,000,000; its own 8,000,000 must not count"
    )
    assert approved2["referral_fee_cents"] == 2_000_000
    assert_waterfall_conservation(approved2)

    deal1_after = get_deal(ctx["deal1"]["id"])
    assert deal1_after["referral_fee_cents"] == 1_500_000, "Tier snapshot is immutable"


# ─── Difficulty: dispute / re-approve money conservation ─────────────────────


def _dispute_setup(api):
    """Deal gross 1,000,000 with partner 2500 bps; approved with actual
    1,100,000; disputed by admin."""
    ctx = ctx_pending_deal(1_000_000, with_partner=True, partner_fee_bps=2500, phone="+15125550091")
    deal = ctx["deal"]
    assert deal["referral_fee_cents"] == 250_000
    assert deal["house_share_cents"] == 225_000
    assert deal["agent_pool_cents"] == 525_000
    assert_waterfall_conservation(deal)
    approved = approve_deal_as_leader(
        deal["id"], ctx["leader"]["id"], {"actual_gross_commission_cents": 1_100_000}
    )
    return ctx, approved


def test_approve_with_actual_then_dispute_retains_split_fields(api):
    """PRD §3.6: "The lead remains `CLOSED_WON`, and the split fields are retained until a corrected re-approval replaces the basis with the corrected actual figure and recomputes every derived field."
    PRD §3.6: "This pinned order — basis, then referral fee, then house share, then pool, then A, then B — guarantees money conservation: the referral fee plus the house share plus the sum of the agent shares always equals the basis exactly."

    Design: Difficulty/compensating_invariant/dispute_reapprove_preserves_money_conservation
    """
    ctx, approved = _dispute_setup(api)
    assert approved["split_basis_cents"] == 1_100_000
    assert approved["referral_fee_cents"] == 275_000
    assert approved["house_share_cents"] == 247_500
    assert approved["agent_pool_cents"] == 577_500
    assert_waterfall_conservation(approved)

    disputed = validate_success(
        api.dispute_deal(approved["id"], {"reason": "lender credit corrected"}, ADMIN), 200
    )
    assert disputed["status"] == "DISPUTED"
    assert disputed["split_basis_cents"] == 1_100_000
    assert disputed["referral_fee_cents"] == 275_000
    assert disputed["house_share_cents"] == 247_500
    assert disputed["agent_pool_cents"] == 577_500
    assert_waterfall_conservation(disputed)


def test_reapprove_with_corrected_actual_recomputes_without_drift(api):
    """PRD §3.6: "The lead remains `CLOSED_WON`, and the split fields are retained until a corrected re-approval replaces the basis with the corrected actual figure and recomputes every derived field."
    PRD §3.6: "This pinned order — basis, then referral fee, then house share, then pool, then A, then B — guarantees money conservation: the referral fee plus the house share plus the sum of the agent shares always equals the basis exactly."

    Design: Difficulty/compensating_invariant/dispute_reapprove_preserves_money_conservation
    """
    ctx, approved = _dispute_setup(api)
    validate_success(
        api.dispute_deal(approved["id"], {"reason": "lender credit corrected"}, ADMIN), 200
    )

    reapproved = approve_deal_as_leader(
        approved["id"], ctx["leader"]["id"], {"actual_gross_commission_cents": 900_000}
    )
    assert reapproved["status"] == "APPROVED"
    assert reapproved["split_basis_type"] == "ACTUAL"
    assert reapproved["split_basis_cents"] == 900_000
    assert reapproved["referral_fee_cents"] == 225_000
    assert reapproved["house_share_cents"] == 202_500
    assert reapproved["agent_pool_cents"] == 472_500
    assert reapproved["agent_shares"] == [
        {"agent_id": ctx["closer"]["id"], "amount_cents": 472_500}
    ]
    assert_waterfall_conservation(reapproved)


# ─── Difficulty: temporal-vs-constraint validation priority ──────────────────


def _split_priority_setup(api):
    """Two ACTIVE agents with an existing ACTIVE agreement [08-01, 09-01)."""
    team = create_team()
    a1 = create_agent(team["id"], "LIC-A1", display_name="Agent One")
    a2 = create_agent(team["id"], "LIC-A2", display_name="Agent Two")
    create_split_agreement(
        team["id"], a1["id"], a2["id"], effective_until="2026-09-01T00:00:00Z"
    )
    return team, a1, a2


def test_split_overlap_and_bad_sum_temporal_beats_constraint(api):
    """PRD §2.8: "Every request is screened against eleven tiers of checks in a fixed priority order, and a request that violates several tiers surfaces only the earliest failure."
    PRD §2.8: "Seventh, the temporal overlap rules of §3.1 and §3.6 (`ERR_TIME_OFF_OVERLAP`, `ERR_SPLIT_WINDOW_OVERLAP`). Eighth, structural cross-field rules — split shares summing to exactly 10000 basis points, split agent pair validity, and referral partner presence — surfacing the HTTP 422 codes."

    Design: Difficulty/priority_pair_validation_conflict/split_overlap_and_bad_sum_temporal_beats_constraint
    """
    team, a1, a2 = _split_priority_setup(api)
    res = api.create_split_agreement(
        split_agreement_payload(
            team["id"], a1["id"], a2["id"],
            a_share_bps=4000, b_share_bps=4000,
            effective_from="2026-08-15T00:00:00Z",
        ),
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_SPLIT_WINDOW_OVERLAP, expected_status=409)


def test_split_bad_sum_alone_surfaces_share_sum_error(api):
    """PRD §3.6: "The two shares must sum to exactly 10000 basis points, else `ERR_SPLIT_SHARE_SUM_INVALID` (HTTP 422), and the pair must be two distinct `ACTIVE` agents of the same team, else `ERR_SPLIT_AGENT_PAIR_INVALID` (HTTP 422)."
    PRD §3.6: "A new agreement whose window overlaps an `ACTIVE` agreement for the same unordered agent pair is rejected with `ERR_SPLIT_WINDOW_OVERLAP` (HTTP 409) under half-open semantics: adjacency is allowed, so a new agreement whose `effective_from` equals the existing agreement's `effective_until` does not conflict."

    Design: Difficulty/priority_pair_validation_conflict/split_overlap_and_bad_sum_temporal_beats_constraint
    """
    team, a1, a2 = _split_priority_setup(api)
    res = api.create_split_agreement(
        split_agreement_payload(
            team["id"], a1["id"], a2["id"],
            a_share_bps=4000, b_share_bps=4000,
            effective_from="2026-09-01T00:00:00Z",  # adjacent: no overlap
            effective_until="2026-10-01T00:00:00Z",
        ),
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_SPLIT_SHARE_SUM_INVALID, expected_status=422)


# ─── Difficulty: half-open window adjacency (unordered pair) ─────────────────


def test_split_agreement_adjacent_window_allowed(api):
    """PRD §3.6: "A new agreement whose window overlaps an `ACTIVE` agreement for the same unordered agent pair is rejected with `ERR_SPLIT_WINDOW_OVERLAP` (HTTP 409) under half-open semantics: adjacency is allowed, so a new agreement whose `effective_from` equals the existing agreement's `effective_until` does not conflict."

    Design: Difficulty/resource_temporal_overlap/split_agreement_half_open_adjacency_allowed
    """
    team, a1, a2 = _split_priority_setup(api)
    adjacent = validate_success(
        api.create_split_agreement(
            split_agreement_payload(
                team["id"], a1["id"], a2["id"],
                a_share_bps=6000, b_share_bps=4000,
                effective_from="2026-09-01T00:00:00Z",
                effective_until="2026-10-01T00:00:00Z",
            ),
            ADMIN,
        ),
        201,
    )
    assert adjacent["status"] == "ACTIVE"


def test_split_agreement_mid_window_overlap_rejected_for_unordered_pair(api):
    """PRD §3.6: "A new agreement whose window overlaps an `ACTIVE` agreement for the same unordered agent pair is rejected with `ERR_SPLIT_WINDOW_OVERLAP` (HTTP 409) under half-open semantics: adjacency is allowed, so a new agreement whose `effective_from` equals the existing agreement's `effective_until` does not conflict."

    Design: Difficulty/resource_temporal_overlap/split_agreement_half_open_adjacency_allowed
    """
    team, a1, a2 = _split_priority_setup(api)
    # Agents passed in the swapped order: the pair rule is unordered.
    res = api.create_split_agreement(
        split_agreement_payload(
            team["id"], a2["id"], a1["id"],
            effective_from="2026-08-15T00:00:00Z",
        ),
        ADMIN,
    )
    validate_error(res, ApiErrorId.ERR_SPLIT_WINDOW_OVERLAP, expected_status=409)


# ─── Difficulty: approval cascade (lead closure, nurture exit, tier) ─────────


def _approval_cascade_setup(api):
    """Claimed COLD lead enrolled in an ACTIVE COLD campaign, worked to
    WORKING, deal gross 500,000 PENDING."""
    ctx = ctx_claimed_lead_with_campaign()  # ACTIVE COLD campaign, lead CLAIMED COLD
    agent = ctx["agents"][0]
    log_response_as(ctx["lead"]["id"], agent["id"])  # CLAIMED -> WORKING
    enrollment = enroll_as_leader(ctx["campaign"]["id"], ctx["lead"]["id"], ctx["leader"]["id"])
    deal = create_deal_as_agent(ctx["lead"]["id"], agent["id"], 500_000)
    ctx["enrollment"] = enrollment
    ctx["deal"] = deal
    return ctx


def test_approval_closes_lead_and_releases_capacity(api):
    """PRD §3.6: "Approval cascades to the lead: it becomes `CLOSED_WON`, the closing agent's `active_lead_count` decrements, `trailing_90d_conversions` is recomputed and the agent's tier re-evaluated, and any `ENROLLED` or `PAUSED` nurture enrollment for the lead exits with `exit_reason` `CONVERTED`."

    Design: Difficulty/transitive_cascade/deal_approval_cascade_closes_lead_exits_nurture_recomputes_tier
    """
    ctx = _approval_cascade_setup(api)
    agent = ctx["agents"][0]
    assert get_agent(agent["id"])["active_lead_count"] == 1

    approved = approve_deal_as_leader(ctx["deal"]["id"], ctx["leader"]["id"])
    assert approved["status"] == "APPROVED"
    assert get_lead(ctx["lead"]["id"])["status"] == "CLOSED_WON"
    assert get_agent(agent["id"])["active_lead_count"] == 0


def test_approval_exits_enrollment_converted_and_recomputes_tier(api):
    """PRD §3.6: "Approval cascades to the lead: it becomes `CLOSED_WON`, the closing agent's `active_lead_count` decrements, `trailing_90d_conversions` is recomputed and the agent's tier re-evaluated, and any `ENROLLED` or `PAUSED` nurture enrollment for the lead exits with `exit_reason` `CONVERTED`."
    PRD §3.7: "`PLATINUM` requires at least 8 trailing-90-day conversions together with an average first response of at most 300 seconds (five minutes); `GOLD` requires at least 4 conversions together with an average of at most 900 seconds (fifteen minutes); `SILVER` requires at least 1 conversion; anything else is `BRONZE`."

    Design: Difficulty/transitive_cascade/deal_approval_cascade_closes_lead_exits_nurture_recomputes_tier
    """
    ctx = _approval_cascade_setup(api)
    agent = ctx["agents"][0]
    approve_deal_as_leader(ctx["deal"]["id"], ctx["leader"]["id"])

    agent_after = get_agent(agent["id"])
    assert agent_after["trailing_90d_conversions"] == 1
    assert agent_after["performance_tier"] == "SILVER", "1 >= 1 conversion threshold"

    enr_after = get_enrollment(ctx["enrollment"]["id"])
    assert enr_after["status"] == "EXITED"
    assert enr_after["exit_reason"] == "CONVERTED"
