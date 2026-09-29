"""Funding a resolution: the hammer cap, the three-way minimum, and the split.

The insurer's share is decided before it is divided, and the division is where
the cents live: each part's share is rounded first and only then does the residual
land on one nominated part. Where the claim type narrows the eligible set, the
same split has to leave the other parts alone and walk up the tower.
"""

import pytest
from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    FIRST_ADJUSTER_USER_ID,
    SECOND_ADJUSTER_USER_ID,
    assert_limit_conservation,
    assert_money,
    assert_parts_sum_to_share,
    assert_settlement_proposal,
    fund_resolution,
    make_claims_adjuster_headers,
    read_claim,
    read_coverage_parts,
    read_layers,
    read_policy,
    read_settlement_proposals,
    recommend_settlement,
    resolve_claim_payload,
    respond_to_settlement,
    setup_bound_policy,
    setup_claim_with_answered_proposal,
    setup_claim_with_coverage_accepted,
    side_a_part,
    side_b_part,
    side_c_part,
    subscribe_layer,
)

# A retention of 4,000,000 against a 10,000,000 / 5,000,000 programme, so the
# three ACTIVE parts give a split basis of 25,000,000 in the ratio 10 : 10 : 5.
HIGH_RETENTION = {
    "submission_overrides": {"requested_retention_usd": 4_000_000},
    "quote_overrides": {"offered_retention_usd": 4_000_000},
}
REFUSED_RECOMMENDATION = 6_000_011.30

IVI_CLAIM = {
    "claim_type": "INSURED_VS_INSURED",
    "claimant_name": "Ellery Vance, derivative plaintiff",
    "claimant_capacity": "SHAREHOLDER_DERIVATIVE",
    "wrongful_act_date": "2026-06-10T00:00:00Z",
    "alleged_damages_usd": 9_000_000,
}
DERIVATIVE_CARVEBACK = {
    "exclusion_type": "INSURED_VS_INSURED",
    "wording_variant": "DERIVATIVE_CARVEBACK",
    "premium_impact_pct": 0.00,
}


def _claim_awaiting_funding_after_a_refusal():
    """A securities claim in SETTLEMENT_PENDING whose 6,000,011.30 recommendation
    the insured refused, over three un-eroded coverage parts."""
    return setup_claim_with_answered_proposal(
        response="REFUSE", recommended_amount_usd=REFUSED_RECOMMENDATION,
        **HIGH_RETENTION,
    )


def test_the_indemnity_split_rounds_each_part_before_the_residual_is_placed(api):
    """PRD 3.9: "each part's share is `insurer_share_usd` multiplied by that part's
    `remaining_limit_usd` divided by the basis, rounded half-up to 2 decimal places
    first, part by part in creation order. The residual — `insurer_share_usd` less
    the sum of those rounded shares, rounded to 2 decimal places, and possibly
    negative — is then added to the share of the part with the greatest
    `remaining_limit_usd`, and where two parts tie on `remaining_limit_usd` the one
    with the earlier `created_at` takes it. Rounding each share once at the end from
    unrounded values is not an acceptable substitute: the parts must sum to
    `insurer_share_usd` exactly."

    Design: Difficulty/combinatorial_formula/settlement_split_round_per_part_then_residual
    """
    scenario = _claim_awaiting_funding_after_a_refusal()
    policy_id = scenario["policy"]["id"]

    before = read_coverage_parts(policy_id)
    assert [p["status"] for p in before] == ["ACTIVE"] * 3
    assert side_a_part(before)["remaining_limit_usd"] == pytest.approx(
        10_000_000, abs=0.01
    )
    assert side_b_part(before)["remaining_limit_usd"] == pytest.approx(
        10_000_000, abs=0.01
    )
    assert side_c_part(before)["remaining_limit_usd"] == pytest.approx(
        5_000_000, abs=0.01
    )

    settled = fund_resolution(scenario["claim"]["id"], REFUSED_RECOMMENDATION)

    assert settled["status"] == "SETTLED"
    # 0.70 x (6,000,011.30 - 4,000,000), the least of the three quantities.
    assert_money(settled["insurer_share_usd"], 1_400_007.91, "insurer_share_usd")

    parts = read_coverage_parts(policy_id)
    # 1,400,007.91 x 10/25 == 560,003.164 and x 5/25 == 280,001.582, each rounded
    # half-up on its own before the 0.01 residual is placed.
    assert_money(side_a_part(parts)["eroded_usd"], 560_003.17, "SIDE_A eroded_usd")
    assert_money(side_b_part(parts)["eroded_usd"], 560_003.16, "SIDE_B eroded_usd")
    assert_money(side_c_part(parts)["eroded_usd"], 280_001.58, "SIDE_C eroded_usd")
    assert side_a_part(parts)["eroded_usd"] > side_b_part(parts)["eroded_usd"], (
        "the residual lands on SIDE_A: it ties SIDE_B on remaining_limit_usd and has "
        "the earlier created_at"
    )
    assert_parts_sum_to_share(parts, 1_400_007.91)
    assert_money(side_a_part(parts)["remaining_limit_usd"], 9_439_996.83, "SIDE_A left")
    assert_money(side_b_part(parts)["remaining_limit_usd"], 9_439_996.84, "SIDE_B left")
    assert_money(side_c_part(parts)["remaining_limit_usd"], 4_719_998.42, "SIDE_C left")
    assert [p["status"] for p in parts] == ["ACTIVE"] * 3, (
        "no part's share reaches its limit, so none is exhausted"
    )

    policy = read_policy(policy_id)
    assert_money(policy["total_eroded_usd"], 1_400_007.91, "total_eroded_usd")
    assert_money(policy["aggregate_remaining_usd"], 8_599_992.09, "aggregate_remaining")
    assert_limit_conservation(policy)
    assert policy["tower_posture"] == "ERODED"
    assert policy["open_claim_count"] == 0


def test_the_stored_refusal_cap_is_what_binds_the_insurer_share(api):
    """PRD 3.9: "On `REFUSE`, the proposal moves `RECOMMENDED → REFUSED` and
    `hammer_pct_applied` is 0.70 — the insurer will bear seventy percent of the
    excess over the retention and no more. In both branches
    `insurer_indemnity_cap_usd` is `hammer_pct_applied` multiplied by the recommended
    amount less the retention baseline, floored at 0 before the multiplication where
    the retention exceeds the recommended amount, rounded half-up to 2 decimal places
    once at this point; that stored value is reused verbatim at resolution and never
    recomputed." PRD 3.9: "`insurer_share_usd` is the least of three quantities: the
    final resolution amount less the retention baseline floored at 0; the proposal's
    stored `insurer_indemnity_cap_usd`; and the policy's `aggregate_remaining_usd`."

    Design: Difficulty/combinatorial_formula/settlement_split_round_per_part_then_residual
    """
    scenario = _claim_awaiting_funding_after_a_refusal()
    proposal = scenario["proposal"]

    assert_settlement_proposal(proposal)
    assert proposal["insured_response"] == "REFUSE"
    assert proposal["status"] == "REFUSED"
    assert proposal["hammer_pct_applied"] == pytest.approx(0.70)
    assert_money(proposal["insurer_indemnity_cap_usd"], 1_400_007.91,
                 "insurer_indemnity_cap_usd")

    settled = fund_resolution(scenario["claim"]["id"], REFUSED_RECOMMENDATION)

    assert settled["hammer_applied"] is True
    assert_money(settled["retention_applied_usd"], 4_000_000.00, "retention_applied")
    assert_money(settled["retention_remaining_usd"], 0.00, "retention_remaining")
    # The cap 1,400,007.91 is below F - R == 2,000,011.30 and far below the
    # aggregate 10,000,000.00, so the middle quantity governs.
    assert_money(settled["insurer_share_usd"], 1_400_007.91, "insurer_share_usd")
    assert_money(settled["indemnity_paid_usd"], 1_400_007.91, "indemnity_paid_usd")
    assert_money(settled["insured_retained_usd"], 4_600_003.39, "insured_retained_usd")
    assert settled["insurer_share_usd"] < REFUSED_RECOMMENDATION - 4_000_000

    funded = {p["id"]: p for p in read_settlement_proposals(scenario["claim"]["id"])}
    after = funded[proposal["id"]]
    assert after["status"] == "HAMMER_APPLIED"
    assert_money(after["insurer_indemnity_cap_usd"], 1_400_007.91, "the stored cap")
    assert after["hammer_pct_applied"] == pytest.approx(0.70)


def _consented_ivi_claim_on_a_two_band_tower():
    """A 5,000,000 policy with no Side C part under a contiguous 0-5M / 5M-10M
    tower, carrying an insured-versus-insured claim whose 7,000,000 recommendation
    the insured has consented to."""
    scenario = setup_bound_policy(
        agreed_terms=[DERIVATIVE_CARVEBACK],
        submission_overrides={
            "requested_limit_usd": 5_000_000,
            "requested_side_c_sublimit_usd": 0,
            "requested_program_target_limit_usd": 10_000_000,
        },
        quote_overrides={
            "offered_limit_usd": 5_000_000,
            "offered_side_c_sublimit_usd": 0,
        },
    )
    policy_id = scenario["policy"]["id"]
    scenario["primary_layer"] = subscribe_layer(
        policy_id, carrier_name="Meridian Primary", attachment_point_usd=0,
        limit_usd=5_000_000, participation_pct=1.00,
    )
    scenario["excess_layer"] = subscribe_layer(
        policy_id, carrier_name="Northgate Excess", attachment_point_usd=5_000_000,
        limit_usd=5_000_000, participation_pct=1.00,
        underlying_layer_id=scenario["primary_layer"]["id"],
    )
    return setup_claim_with_answered_proposal(
        response="CONSENT", recommended_amount_usd=7_000_000,
        policy_scenario=scenario, claim_overrides=IVI_CLAIM,
    )


def test_an_insured_versus_insured_settlement_erodes_side_a_and_the_layer_beneath_it(api):
    """PRD 3.8: "An `INSURED_VS_INSURED` claim may reach `SIDE_A` only." PRD 3.9:
    "Each part's `eroded_usd` then rises by its assigned share and its
    `remaining_limit_usd` becomes its `limit_usd` less its `eroded_usd`, and any part
    whose `eroded_usd` reaches or passes its `limit_usd` moves `ACTIVE → EXHAUSTED`."
    PRD 3.9: "the policy's `total_eroded_usd` is re-summed and its
    `aggregate_remaining_usd` re-derived, every layer still `ATTACHED` whose
    `attachment_point_usd` is below the new `total_eroded_usd` moves `ATTACHED →
    EXHAUSTED`, and the policy's `tower_posture` re-derives to `ERODED`."

    Design: Difficulty/transitive_cascade/settlement_erosion_exhausts_part_layer_tower
    """
    scenario = _consented_ivi_claim_on_a_two_band_tower()
    policy_id = scenario["policy"]["id"]

    before = read_policy(policy_id)
    assert_money(before["placed_limit_usd"], 10_000_000, "placed_limit_usd")
    assert before["tower_posture"] == "CONTIGUOUS"
    assert_money(before["total_eroded_usd"], 0, "total_eroded_usd")
    assert_money(before["aggregate_remaining_usd"], 5_000_000, "aggregate_remaining")
    assert before["open_claim_count"] == 1
    assert {p["part"] for p in read_coverage_parts(policy_id)} == {"SIDE_A", "SIDE_B"}

    settled = fund_resolution(scenario["claim"]["id"], 7_000_000)

    # Hop 1: the consent cap 6,750,000.00 and F - R 6,750,000.00 are both cut down
    # by the policy's aggregate_remaining_usd of 5,000,000.00.
    assert settled["status"] == "SETTLED"
    assert settled["hammer_applied"] is False
    assert_money(settled["retention_applied_usd"], 250_000.00, "retention_applied")
    assert_money(settled["retention_remaining_usd"], 0.00, "retention_remaining")
    assert_money(settled["insurer_share_usd"], 5_000_000.00, "insurer_share_usd")
    assert_money(settled["indemnity_paid_usd"], 5_000_000.00, "indemnity_paid_usd")
    assert_money(settled["insured_retained_usd"], 2_000_000.00, "insured_retained_usd")

    # Hops 2 and 3: the eligible set is SIDE_A alone, so the whole share lands there
    # and takes it to its limit.
    parts = read_coverage_parts(policy_id)
    assert_money(side_a_part(parts)["eroded_usd"], 5_000_000.00, "SIDE_A eroded_usd")
    assert_money(side_a_part(parts)["remaining_limit_usd"], 0.00, "SIDE_A left")
    assert side_a_part(parts)["status"] == "EXHAUSTED"
    assert_money(side_b_part(parts)["eroded_usd"], 0.00, "SIDE_B eroded_usd")
    assert_money(side_b_part(parts)["remaining_limit_usd"], 5_000_000.00, "SIDE_B left")
    assert side_b_part(parts)["status"] == "ACTIVE", (
        "SIDE_B carries an identical 5,000,000 limit and is still untouched"
    )
    assert_parts_sum_to_share(parts, 5_000_000.00)

    # Hop 4: only the band strictly below the new erosion goes out.
    layers = {layer["id"]: layer for layer in read_layers(policy_id)}
    assert layers[scenario["primary_layer"]["id"]]["status"] == "EXHAUSTED"
    assert layers[scenario["excess_layer"]["id"]]["status"] == "ATTACHED", (
        "5,000,000 is not below 5,000,000"
    )

    after = read_policy(policy_id)
    assert_money(after["total_eroded_usd"], 5_000_000.00, "total_eroded_usd")
    assert_money(after["aggregate_remaining_usd"], 0.00, "aggregate_remaining_usd")
    assert_limit_conservation(after)
    assert after["tower_posture"] == "ERODED"
    assert_money(after["placed_limit_usd"], 10_000_000, "placed_limit_usd")
    assert after["open_claim_count"] == 0


def test_a_funded_claim_is_final_and_leaves_no_aggregate_for_the_next_one(api):
    """PRD 3.9: the resolution moves the claim `SETTLEMENT_PENDING → SETTLED` and
    "The claim must be `SETTLEMENT_PENDING`, or the request is refused with
    `ERR_INVALID_CLAIM_STATE`." PRD 3.9: "the policy's `aggregate_remaining_usd` must
    be strictly greater than 0, or the request is refused with
    `ERR_LIMIT_EXHAUSTED`." PRD 3.9: "The governing proposal reaches its own terminus
    in the same call: `CONSENTED → FUNDED` when the `insured_response` was `CONSENT`".

    Design: Difficulty/transitive_cascade/settlement_erosion_exhausts_part_layer_tower
    """
    scenario = _consented_ivi_claim_on_a_two_band_tower()
    policy_id = scenario["policy"]["id"]
    claim_id = scenario["claim"]["id"]

    fund_resolution(claim_id, 7_000_000)

    proposals = {p["id"]: p for p in read_settlement_proposals(claim_id)}
    governing = proposals[scenario["proposal"]["id"]]
    assert governing["status"] == "FUNDED"
    assert governing["hammer_pct_applied"] == pytest.approx(1.00)
    assert_money(governing["insurer_indemnity_cap_usd"], 6_750_000.00,
                 "insurer_indemnity_cap_usd")
    assert governing["insurer_indemnity_cap_usd"] > 5_000_000.00, (
        "the stored cap is not rewritten by the smaller amount actually funded"
    )

    # Re-funding the same claim is refused on its state, and nothing moves.
    validate_error(
        api.resolve_claim(
            claim_id, resolve_claim_payload(7_000_000),
            make_claims_adjuster_headers(SECOND_ADJUSTER_USER_ID),
        ),
        ApiErrorId.ERR_INVALID_CLAIM_STATE,
        409,
    )
    replayed = read_claim(claim_id)
    assert replayed["status"] == "SETTLED"
    assert_money(replayed["indemnity_paid_usd"], 5_000_000.00, "indemnity_paid_usd")
    assert_money(read_policy(policy_id)["total_eroded_usd"], 5_000_000.00,
                 "total_eroded_usd")

    # A fresh claim on the same policy gets all the way to the fiscal gate.
    successor = setup_claim_with_coverage_accepted(
        policy_scenario=scenario, notice_clock=None,
        claim_overrides=dict(IVI_CLAIM, claimant_name="Rowan Ash, derivative plaintiff"),
    )["claim"]
    proposal = recommend_settlement(successor["id"], 1_000_000)
    respond_to_settlement(proposal["id"], scenario["insured"]["id"], "CONSENT")

    validate_error(
        api.resolve_claim(
            successor["id"], resolve_claim_payload(1_000_000),
            make_claims_adjuster_headers(SECOND_ADJUSTER_USER_ID),
        ),
        ApiErrorId.ERR_LIMIT_EXHAUSTED,
        409,
    )
    assert read_claim(successor["id"])["status"] == "SETTLEMENT_PENDING"
    assert read_policy(policy_id)["open_claim_count"] == 1
    assert governing["recommended_by_user_id"] == FIRST_ADJUSTER_USER_ID, (
        "the recommending adjuster is recorded, and it is not the one who funded"
    )
