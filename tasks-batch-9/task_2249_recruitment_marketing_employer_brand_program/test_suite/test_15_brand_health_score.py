"""The brand health decay: which reviews are in the window, what they weigh, how it rounds."""
from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures as fx
from test_helpers.test_users import brand_lead_headers


def _ingest(api, program_id, platform, external_ref, rating, posted_at):
    return fx.ingest_review(
        api,
        program_id,
        platform=platform,
        external_ref=external_ref,
        rating=rating,
        posted_at=posted_at,
    )


def test_the_review_response_deadline_picks_a_different_band_for_two_three_and_four_stars(api):
    """PRD §3.8: "A rating of 1 or 2 gives 24 hours; a rating of exactly 3 gives 72 hours — three
    days; a rating of 4 or 5 gives 168 hours — a full week."
    PRD §3.8: "`response_due_at` is `posted_at` plus that many hours, recorded as an exact ISO 8601
    instant with three fractional digits."
    PRD §3.8: "A new review is in `state` `NEW` with `sla_status` `PENDING`, `rejection_count` 0,
    `response_body` null, and `drafted_by_user_id`, `approved_by_user_id` and `responded_at` all
    null."

    Design: Corner/calculations/review_response_deadline_selects_the_right_sla_band_for_each_rating
    """
    program = fx.create_program(api)

    two_stars = _ingest(api, program["id"], "GLASSDOOR", "gd-r2", 2, "2026-07-30T06:00:00Z")
    three_stars = _ingest(api, program["id"], "GLASSDOOR", "gd-r3", 3, "2026-07-30T06:00:00Z")
    four_stars = _ingest(api, program["id"], "GLASSDOOR", "gd-r4", 4, "2026-07-30T06:00:00Z")

    assert two_stars["response_due_at"] == "2026-07-31T06:00:00.000Z", two_stars
    assert three_stars["response_due_at"] == "2026-08-02T06:00:00.000Z", three_stars
    assert four_stars["response_due_at"] == "2026-08-06T06:00:00.000Z", four_stars
    for review in (two_stars, three_stars, four_stars):
        assert review["state"] == "NEW", review
        assert review["sla_status"] == "PENDING", review
        assert review["responded_at"] is None, review


def test_a_review_posted_exactly_ninety_days_ago_falls_outside_the_health_window(api):
    """PRD §3.8: "The window is the reviews of that program whose `posted_at` is strictly later than
    the logical clock minus 90 days and no later than the logical clock — the lower bound exclusive,
    the upper inclusive."
    PRD §3.8: "Reviews outside that window contribute nothing regardless of their state."
    PRD §3.8: "The rating penalty is the sum over the windowed reviews of the star shortfall — three
    less the review's `rating`, treated as zero when the rating is 3 or above — multiplied by 2.5
    points per missing star and then multiplied by that review's recency weight."

    Design: Corner/calculations/brand_health_window_excludes_a_review_posted_exactly_ninety_days_ago
    """
    program = fx.create_program(api)

    yesterday = _ingest(api, program["id"], "GLASSDOOR", "gd-in", 1, "2026-07-31T00:00:00Z")
    after_one_review = fx.read_program(api, program["id"])["brand_health_score"]
    _ingest(api, program["id"], "INDEED", "in-edge", 1, "2026-05-03T00:00:00Z")
    after_the_edge = fx.read_program(api, program["id"])["brand_health_score"]
    _ingest(api, program["id"], "COMPARABLY", "cp-inside", 1, "2026-05-04T00:00:00Z")

    assert yesterday["sla_status"] == "PENDING", yesterday
    assert float(after_one_review) == 95.00, after_one_review
    assert float(after_the_edge) == 95.00, after_the_edge
    final = fx.read_program(api, program["id"])
    assert float(final["brand_health_score"]) == 93.75, final


def test_recency_weights_treat_thirty_and_sixty_days_as_the_newer_band(api):
    """PRD §3.8: "For each review in the window, its age in whole days is the elapsed time from
    `posted_at` to the logical clock divided by 86,400 seconds and rounded down, and its recency
    weight is `1.00` when the age is 30 days or fewer, `0.50` when the age is 31 through 60 days,
    and `0.25` when the age is 61 days or more."
    PRD §3.8: "So a one-star review posted yesterday costs 5 points, the same review 45 days old
    costs 2.5 points, and the same review 75 days old costs 1.25 points, while a three-star review
    costs nothing at all."
    PRD §3.8: "The SLA penalty is 5 points multiplied by the number of windowed reviews whose
    `sla_status` is `BREACHED`, with no recency weighting applied to it."

    Design: Corner/calculations/brand_health_recency_weights_switch_at_thirty_and_sixty_days
    """
    program = fx.create_program(api)

    _ingest(api, program["id"], "GLASSDOOR", "gd-a30", 1, "2026-07-02T00:00:00Z")
    thirty_days = fx.read_program(api, program["id"])["brand_health_score"]
    _ingest(api, program["id"], "GLASSDOOR", "gd-a60", 1, "2026-06-02T00:00:00Z")
    sixty_days = fx.read_program(api, program["id"])["brand_health_score"]
    _ingest(api, program["id"], "GLASSDOOR", "gd-a61", 1, "2026-06-01T00:00:00Z")

    assert float(thirty_days) == 95.00, thirty_days
    assert float(sixty_days) == 92.50, sixty_days
    final = fx.read_program(api, program["id"])
    assert float(final["brand_health_score"]) == 91.25, final


def test_a_fractional_penalty_is_rounded_half_up_once_at_the_very_end(api):
    """PRD §3.8: "The score is then 100 less the rating penalty less the SLA penalty, held to the
    inclusive interval from 0 to 100, and rounded half up to exactly two decimal places."
    PRD §3.8: "All the intermediate arithmetic is exact decimal arithmetic, and the single rounding
    happens at the very end."
    PRD §2.5: "The program's `brand_health_score` is the only non-integer stored value: it is a
    number rounded half up to exactly two decimal places and clamped to the inclusive interval from
    `0.00` to `100.00`."

    Design: Corner/calculations/brand_health_rounds_half_up_to_two_decimals_at_the_end
    """
    program = fx.create_program(api)
    _ingest(api, program["id"], "INDEED", "in-frac", 2, "2026-06-01T00:00:00Z")

    response = api.get_program(program["id"], brand_lead_headers())

    read_back = validate_success(response, 200)
    assert float(read_back["brand_health_score"]) == 99.38, read_back
    assert float(read_back["brand_health_score"]) != 99.37, read_back
    assert float(read_back["brand_health_score"]) >= 55.00, read_back
