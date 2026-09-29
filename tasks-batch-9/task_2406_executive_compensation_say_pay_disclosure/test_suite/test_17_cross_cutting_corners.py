"""Cross-cutting corners: composition version guards, the responsiveness floor,
program-total re-derivation after a forfeiture, and the immediacy of derived
benchmark state in a write response.
"""

from test_helpers import (
    CHAIR_ONE,
    CONSULTANT,
    ApiErrorId,
    add_member_payload,
    adjustment_payload,
    api_client,
    assert_money,
    assert_pay_program,
    assert_payout_award,
    assert_peer_group,
    assert_peer_group_member,
    create_award,
    create_company,
    create_peer_group,
    make_comp_committee_chair_headers,
    peer_group_version,
    read_award,
    read_metric,
    read_pay_program,
    read_peer_group,
    read_peer_group_member,
    set_clock,
    setup_disclosed_program,
    setup_issuer,
    setup_mini_peer_group,
    setup_pay_program,
    settlement_payload,
    validate_error,
    validate_success,
    vote_certification_payload,
)


def test_replayed_peer_group_version_token_is_refused_and_the_refreshed_token_admits_the_peer():
    """A member add must quote the group's live version, not the one first seen.

    "Adding a peer to a peer group requires `expected_peer_group_version` to equal that
    `PeerGroup` row's current `version`; if it does not, the add is rejected with
    `ERR_STALE_PEER_GROUP_VERSION` (HTTP 412), because a membership change legitimately
    supersedes the group's screened medians and benchmark values and a writer holding an older
    view would be composing a peer set against numbers that no longer exist."

    Design: Corner/cross_cutting_layers/a_stale_expected_peer_group_version_is_rejected_with_412
    """
    env = setup_issuer(executive_profiles=())
    bravo = create_company("BRVO")
    charlie = create_company("CHRL")

    group = create_peer_group(env["issuer"]["id"], "RAW_MEDIAN")
    first_token = group["version"]

    # The first add consumes the token the create response carried.
    validate_success(
        api_client.add_peer_group_member(
            group["id"],
            add_member_payload(bravo["id"], first_token, "SIZE_MATCH"),
            CONSULTANT,
        ),
        201,
    )

    # Replaying the same token now addresses a version that has already moved on.
    validate_error(
        api_client.add_peer_group_member(
            group["id"],
            add_member_payload(charlie["id"], first_token, "SIZE_MATCH"),
            CONSULTANT,
        ),
        ApiErrorId.ERR_STALE_PEER_GROUP_VERSION,
        412,
    )

    refused = read_peer_group(group["id"])
    assert_peer_group(refused)
    assert refused["accepted_member_count"] == 1, "the refused add must write nothing"
    assert refused["version"] == first_token + 1
    assert refused["status"] == "DRAFT"

    live_token = peer_group_version(group["id"])
    assert live_token == first_token + 1

    retried = validate_success(
        api_client.add_peer_group_member(
            group["id"],
            add_member_payload(charlie["id"], live_token, "SIZE_MATCH"),
            CONSULTANT,
        ),
        201,
    )
    assert_peer_group_member(retried)
    assert retried["status"] == "ACCEPTED"
    assert read_peer_group_member(group["id"], retried["id"])["status"] == "ACCEPTED"

    after = read_peer_group(group["id"])
    assert after["accepted_member_count"] == 2
    assert after["version"] == first_token + 2
    assert after["status"] == "DRAFT"


def test_metric_version_token_stale_after_program_approval_blocks_the_goal_adjustment():
    """Committee approval bumps the metric's version, so the creation token is stale.

    "Ordering a goal adjustment requires `expected_incentive_metric_version` to equal that
    `IncentiveMetric` row's current `version`, failing with
    `ERR_STALE_INCENTIVE_METRIC_VERSION` (HTTP 412), because an adjustment supersedes the locked
    goal curve and a stale view would measure the policy limit against a target that has already
    moved."

    Design: Corner/cross_cutting_layers/a_stale_expected_incentive_metric_version_is_rejected_with_412
    """
    env = setup_pay_program(
        metric_curves=("ADJ_EPS_LINEAR",),
        metric_overrides=[{"weight_pct": 100.00}],
        approve=True,
    )
    program_id = env["program"]["id"]
    metric = env["metrics"][0]
    creation_token = metric["version"]

    chair = make_comp_committee_chair_headers(CHAIR_ONE)
    reason = "The divestiture of the storage unit removed 0.50 of budgeted EPS."

    validate_error(
        api_client.adjust_incentive_metric(
            metric["id"],
            adjustment_payload(creation_token, reason, target_value=5.50),
            chair,
        ),
        ApiErrorId.ERR_STALE_INCENTIVE_METRIC_VERSION,
        412,
    )

    refused = read_metric(program_id, metric["id"])
    assert refused["status"] == "LOCKED", "the refused adjustment must leave the metric locked"
    assert_money(refused["target_value"], 5.00, "target_value")
    assert refused["version"] == creation_token + 1

    adjusted = validate_success(
        api_client.adjust_incentive_metric(
            metric["id"],
            adjustment_payload(refused["version"], reason, target_value=5.50),
            chair,
        ),
        200,
    )
    assert adjusted["status"] == "ADJUSTED"
    assert_money(adjusted["target_value"], 5.50, "target_value")
    assert_money(adjusted["locked_target_value"], 5.00, "locked_target_value")
    assert_money(adjusted["goal_adjustment_pct"], 10.00, "goal_adjustment_pct")
    assert adjusted["version"] == creation_token + 2


def test_support_exactly_at_seventy_percent_closes_the_program_without_enhanced_engagement():
    """Exactly 70.00 percent support passes, closes the design and clears the trigger.

    "And independently of pass or fail, `enhanced_engagement_required` is set true whenever
    `support_pct` is strictly below 70.00 — the responsiveness trigger — and false otherwise."
    "If support reached 70.00 or more, the design dimension also advances `DISCLOSED → CLOSED`
    and the program is done."

    Design: Corner/cross_cutting_layers/support_exactly_at_the_responsiveness_floor_skips_enhanced_engagement_and_closes_the_program
    """
    env = setup_disclosed_program(advisor="ISS")
    program_id = env["program"]["id"]
    assert env["program"]["design_status"] == "DISCLOSED"

    certified = validate_success(
        api_client.certify_vote(
            program_id,
            vote_certification_payload(700000, 300000, 0),
            make_comp_committee_chair_headers(CHAIR_ONE),
        ),
        200,
    )
    assert_pay_program(certified)
    assert_money(certified["support_pct"], 70.00, "support_pct")
    assert certified["vote_status"] == "PASSED"
    assert certified["enhanced_engagement_required"] is False, (
        "70.00 is not strictly below the 70.00 responsiveness floor"
    )
    assert certified["design_status"] == "CLOSED"
    assert certified["votes_for"] == 700000
    assert certified["votes_against"] == 300000
    assert certified["abstentions"] == 0

    stored = read_pay_program(program_id)
    assert stored["vote_status"] == "PASSED"
    assert stored["design_status"] == "CLOSED"
    assert stored["enhanced_engagement_required"] is False


def test_forfeiting_one_award_re_derives_the_program_totals_from_the_survivors():
    """A forfeited award drops out of both totals; the surviving award is untouched.

    "The program's `realized_pay_total_usd` is the sum of `realized_value_usd` over the program's
    awards in `GRANTED`, `VESTED` or `CLAWED_BACK`, rounded half-up to two decimal places, and
    `realizable_pay_total_usd` is the corresponding sum of `realizable_value_usd`."

    Design: Corner/cross_cutting_layers/program_totals_reconcile_after_a_forfeiture_removes_an_award
    """
    env = setup_pay_program(approve=False)
    program_id = env["program"]["id"]
    ceo_id = env["ceo"]["id"]

    annual = create_award(program_id, ceo_id, "ANNUAL_INCENTIVE")
    psu = create_award(program_id, ceo_id, "LONG_TERM_PSU")

    before = read_pay_program(program_id)
    assert_money(
        before["realizable_pay_total_usd"], 6800000.00, "realizable_pay_total_usd before forfeiture"
    )
    assert_money(before["realized_pay_total_usd"], 0.00, "realized_pay_total_usd before forfeiture")

    set_clock("2026-10-01T00:00:00Z")

    forfeited = validate_success(
        api_client.settle_payout_award(
            psu["id"],
            settlement_payload("FORFEIT", "2026-09-30T00:00:00Z"),
            CONSULTANT,
        ),
        200,
    )
    assert_payout_award(forfeited)
    assert forfeited["status"] == "FORFEITED"
    assert_money(forfeited["realizable_value_usd"], 0.00, "forfeited realizable_value_usd")
    assert_money(forfeited["realized_value_usd"], 0.00, "forfeited realized_value_usd")

    surviving = read_award(annual["id"])
    assert surviving["status"] == "GRANTED"
    assert_money(surviving["realizable_value_usd"], 1800000.00, "annual realizable_value_usd")

    after = read_pay_program(program_id)
    assert_money(
        after["realizable_pay_total_usd"], 1800000.00, "realizable_pay_total_usd after forfeiture"
    )
    assert_money(after["realized_pay_total_usd"], 0.00, "realized_pay_total_usd after forfeiture")
    assert_money(after["degree_of_alignment"], 30.00, "degree_of_alignment")
    assert after["alignment_status"] == "ALIGNED"


def test_screen_response_body_already_carries_every_derived_benchmark_field():
    """Screening returns the derived medians and both benchmark legs in its own body.

    "Unless otherwise noted, operations that create or modify a resource will return the created
    or updated resource object in the data field."

    Design: Corner/consistency_model/the_screen_response_already_carries_every_derived_benchmark_field
    """
    env = setup_mini_peer_group(target_status="DRAFT", executive_profiles=())
    group_id = env["peer_group"]["id"]

    screened = validate_success(api_client.screen_peer_group(group_id, CONSULTANT), 200)
    assert_peer_group(screened)

    assert screened["status"] == "SCREENED"
    assert_money(screened["median_revenue_usd"], 8000000000.00, "median_revenue_usd")
    assert_money(screened["median_market_cap_usd"], 16000000000.00, "median_market_cap_usd")
    assert_money(screened["size_fit_score"], 80.00, "size_fit_score")
    assert_money(
        screened["benchmark_target_tdc_raw_usd"], 12000000.00, "benchmark_target_tdc_raw_usd"
    )
    assert_money(
        screened["benchmark_target_tdc_adjusted_usd"],
        15000000.00,
        "benchmark_target_tdc_adjusted_usd",
    )
    assert_money(screened["benchmark_target_tdc_usd"], 12000000.00, "benchmark_target_tdc_usd")
    assert screened["screened_at"] is not None, "screening stamps screened_at"
    assert screened["version"] == 3, "create, member add and screen each bump the version"

    # An immediate re-read must agree exactly, and must not itself mutate the row.
    reread = read_peer_group(group_id)
    for field in (
        "status",
        "median_revenue_usd",
        "median_market_cap_usd",
        "size_fit_score",
        "benchmark_target_tdc_raw_usd",
        "benchmark_target_tdc_adjusted_usd",
        "benchmark_target_tdc_usd",
        "screened_at",
        "version",
    ):
        assert reread[field] == screened[field], (
            f"the immediate re-read must return the same {field}: "
            f"expected {screened[field]}, got {reread[field]}"
        )
    assert reread["version"] == 3, "a read must not bump the peer group's version"
