"""Gates that guard clearance, channel capacity, campaign timing and the reputation threshold."""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    COMPLIANCE_REVIEWER_USER_ID,
    brand_lead_headers,
    community_manager_headers,
    compliance_reviewer_headers,
    media_buyer_headers,
)


def test_a_missing_equal_opportunity_statement_blocks_clearance_before_any_score_gate(api):
    """PRD §3.4: "It further requires `eeo_statement_included` to be true, refusing otherwise with
    `ERR_EEO_STATEMENT_MISSING`, and it requires that either `superlative_claim_included` is false or
    `substantiation_url` is present, refusing an unsupported boast with `ERR_UNSUBSTANTIATED_CLAIM`."
    PRD §2.9: "23. `eeo_statement_included` must be true before a compliance `CLEAR` decision and
    before publication, else `ERR_EEO_STATEMENT_MISSING` (409)."
    PRD §3.4: "The equal-opportunity component contributes 15 points when `eeo_statement_included`
    is true and 0 when it is false."
    PRD §2.9: "25. `compliance_status` must be `CLEARED` before publishing a posting, before
    activating or resuming a flight pointing at it, and before an application on it is submitted,
    else `ERR_POSTING_COMPLIANCE_NOT_CLEARED` (409)."
    PRD §2.9: "The service therefore evaluates checks in the following fixed priority order,
    stopping at the first failure. Text order in the rest of this document is *not* an ordering
    signal; this list is."

    Design: Corner/validations/clearing_a_posting_without_an_eeo_statement_returns_eeo_statement_missing
    """
    program = fx.create_program(api)
    family = fx.create_job_family(api, program["id"])
    posting = fx.create_posting(api, family["id"], eeo_statement_included=False)
    optimized = fx.optimize_posting(api, posting["id"], posting["version"])

    refused = api.compliance_review_job_posting(
        posting["id"],
        f.compliance_review_payload("CLEAR", "looks fine to me"),
        compliance_reviewer_headers(),
    )
    publish_refused = api.publish_job_posting(posting["id"], brand_lead_headers())

    validate_error(refused, ApiErrorId.EEO_STATEMENT_MISSING, 409)
    assert optimized["optimization_score"] == 85, optimized
    unchanged = fx.read_posting(api, posting["id"])
    assert unchanged["compliance_status"] == "UNREVIEWED", unchanged
    assert unchanged["cleared_by_user_id"] is None, unchanged
    assert unchanged["version"] == optimized["version"], unchanged
    # Ladder priority 23 (EEO) is evaluated before priority 25 (clearance), so the
    # missing statement is the first failure publication reports.
    validate_error(publish_refused, ApiErrorId.EEO_STATEMENT_MISSING, 409)


def test_a_superlative_boast_clears_only_once_a_substantiation_url_is_stored(api):
    """PRD §2.9: "24. When `superlative_claim_included` is true, `substantiation_url` must be present
    before a compliance `CLEAR` decision, else `ERR_UNSUBSTANTIATED_CLAIM` (409)."
    PRD §3.4: "Clearing moves `compliance_status` to `CLEARED`, sets `cleared_by_user_id` to the
    acting `X-User-ID`, refreshes `updated_at` and advances `version` by 1."
    PRD §3.4: "A successful revision applies the supplied edits, recomputes `title_word_count` from
    the resulting title, recomputes `optimization_score`, moves `content_status` to `OPTIMIZED`, sets
    `optimized_by_user_id` to the acting `X-User-ID`, refreshes `updated_at` and advances `version`
    by 1."

    Design: Corner/validations/superlative_claim_needs_a_substantiation_url_before_it_can_be_cleared
    """
    program = fx.create_program(api)
    family = fx.create_job_family(api, program["id"])
    posting = fx.create_posting(
        api,
        family["id"],
        title="Best Backend Team On Earth Engineer",
        superlative_claim_included=True,
    )
    optimized = fx.optimize_posting(api, posting["id"], posting["version"])

    refused = api.compliance_review_job_posting(
        posting["id"],
        f.compliance_review_payload("CLEAR", "first look"),
        compliance_reviewer_headers(),
    )
    after_the_refusal = fx.read_posting(api, posting["id"])
    substantiated = fx.optimize_posting(
        api,
        posting["id"],
        optimized["version"],
        substantiation_url="https://example.com/awards/2026",
    )
    cleared = validate_success(
        api.compliance_review_job_posting(
            posting["id"],
            f.compliance_review_payload("CLEAR", "award page checked"),
            compliance_reviewer_headers(),
        ),
        200,
    )

    validate_error(refused, ApiErrorId.UNSUBSTANTIATED_CLAIM, 409)
    assert after_the_refusal["compliance_status"] == "UNREVIEWED", after_the_refusal
    assert after_the_refusal["cleared_by_user_id"] is None, after_the_refusal
    assert after_the_refusal["version"] == optimized["version"], after_the_refusal
    assert substantiated["substantiation_url"] == "https://example.com/awards/2026", substantiated
    assert substantiated["content_status"] == "OPTIMIZED", substantiated
    assert substantiated["version"] == optimized["version"] + 1, substantiated
    assert cleared["compliance_status"] == "CLEARED", cleared
    assert cleared["cleared_by_user_id"] == COMPLIANCE_REVIEWER_USER_ID, cleared


def test_the_daily_capacity_check_sums_every_overlapping_flight_across_families(api):
    """PRD §3.5: "The requested `daily_cap_cents` added to the sum of `daily_cap_cents` over every
    flight on the same channel — of any job family — whose `state` is `RESERVED`, `ACTIVE`,
    `PAUSED_PACING` or `SUSPENDED_CONTENT` and whose window intersects the requested one must be no
    greater than the channel's `daily_capacity_cents`, or the request is refused with
    `ERR_CHANNEL_DAILY_CAPACITY_EXCEEDED`."
    PRD §3.5: "No other flight on the *same channel and the same job family* whose `state` is
    `RESERVED`, `ACTIVE`, `PAUSED_PACING` or `SUSPENDED_CONTENT` may have a half-open window
    intersecting the requested one, or the request is refused with `ERR_FLIGHT_WINDOW_OVERLAP`;
    because the windows are half-open, back-to-back flights that merely touch are allowed."
    PRD §2.6: "`committed_budget_cents` is the sum of `delta_cents` over every ledger entry of that
    program, and `available_budget_cents` is the sum of `pool_job_board_cents`, `pool_social_cents`,
    `pool_programmatic_cents`, `flex_reserve_cents` and the `dedicated_budget_cents` of every
    `JobFamily` belonging to that program, less `committed_budget_cents`."

    Design: Corner/validations/channel_daily_capacity_is_an_aggregate_over_every_overlapping_flight
    """
    program = fx.create_program(api, pool_job_board_cents=1000000)
    engineering = fx.create_job_family(api, program["id"])
    sales = fx.create_job_family(
        api,
        program["id"],
        name="Enterprise Sales",
        code="SALES",
        cpqa_target_cents=22000,
        priority_rank=2,
    )
    channel = fx.create_channel(api, program["id"])
    posting = fx.create_posting(api, engineering["id"])
    first = fx.reserve_flight(
        api,
        channel["id"],
        engineering["id"],
        posting["id"],
        fx.program_version(api, program["id"]),
        start_date="2026-08-05",
        end_date="2026-08-10",
        daily_cap_cents=60000,
    )
    version_after_first = fx.program_version(api, program["id"])

    over_capacity = api.create_media_flight(
        f.flight_payload(
            channel["id"],
            sales["id"],
            posting["id"],
            version_after_first,
            start_date="2026-08-07",
            end_date="2026-08-12",
            daily_cap_cents=50000,
        ),
        media_buyer_headers(),
    )
    version_after_the_refusal = fx.program_version(api, program["id"])
    exactly_at_capacity = api.create_media_flight(
        f.flight_payload(
            channel["id"],
            sales["id"],
            posting["id"],
            version_after_first,
            start_date="2026-08-07",
            end_date="2026-08-12",
            daily_cap_cents=40000,
        ),
        media_buyer_headers(),
    )

    validate_error(over_capacity, ApiErrorId.CHANNEL_DAILY_CAPACITY_EXCEEDED, 409)
    assert version_after_the_refusal == version_after_first, version_after_the_refusal
    second = validate_success(exactly_at_capacity, 201)
    assert fx.program_version(api, program["id"]) == version_after_first + 1
    a.assert_cents(first["total_cost_cents"], 309000, "total_cost_cents")
    a.assert_cents(second["total_cost_cents"], 206000, "total_cost_cents")
    assert second["state"] == "RESERVED", second
    a.assert_program_budget(
        fx.read_program(api, program["id"]),
        committed_budget_cents=515000,
        available_budget_cents=485000,
    )


def test_scheduling_and_dispatch_both_accept_the_boundary_instant_and_nothing_earlier(api):
    """PRD §3.7: "Scheduling it supplies a `scheduled_for` instant that must be at or after the
    logical clock, refusing a past instant with `ERR_SCHEDULE_IN_PAST`; the campaign must be in
    `DRAFT`, refused otherwise with `ERR_CAMPAIGN_NOT_DRAFT`."
    PRD §3.7: "The campaign must be in `SCHEDULED`, refused otherwise with
    `ERR_CAMPAIGN_NOT_SCHEDULED`, and the logical clock must be at or after the stored
    `scheduled_for`, refused otherwise with `ERR_DISPATCH_TOO_EARLY`."
    PRD §3.7: "Scheduling stores `scheduled_for`, moves the campaign `DRAFT → SCHEDULED`, refreshes
    `updated_at` and advances `version` by 1."

    Design: Corner/validations/campaign_scheduling_and_dispatch_windows_are_inclusive_at_their_boundaries
    """
    program = fx.create_program(api, send_quota_total=10)
    fx.subscribed_member(api, program["id"], "nurtured@example.com")
    campaign = fx.create_campaign(api, program["id"], name="August Warm-up", max_sends=5)

    dispatch_while_draft = api.dispatch_nurture_campaign(
        campaign["id"], community_manager_headers()
    )
    schedule_in_past = api.schedule_nurture_campaign(
        campaign["id"], f.schedule_payload("2026-07-31T23:59:59Z"), community_manager_headers()
    )
    scheduled = fx.schedule_campaign(api, campaign["id"], "2026-08-05T00:00:00Z")
    dispatch_four_days_early = api.dispatch_nurture_campaign(
        campaign["id"], community_manager_headers()
    )
    fx.move_clock(api, "2026-08-04T23:59:59Z")
    dispatch_one_second_early = api.dispatch_nurture_campaign(
        campaign["id"], community_manager_headers()
    )
    fx.move_clock(api, "2026-08-05T00:00:00Z")
    dispatched = validate_success(
        api.dispatch_nurture_campaign(campaign["id"], community_manager_headers()), 200
    )

    validate_error(dispatch_while_draft, ApiErrorId.CAMPAIGN_NOT_SCHEDULED, 409)
    validate_error(schedule_in_past, ApiErrorId.SCHEDULE_IN_PAST, 409)
    assert scheduled["state"] == "SCHEDULED", scheduled
    assert scheduled["scheduled_for"] == "2026-08-05T00:00:00.000Z", scheduled
    assert scheduled["version"] == campaign["version"] + 1, scheduled
    validate_error(dispatch_four_days_early, ApiErrorId.DISPATCH_TOO_EARLY, 409)
    validate_error(dispatch_one_second_early, ApiErrorId.DISPATCH_TOO_EARLY, 409)
    assert dispatched["state"] == "DISPATCHED", dispatched
    assert dispatched["audience_size"] == 1, dispatched
    assert dispatched["sent_count"] == 1, dispatched
    assert fx.read_program(api, program["id"])["send_quota_used"] == 1


def test_activation_passes_at_exactly_fifty_five_points_of_brand_health_and_fails_below(api):
    """PRD §2.9: "27. `brand_health_score` must be at least `55.00` before a flight may be
    activated, else `ERR_BRAND_HEALTH_GATE` (409)."
    PRD §3.5: "and the funding program's `brand_health_score` must be at least `55.00`, refusing
    otherwise with `ERR_BRAND_HEALTH_GATE`."
    PRD §3.8: "The rating penalty is the sum over the windowed reviews of the star shortfall — three
    less the review's `rating`, treated as zero when the rating is 3 or above — multiplied by 2.5
    points per missing star and then multiplied by that review's recency weight."

    Design: Corner/validations/flight_activation_passes_at_a_brand_health_score_of_exactly_fifty_five
    """
    program = fx.create_program(api, pool_job_board_cents=1000000)
    family = fx.create_job_family(api, program["id"])
    channel = fx.create_channel(api, program["id"])
    posting = fx.published_posting(api, family["id"], channel["id"])
    first = fx.reserve_flight(
        api,
        channel["id"],
        family["id"],
        posting["id"],
        fx.program_version(api, program["id"]),
        start_date="2026-08-05",
        end_date="2026-08-10",
        daily_cap_cents=50000,
    )
    second = fx.reserve_flight(
        api,
        channel["id"],
        family["id"],
        posting["id"],
        fx.program_version(api, program["id"]),
        start_date="2026-08-12",
        end_date="2026-08-17",
        daily_cap_cents=50000,
    )
    fx.drive_brand_health_down(api, program["id"], 9)

    at_the_gate = fx.read_program(api, program["id"])
    activated = validate_success(
        api.activate_media_flight(first["id"], media_buyer_headers()), 200
    )
    fx.ingest_review(
        api, program["id"], external_ref="gd-10", rating=1, posted_at="2026-07-31T00:00:00Z"
    )
    below_the_gate = fx.read_program(api, program["id"])
    refused = api.activate_media_flight(second["id"], media_buyer_headers())

    assert float(at_the_gate["brand_health_score"]) == 55.00, at_the_gate
    assert activated["state"] == "ACTIVE", activated
    assert activated["activated_at"].startswith("2026-08-01T00:00:00"), activated
    assert float(below_the_gate["brand_health_score"]) == 50.00, below_the_gate
    validate_error(refused, ApiErrorId.BRAND_HEALTH_GATE, 409)
    still_reserved = fx.read_flight(api, second["id"])
    assert still_reserved["state"] == "RESERVED", still_reserved
    assert fx.read_channel(api, channel["id"])["active_flight_count"] == 1
    assert len(fx.ledger_entries_for_source(api, second["id"])) == 1
