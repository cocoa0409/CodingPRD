"""Boundary and rounding edges in peer sizing, goal adjustment and the say-on-pay vote.

Three of the PRD's thresholds are decided at the exact digit where the value is
rounded: the closed size bands are tested against a four-decimal revenue ratio,
the fifteen-percent goal-adjustment limit against a two-decimal derived
percentage, and the say-on-pay floors against a support percentage measured on
votes cast alone. Each behaviour is probed on both sides of its edge.
"""

import pytest

from test_helpers import (
    CHAIR,
    CHAIR_TWO_HEADERS,
    CONSULTANT,
    ApiErrorId,
    add_member_payload,
    add_peer_member,
    adjustment_payload,
    api_client,
    assert_money,
    assert_ratio,
    create_company,
    create_peer_group,
    metric_version,
    peer_group_version,
    read_metric,
    read_pay_program,
    read_peer_group,
    read_peer_group_members,
    setup_disclosed_program,
    setup_issuer,
    setup_pay_program,
    validate_error,
    validate_success,
    vote_certification_payload,
)


# ===========================================================================
# The closed size bands, decided at the fourth decimal of the revenue ratio
# ===========================================================================
def _draft_group_with_band_edge_peers():
    """ACME issuer, a DRAFT group and the three peers that straddle 2.0000.

    DLTA's revenue is exactly twice the issuer's, GAMM is 2.00004 times it and
    HOTL 2.00005 times it; all three carry a market capitalisation ratio of
    2.0000, well inside that band.
    """
    env = setup_issuer()
    for ticker in ("DLTA", "GAMM", "HOTL"):
        env["peers"][ticker] = create_company(ticker)
    env["peer_group"] = create_peer_group(env["issuer"]["id"])
    return env


def test_revenue_ratio_rounding_admits_the_band_edge_and_rejects_the_next_tick():
    """A ratio rounding to 2.0000 is admitted; one rounding to 2.0001 is refused.

    The band test reads the stored four-decimal ratio, and "The peer's revenue
    divided by the issuer's revenue, rounded half-up to four decimal places, is
    stored as `revenue_ratio`; the peer's market capitalisation divided by the
    issuer's market capitalisation, rounded the same way, is stored as
    `market_cap_ratio`." The edge itself is inclusive: "Both bands are
    **closed**: a ratio exactly equal to a bound is inside the band."

    Design: Difficulty/boundary_precision_check/revenue_ratio_rounds_to_band_edge_accepted_then_next_tick_rejected
    """
    env = _draft_group_with_band_edge_peers()
    group_id = env["peer_group"]["id"]

    # Exactly at the upper bound: inside the closed band.
    dlta = add_peer_member(group_id, env["peers"]["DLTA"]["id"], "SIZE_MATCH")
    assert_ratio(dlta["revenue_ratio"], 2.0000, "revenue_ratio")
    assert_ratio(dlta["market_cap_ratio"], 2.0000, "market_cap_ratio")
    assert dlta["in_size_band"] is True
    assert dlta["status"] == "ACCEPTED"

    # True ratio 2.00004 rounds down to the bound, so the peer is still inside.
    gamm = add_peer_member(group_id, env["peers"]["GAMM"]["id"], "SIZE_MATCH")
    assert gamm["revenue_ratio"] == pytest.approx(2.0000, abs=0.000001), (
        "revenue_ratio must be the rounded 2.0000, not the raw 2.00004"
    )
    assert gamm["in_size_band"] is True

    # True ratio 2.00005 rounds half-up to 2.0001 and leaves the band.
    version_before = peer_group_version(group_id)
    response = api_client.add_peer_group_member(
        group_id,
        add_member_payload(env["peers"]["HOTL"]["id"], version_before, "SIZE_MATCH"),
        CONSULTANT,
    )

    validate_error(response, ApiErrorId.ERR_PEER_OUTSIDE_SIZE_BAND, 422)

    members = read_peer_group_members(group_id)
    assert len(members) == 2, "the rejected candidate must not leave a membership row"
    assert env["peers"]["HOTL"]["id"] not in [row["peer_company_id"] for row in members]
    assert read_peer_group(group_id)["version"] == version_before


def test_out_of_band_peer_is_admitted_on_a_documented_rationale():
    """The same 2.0001 peer joins when the rationale waives the band.

    Nothing about the ratio changes; only the reason does, and the PRD makes the
    reason decisive: "A candidate that fails either band is still admissible, but
    only on a documented rationale — an `inclusion_reason` of
    `BUSINESS_MODEL_ANALOG` or `TALENT_COMPETITOR` permits an out-of-band peer,
    whereas `SIZE_MATCH` or `INDUSTRY_MATCH` does not and the add is rejected
    with `ERR_PEER_OUTSIDE_SIZE_BAND`."

    Design: Difficulty/boundary_precision_check/revenue_ratio_rounds_to_band_edge_accepted_then_next_tick_rejected
    """
    env = _draft_group_with_band_edge_peers()
    group_id = env["peer_group"]["id"]

    response = api_client.add_peer_group_member(
        group_id,
        add_member_payload(
            env["peers"]["HOTL"]["id"], peer_group_version(group_id), "BUSINESS_MODEL_ANALOG"
        ),
        CONSULTANT,
    )

    data = validate_success(response, 201)
    assert data["revenue_ratio"] == pytest.approx(2.0001, abs=0.000001), (
        "revenue_ratio must be the rounded 2.0001, not the raw 2.00005"
    )
    assert data["in_size_band"] is False
    assert data["status"] == "ACCEPTED"

    # The same peer under a non-waiving rationale is a different peer group.
    other = create_peer_group(env["issuer"]["id"])
    refused = api_client.add_peer_group_member(
        other["id"],
        add_member_payload(
            env["peers"]["HOTL"]["id"], peer_group_version(other["id"]), "INDUSTRY_MATCH"
        ),
        CONSULTANT,
    )
    validate_error(refused, ApiErrorId.ERR_PEER_OUTSIDE_SIZE_BAND, 422)


def test_lower_size_band_bounds_are_closed_and_the_next_tick_down_is_refused():
    """Ratios of exactly 0.5000 and 0.2500 sit inside; 0.4999 does not.

    Both bands are tested at their floors, where "The membership's `in_size_band`
    is true only when the revenue ratio lies between 0.5 and 2.0 and the
    market-capitalisation ratio lies between 0.25 and 4.0."

    Design: Difficulty/boundary_precision_check/revenue_ratio_rounds_to_band_edge_accepted_then_next_tick_rejected
    """
    env = setup_issuer()
    on_edge = create_company(
        "BRVO",
        legal_name="Edge Floor Corp",
        ticker="EDGE",
        revenue_usd=5000000000,
        market_cap_usd=5000000000,
    )
    below_edge = create_company(
        "BRVO",
        legal_name="Tick Below Corp",
        ticker="TICKD",
        revenue_usd=4999400000,
        market_cap_usd=5000000000,
    )
    group_id = create_peer_group(env["issuer"]["id"])["id"]

    member = add_peer_member(group_id, on_edge["id"], "SIZE_MATCH")
    assert_ratio(member["revenue_ratio"], 0.5000, "revenue_ratio")
    assert_ratio(member["market_cap_ratio"], 0.2500, "market_cap_ratio")
    assert member["in_size_band"] is True

    # True ratio 0.49994 rounds to 0.4999, one tick below the closed floor.
    response = api_client.add_peer_group_member(
        group_id,
        add_member_payload(below_edge["id"], peer_group_version(group_id), "SIZE_MATCH"),
        CONSULTANT,
    )
    validate_error(response, ApiErrorId.ERR_PEER_OUTSIDE_SIZE_BAND, 422)
    assert len(read_peer_group_members(group_id)) == 1


# ===========================================================================
# The goal-adjustment policy limit, decided at the second decimal
# ===========================================================================
def _locked_two_metric_program():
    """Two ANNUAL_INCENTIVE metrics on one program, both LOCKED at target 5.00.

    The pair weighs 60.00 and 40.00 so the vehicle's weights total 100.00 and
    committee approval succeeds, snapshotting locked_target_value 5.00 on each.
    """
    env = setup_pay_program(
        metric_curves=("ADJ_EPS_LINEAR", "ADJ_EPS_LINEAR"),
        metric_overrides=[{}, {"metric_code": "FCF", "weight_pct": 40.00}],
    )
    for metric in env["metrics"]:
        locked = read_metric(env["program"]["id"], metric["id"])
        assert locked["status"] == "LOCKED"
        assert_ratio(locked["locked_target_value"], 5.00, "locked_target_value")
    return env


def test_goal_adjustment_rounding_to_exactly_the_policy_limit_is_permitted():
    """A 15.004 percent move rounds to 15.00 and is therefore allowed.

    The magnitude is derived and then rounded before the comparison: "Before the
    adjustment is applied, its magnitude is measured against the snapshot: take
    the new target (the supplied `target_value`, or the metric's existing one if
    the request does not move the target), subtract `locked_target_value`, take
    the absolute value, divide by the absolute value of `locked_target_value`,
    multiply by 100 and round half-up to two decimal places; the result is stored
    as `goal_adjustment_pct`." And "A magnitude of exactly 15.00 percent is
    permitted; anything strictly greater is rejected with
    `ERR_ADJUSTMENT_EXCEEDS_POLICY_LIMIT`."

    Design: Difficulty/boundary_precision_check/goal_adjustment_at_rounded_policy_limit_allowed_then_next_tick_rejected
    """
    env = _locked_two_metric_program()
    program_id = env["program"]["id"]
    metric_id = env["metrics"][0]["id"]

    response = api_client.adjust_incentive_metric(
        metric_id,
        adjustment_payload(metric_version(program_id, metric_id), target_value=5.7502),
        CHAIR_TWO_HEADERS,
    )

    data = validate_success(response, 200)
    assert data["status"] == "ADJUSTED"
    assert_money(data["goal_adjustment_pct"], 15.00, "goal_adjustment_pct")

    adjusted = read_metric(program_id, metric_id)
    assert_ratio(adjusted["target_value"], 5.7502, "target_value")
    assert_ratio(adjusted["locked_target_value"], 5.00, "locked_target_value")
    # Only target_value was named, so the other two goal values stand.
    assert_ratio(adjusted["threshold_value"], 4.00, "threshold_value")
    assert_ratio(adjusted["maximum_value"], 6.00, "maximum_value")


def test_goal_adjustment_rounding_past_the_policy_limit_is_rejected():
    """A 15.052 percent move rounds to 15.05 and breaches the limit.

    One tick further than the permitted edge, so "A magnitude of exactly 15.00
    percent is permitted; anything strictly greater is rejected with
    `ERR_ADJUSTMENT_EXCEEDS_POLICY_LIMIT`."

    Design: Difficulty/boundary_precision_check/goal_adjustment_at_rounded_policy_limit_allowed_then_next_tick_rejected
    """
    env = _locked_two_metric_program()
    program_id = env["program"]["id"]
    metric_id = env["metrics"][1]["id"]
    version_before = metric_version(program_id, metric_id)

    response = api_client.adjust_incentive_metric(
        metric_id,
        adjustment_payload(version_before, target_value=5.7526),
        CHAIR_TWO_HEADERS,
    )

    validate_error(response, ApiErrorId.ERR_ADJUSTMENT_EXCEEDS_POLICY_LIMIT, 422)

    untouched = read_metric(program_id, metric_id)
    assert untouched["status"] == "LOCKED"
    assert_ratio(untouched["target_value"], 5.00, "target_value")
    assert untouched.get("goal_adjustment_pct") is None
    assert untouched["version"] == version_before


def test_goal_adjustment_rounding_up_into_the_policy_limit_is_permitted():
    """A 14.998 percent move rounds up to 15.00 and is still inside the limit.

    The other side of the same rounded edge, again measured against the snapshot:
    "A magnitude of exactly 15.00 percent is permitted; anything strictly greater
    is rejected with `ERR_ADJUSTMENT_EXCEEDS_POLICY_LIMIT`."

    Design: Difficulty/boundary_precision_check/goal_adjustment_at_rounded_policy_limit_allowed_then_next_tick_rejected
    """
    env = _locked_two_metric_program()
    program_id = env["program"]["id"]
    metric_id = env["metrics"][1]["id"]

    response = api_client.adjust_incentive_metric(
        metric_id,
        adjustment_payload(metric_version(program_id, metric_id), target_value=5.7499),
        CHAIR_TWO_HEADERS,
    )

    data = validate_success(response, 200)
    assert data["status"] == "ADJUSTED"
    assert_money(data["goal_adjustment_pct"], 15.00, "goal_adjustment_pct")
    assert_ratio(read_metric(program_id, metric_id)["target_value"], 5.7499, "target_value")


# ===========================================================================
# The say-on-pay floors, measured on votes cast
# ===========================================================================
def test_support_exactly_at_the_pass_floor_passes_and_excludes_abstentions():
    """Half a million each way carries the vote at exactly 50.00 percent.

    The abstentions never enter the denominator: "Support is measured on votes
    cast: the denominator is `votes_for` plus `votes_against`, and `abstentions`
    are recorded for disclosure but deliberately excluded from it." The floor is
    inclusive — "Support of at least 50.00 percent carries the vote; below that it
    fails." — while the responsiveness trigger still bites, since "Exactly 50.00
    passes; exactly 70.00 does *not* trigger enhanced engagement."

    Design: Difficulty/boundary_precision_check/say_on_pay_support_exactly_at_pass_floor_passes_and_excludes_abstentions
    """
    env = setup_disclosed_program()
    program_id = env["program"]["id"]
    assert env["program"]["design_status"] == "DISCLOSED"

    response = api_client.certify_vote(
        program_id, vote_certification_payload(500000, 500000, 250000), CHAIR
    )

    data = validate_success(response, 200)
    # 500,000 / 1,000,000 == 50.00, not 500,000 / 1,250,000 == 40.00.
    assert_money(data["support_pct"], 50.00, "support_pct")
    assert data["vote_status"] == "PASSED"
    assert data["enhanced_engagement_required"] is True
    assert data["design_status"] == "DISCLOSED"

    after = read_pay_program(program_id)
    assert_money(after["support_pct"], 50.00, "support_pct")
    assert after["vote_status"] == "PASSED"
    assert after["enhanced_engagement_required"] is True
    assert after["design_status"] == "DISCLOSED", "a bare majority does not close the program"
    assert after["votes_for"] == 500000
    assert after["votes_against"] == 500000
    assert after["abstentions"] == 250000


def test_support_exactly_at_the_responsiveness_floor_closes_the_program():
    """Seventy percent support clears the trigger and finishes the design cycle.

    Exactly at the second floor: "And independently of pass or fail,
    `enhanced_engagement_required` is set true whenever `support_pct` is strictly
    below 70.00 — the responsiveness trigger — and false otherwise." And "If
    support reached 70.00 or more, the design dimension also advances `DISCLOSED
    → CLOSED` and the program is done."

    Design: Difficulty/boundary_precision_check/say_on_pay_support_exactly_at_pass_floor_passes_and_excludes_abstentions
    """
    env = setup_disclosed_program()
    program_id = env["program"]["id"]

    response = api_client.certify_vote(
        program_id, vote_certification_payload(700000, 300000, 250000), CHAIR
    )

    data = validate_success(response, 200)
    assert_money(data["support_pct"], 70.00, "support_pct")
    assert data["vote_status"] == "PASSED"
    assert data["enhanced_engagement_required"] is False
    assert data["design_status"] == "CLOSED"

    after = read_pay_program(program_id)
    assert after["design_status"] == "CLOSED"
    assert after["enhanced_engagement_required"] is False


def test_support_below_the_pass_floor_fails_the_vote_on_votes_cast():
    """Forty-nine percent of votes cast fails, abstentions notwithstanding.

    The failing side of the inclusive floor, with the denominator again taken
    from votes cast alone: "Support of at least 50.00 percent carries the vote;
    below that it fails."

    Design: Difficulty/boundary_precision_check/say_on_pay_support_exactly_at_pass_floor_passes_and_excludes_abstentions
    """
    env = setup_disclosed_program()
    program_id = env["program"]["id"]

    response = api_client.certify_vote(
        program_id, vote_certification_payload(49, 51, 1000), CHAIR
    )

    data = validate_success(response, 200)
    assert_money(data["support_pct"], 49.00, "support_pct")
    assert data["vote_status"] == "FAILED"
    assert data["enhanced_engagement_required"] is True

    after = read_pay_program(program_id)
    assert after["vote_status"] == "FAILED"
    assert after["design_status"] == "DISCLOSED", "a failed vote does not close a program"
    assert after["abstentions"] == 1000
