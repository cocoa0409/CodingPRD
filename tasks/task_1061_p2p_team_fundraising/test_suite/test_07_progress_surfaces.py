"""Public progress: the thermometer, the two leaderboard variants, and the rollup."""

from test_helpers import (
    create_active_participant,
    create_donor,
    create_event,
    create_gift,
    create_incentive_tier,
    create_participant,
    create_registration,
    create_settled_gift,
    make_participant_headers,
    settle_gift,
    setup_published_campaign,
    setup_two_teams_with_credit,
    validate_success,
)


def test_thermometer_reports_zeros_when_no_gift_has_settled(api, anonymous_headers):
    """PRD §3.8: "With zero settled gifts the response reports a credited total of 0,
    a donor count of 0 and a `percent_bp` of 0 — never a null and never a division
    failure, which is why a campaign goal of at least 1 cent is enforced at creation."

    Design: Difficulty/boundary_precision_check/thermometer_empty_settled_set_returns_zero_percent
    """
    ctx = setup_published_campaign(api=api)
    create_participant(ctx["campaign_id"], api=api, display_name="Alice Reyes")
    create_participant(ctx["campaign_id"], api=api, display_name="Ben Ortiz")
    donor = create_donor(api=api)
    create_gift(ctx["campaign_id"], donor["id"], "CAMPAIGN", ctx["campaign_id"], 5000, api=api)
    failed = create_gift(
        ctx["campaign_id"], donor["id"], "CAMPAIGN", ctx["campaign_id"], 7000, api=api
    )
    settle_gift(failed["id"], api=api, outcome="FAILED")

    thermometer = validate_success(
        api.get_thermometer(ctx["campaign_id"], anonymous_headers)
    )

    assert thermometer["raised_credited_cents"] == 0
    assert thermometer["donor_count"] == 0
    assert thermometer["percent_bp"] == 0


def test_thermometer_still_counts_pages_and_echoes_the_goal(api, anonymous_headers):
    """PRD §3.8: "`participant_count` is the number of the campaign's fundraiser pages
    whose status is `PENDING` or `ACTIVE`."
    PRD §3.8: "It reports the campaign's `goal_amount_cents`, the credited total
    `raised_credited_cents`, an integer `percent_bp`, a `donor_count` and a
    `participant_count`."

    Design: Difficulty/boundary_precision_check/thermometer_empty_settled_set_returns_zero_percent
    """
    ctx = setup_published_campaign(api=api)
    create_participant(ctx["campaign_id"], api=api, display_name="Alice Reyes")
    create_participant(ctx["campaign_id"], api=api, display_name="Ben Ortiz")
    donor = create_donor(api=api)
    create_gift(ctx["campaign_id"], donor["id"], "CAMPAIGN", ctx["campaign_id"], 5000, api=api)
    failed = create_gift(
        ctx["campaign_id"], donor["id"], "CAMPAIGN", ctx["campaign_id"], 7000, api=api
    )
    settle_gift(failed["id"], api=api, outcome="FAILED")

    thermometer = validate_success(
        api.get_thermometer(ctx["campaign_id"], anonymous_headers)
    )

    assert thermometer["participant_count"] == 2
    assert thermometer["goal_amount_cents"] == 1000000


def test_raw_total_ranks_teams_by_credited_cents(api, anonymous_headers):
    """PRD §3.8: "`RAW_TOTAL` is the default — the variant used by the public campaign
    page — and orders teams by `credited_cents` descending, breaking ties by
    `created_at` ascending; the size of a team's goal is ignored entirely."

    Design: Difficulty/dual_variant_calc/team_leaderboard_raw_total_vs_goal_percent_invert_order
    """
    ctx = setup_two_teams_with_credit(api=api)

    board = validate_success(
        api.get_leaderboard(
            ctx["campaign_id"], anonymous_headers,
            params={"scope": "TEAM", "variant": "RAW_TOTAL"},
        )
    )

    rows = board["rows"]
    assert board["scope"] == "TEAM"
    assert board["variant"] == "RAW_TOTAL"
    assert len(rows) == 2, f"Expected both ACTIVE teams, got {len(rows)}"
    assert rows[0]["credited_cents"] == 20000, "Team Alpha leads on the raw total"
    assert rows[1]["credited_cents"] == 15000


def test_goal_percent_inverts_that_ranking_on_the_same_data(api, anonymous_headers):
    """PRD §3.8: "`GOAL_PERCENT`, requested by passing `variant=GOAL_PERCENT`, is used
    to award the "closest to goal" challenge: it computes each team's `goal_percent_bp`
    as that team's `credited_cents` multiplied by 10000, divided by the team's
    `goal_amount_cents`, floored to a whole basis-point integer, and orders teams by
    that figure descending, again breaking ties by `created_at` ascending."

    Design: Difficulty/dual_variant_calc/team_leaderboard_raw_total_vs_goal_percent_invert_order
    """
    ctx = setup_two_teams_with_credit(api=api)

    board = validate_success(
        api.get_leaderboard(
            ctx["campaign_id"], anonymous_headers,
            params={"scope": "TEAM", "variant": "GOAL_PERCENT"},
        )
    )

    rows = board["rows"]
    assert board["variant"] == "GOAL_PERCENT"
    assert rows[0]["goal_percent_bp"] == 5000, "15000 of a 30000 goal"
    assert rows[0]["credited_cents"] == 15000, "The smaller team now leads"
    assert rows[1]["goal_percent_bp"] == 2000, "20000 of a 100000 goal"
    assert rows[1]["credited_cents"] == 20000


def test_participant_scope_ranks_fundraisers_by_their_final_credit(api, anonymous_headers):
    """PRD §3.8: "Under `scope=PARTICIPANT`, rows are built from the FINAL participant
    credit of §3.6 instead."
    PRD §3.8: "`RAW_TOTAL` is the default — the variant used by the public campaign
    page — and orders teams by `credited_cents` descending, breaking ties by
    `created_at` ascending; the size of a team's goal is ignored entirely."

    Design: Corner/endpoints/participant_scope_leaderboard_ranks_by_credited_cents
    """
    ctx = setup_published_campaign(api=api)
    first = create_participant(ctx["campaign_id"], api=api, display_name="Alice Reyes")
    second = create_participant(ctx["campaign_id"], api=api, display_name="Ben Ortiz")
    donor = create_donor(api=api)
    create_settled_gift(
        ctx["campaign_id"], donor["id"], "PARTICIPANT", first["id"], 20000, api=api
    )
    create_settled_gift(
        ctx["campaign_id"], donor["id"], "PARTICIPANT", second["id"], 15000, api=api
    )

    board = validate_success(
        api.get_leaderboard(
            ctx["campaign_id"], anonymous_headers,
            params={"scope": "PARTICIPANT", "limit": 10, "offset": 0},
        )
    )

    rows = board["rows"]
    assert board["scope"] == "PARTICIPANT"
    assert board["variant"] == "RAW_TOTAL", "The default variant when none is passed"
    assert rows[0]["credited_cents"] == 20000
    assert rows[1]["credited_cents"] == 15000


def test_the_rollup_counts_gifts_registrations_and_awards(api):
    """PRD §3.9: "`settled_donation_count` and `refunded_donation_count` are the counts
    of the campaign's gifts whose payment dimension reads `SETTLED` and `REFUNDED`
    respectively."
    PRD §3.9: "`confirmed_registrations` counts registrations across the campaign's
    events sitting in `CONFIRMED` or `CHECKED_IN`, while `checked_in_registrations`
    counts only those in `CHECKED_IN`. `awards_earned_count` counts incentive awards of
    the campaign's fundraisers in `EARNED` or `FULFILLED`, so revoked awards drop out."

    Design: Corner/calculations/campaign_report_counts_registrations_and_awards
    """
    ctx = setup_published_campaign(api=api, fundraising_minimum_cents=0)
    create_incentive_tier(ctx["campaign_id"], ctx["cm_headers"], api=api)
    event = create_event(ctx["campaign_id"], ctx["cm_headers"], api=api)
    participant = create_active_participant(ctx["campaign_id"], api=api)
    donor = create_donor(api=api)
    create_settled_gift(
        ctx["campaign_id"], donor["id"], "PARTICIPANT", participant["id"], 10000, api=api
    )
    headers = make_participant_headers(participant["id"])
    registration = create_registration(participant["id"], event["id"], headers, api=api)
    validate_success(api.confirm_registration(registration["id"], headers))

    report = validate_success(api.get_report(ctx["campaign_id"], ctx["cm_headers"]))

    assert report["settled_donation_count"] == 1
    assert report["refunded_donation_count"] == 0
    assert report["gross_amount_cents"] == 10000
    assert report["fee_total_cents"] == 820
    assert report["match_total_cents"] == 0
    assert report["deductible_total_cents"] == 10000
    assert report["confirmed_registrations"] == 1
    assert report["checked_in_registrations"] == 0
    assert report["awards_earned_count"] == 1
