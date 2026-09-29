"""Four derived numbers: the all-or-nothing waterfall, decayed mix, funnel rates and the score."""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import media_buyer_headers

LONG_TITLE = (
    "Extremely Senior Distinguished Principal Staff Backend Platform Reliability "
    "Infrastructure Engineer For Global Talent Systems And Data Services Group Team "
    "Alpha Bravo"
)


def test_a_flight_the_last_bucket_cannot_fund_is_refused_and_leaves_no_trace(api):
    """PRD §2.6: "The walk itself is mechanical. Starting with the full amount still needed, each
    bucket in order contributes the smaller of the amount still needed and that bucket's
    availability, and never a negative amount; if a bucket's availability is zero or negative it
    contributes nothing and the walk moves on."
    PRD §2.6: "If the walk finishes the last bucket with any amount still needed, the whole request
    is rejected with `ERR_MEDIA_BUDGET_EXHAUSTED` (HTTP 409) and **nothing whatsoever is persisted**
    — no partial reservation, no partial ledger entry, no state change."
    PRD §2.6: "For a media flight the bucket order is: the family-dedicated bucket first, then
    exactly one channel-type pool chosen by the channel's `channel_type` (the job-board pool when
    the type is `JOB_BOARD`, the social pool when it is `SOCIAL`, the programmatic pool when it is
    `PROGRAMMATIC`), then the flex reserve."

    Design: Corner/calculations/waterfall_rejects_and_persists_nothing_when_the_last_bucket_cannot_close_the_gap
    """
    program = fx.create_program(api, pool_job_board_cents=100000)
    family = fx.create_job_family(api, program["id"])
    channel = fx.create_channel(api, program["id"])
    posting = fx.create_posting(api, family["id"])
    program_version = fx.program_version(api, program["id"])

    refused = api.create_media_flight(
        f.flight_payload(
            channel["id"],
            family["id"],
            posting["id"],
            program_version,
            start_date="2026-08-05",
            end_date="2026-08-10",
            daily_cap_cents=50000,
        ),
        media_buyer_headers(),
    )

    validate_error(refused, ApiErrorId.MEDIA_BUDGET_EXHAUSTED, 409)
    assert fx.list_flights(api, channel_id=channel["id"]) == []
    assert fx.list_ledger_entries(api, program_id=program["id"]) == []
    settled = fx.read_program(api, program["id"])
    assert settled["version"] == program_version, settled
    a.assert_cents(settled["committed_budget_cents"], 0, "committed_budget_cents")
    a.assert_cents(
        fx.read_job_family(api, family["id"])["reserved_cents"], 0, "reserved_cents"
    )


def test_engagement_weighting_steps_down_every_thirty_days_and_stops_at_ten_percent(api):
    """PRD §3.3: "Under `ENGAGEMENT_WEIGHTED`, the signal's age in whole days is the elapsed time
    from `collected_at` to the logical clock divided by 86,400 seconds and rounded down; a decay
    percentage is then 100 less 10 for each complete 30-day step of that age, with the number of
    complete steps obtained by rounding the age in days divided by 30 down to a whole number, and
    the result held to a floor of 10 percent no matter how old the signal is; the signal's weight is
    its `engagement_events` multiplied by that decay percentage and divided by 100, kept as an exact
    value with no rounding."
    PRD §3.3: "When the grand total is positive, exactly ten thousand basis points are distributed
    across the channels: each channel's exact share is ten thousand multiplied by that channel's raw
    score and divided by the grand total, each exact share is rounded down to a whole basis point,
    the shortfall between the sum of those floors and ten thousand is counted, and one additional
    basis point is awarded to each of that many channels with the largest fractional parts, ties
    broken by the channel's `created_at` ascending and then the channel's `name` ascending — never
    by the channel's `id`."
    PRD §3.3: "`mix_confidence_pct` is the total `sample_size` across all in-window signals divided
    by 10 and rounded down, then held to a ceiling of 100 — so ten respondents buy one percentage
    point of confidence, and a thousand respondents saturate the scale."

    Design: Corner/calculations/engagement_weighted_mix_applies_the_thirty_day_decay_steps_and_its_ten_percent_floor
    """
    program = fx.create_program(api)
    family = fx.create_job_family(api, program["id"])
    fresh_channel = fx.create_channel(api, program["id"], name="AAA Board")
    two_step_channel = fx.create_channel(
        api, program["id"], name="BBB Social", channel_type="SOCIAL"
    )
    floored_channel = fx.create_channel(
        api, program["id"], name="CCC Programmatic", channel_type="PROGRAMMATIC"
    )
    persona = fx.create_persona(
        api, family["id"], mix_method="ENGAGEMENT_WEIGHTED", research_window_days=365
    )

    fx.add_signal(
        api,
        persona["id"],
        fresh_channel["id"],
        preference_score=50,
        sample_size=100,
        engagement_events=100,
        collected_at="2026-08-01T00:00:00Z",
    )
    fx.add_signal(
        api,
        persona["id"],
        two_step_channel["id"],
        preference_score=50,
        sample_size=100,
        engagement_events=100,
        collected_at="2026-06-02T00:00:00Z",
    )
    fx.add_signal(
        api,
        persona["id"],
        floored_channel["id"],
        preference_score=50,
        sample_size=100,
        engagement_events=100,
        collected_at="2025-10-05T00:00:00Z",
    )

    computed = fx.read_persona(api, persona["id"])
    assert computed["signal_count"] == 3, computed
    a.assert_channel_mix(
        computed["channel_mix"],
        [
            (fresh_channel["id"], 5263),
            (two_step_channel["id"], 4211),
            (floored_channel["id"], 526),
        ],
    )
    assert computed["mix_confidence_pct"] == 30, computed


def test_the_funnel_rate_floors_and_keeps_disqualified_applications_in_the_numerator(api):
    """PRD §3.4: "`apply_start_count` is the number of applications on the posting in any status."
    PRD §3.4: "`submitted_count` is the number whose `status` is `SUBMITTED`, `SCREENED`,
    `QUALIFIED` or `DISQUALIFIED` — that is, every application that got past the start line,
    including ones later rejected."
    PRD §3.4: "`conversion_rate_bp` is null while `apply_start_count` is 0, and otherwise is ten
    thousand multiplied by `submitted_count`, divided by `apply_start_count`, and rounded down to a
    whole basis point."

    Design: Corner/calculations/conversion_metrics_count_started_applications_in_the_denominator_only
    """
    program = fx.create_program(api)
    family = fx.create_job_family(api, program["id"])
    channel = fx.create_channel(api, program["id"])
    posting = fx.published_posting(api, family["id"], channel["id"])

    empty = validate_success(
        api.get_job_posting_conversion(posting["id"], media_buyer_headers()), 200
    )
    first = fx.start_application(api, posting["id"], "a1@example.com")
    fx.start_application(api, posting["id"], "a2@example.com")
    fx.start_application(api, posting["id"], "a3@example.com")
    fx.submit_application(api, first["id"])
    after_one_submission = validate_success(
        api.get_job_posting_conversion(posting["id"], media_buyer_headers()), 200
    )
    fx.screen_application(api, first["id"])
    fx.decide_application(api, first["id"], "DISQUALIFIED", reason="no eligible touch")
    after_disqualification = validate_success(
        api.get_job_posting_conversion(posting["id"], media_buyer_headers()), 200
    )

    assert empty["apply_start_count"] == 0, empty
    assert empty["conversion_rate_bp"] is None, empty
    assert after_one_submission["apply_start_count"] == 3, after_one_submission
    assert after_one_submission["submitted_count"] == 1, after_one_submission
    assert after_one_submission["qualified_count"] == 0, after_one_submission
    assert after_one_submission["conversion_rate_bp"] == 3333, after_one_submission
    assert after_disqualification["apply_start_count"] == 3, after_disqualification
    assert after_disqualification["submitted_count"] == 1, after_disqualification
    assert after_disqualification["qualified_count"] == 0, after_disqualification
    assert after_disqualification["conversion_rate_bp"] == 3333, after_disqualification


def test_the_optimization_score_bands_reward_a_short_title_and_zero_a_long_one(api):
    """PRD §3.4: "The title component contributes 25 points when `title_word_count` is between 3 and
    12 inclusive; failing that, it contributes 10 points when `title_word_count` is 20 or fewer —
    which includes very short titles of one or two words — and 0 points when the count exceeds 20."
    PRD §3.4: "The responsibilities component contributes 20 points when `responsibility_count` is 5
    or more, and otherwise contributes 4 points for each responsibility bullet present."
    PRD §3.4: "The benefits component contributes 5 points for each benefit bullet, counting at most
    five bullets, so it saturates at 25 points."

    Design: Corner/calculations/optimization_score_sums_five_weighted_components_with_their_own_bands
    """
    program = fx.create_program(api)
    family = fx.create_job_family(api, program["id"])
    short = fx.create_posting(
        api, family["id"], title="Backend Engineer", responsibility_count=3, benefit_count=7
    )
    verbose = fx.create_posting(
        api, family["id"], title=LONG_TITLE, responsibility_count=5, benefit_count=0
    )

    short_scored = fx.optimize_posting(api, short["id"], short["version"])
    long_scored = fx.optimize_posting(api, verbose["id"], verbose["version"])

    assert short["title_word_count"] == 2, short
    assert short_scored["title_word_count"] == 2, short_scored
    assert short_scored["optimization_score"] == 77, short_scored
    assert verbose["title_word_count"] == 21, verbose
    assert long_scored["title_word_count"] == 21, long_scored
    assert long_scored["optimization_score"] == 50, long_scored
    for scored in (short_scored, long_scored):
        assert scored["content_status"] == "OPTIMIZED", scored
        assert scored["version"] == 2, scored
