"""Multi-touch attribution: the two models, the remainder rule and the compensating reversal."""
from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.test_users import brand_lead_headers

THREE_TOUCH_INSTANTS = (
    "2026-07-28T09:00:00Z",
    "2026-07-29T09:00:00Z",
    "2026-07-30T09:00:00Z",
)
SEVEN_TOUCH_INSTANTS = (
    "2026-07-25T00:00:00Z",
    "2026-07-26T00:00:00Z",
    "2026-07-27T00:00:00Z",
    "2026-07-28T00:00:00Z",
    "2026-07-29T00:00:00Z",
    "2026-07-30T00:00:00Z",
    "2026-07-31T00:00:00Z",
)
SEVEN_TOUCH_TYPES = (
    "IMPRESSION",
    "IMPRESSION",
    "IMPRESSION",
    "CLICK",
    "CLICK",
    "CLICK",
    "REFERRAL",
)


def _three_channel_program(api):
    """One family, three payable channels created job board first, then social, then programmatic."""
    program = fx.create_program(api, pool_job_board_cents=2000000)
    family = fx.create_job_family(api, program["id"])
    board = fx.create_channel(api, program["id"], name="Board A", channel_type="JOB_BOARD")
    social = fx.create_channel(api, program["id"], name="Social B", channel_type="SOCIAL")
    programmatic = fx.create_channel(
        api, program["id"], name="Prog C", channel_type="PROGRAMMATIC"
    )
    posting = fx.published_posting(api, family["id"], board["id"])
    return program, family, (board, social, programmatic), posting


def _qualify_across_three_channels(api, posting_id, channels, email):
    application = fx.start_application(api, posting_id, email)
    for channel, occurred_at in zip(channels, THREE_TOUCH_INSTANTS):
        fx.add_touchpoint(api, application["id"], channel["id"], occurred_at)
    fx.submit_application(api, application["id"])
    fx.screen_application(api, application["id"])
    return fx.decide_application(api, application["id"], "QUALIFIED")


def _credits_in_engine_order(api, application_id):
    rows = fx.list_touchpoints(api, application_id=application_id)
    a.assert_ordered_by(rows, "occurred_at", "created_at")
    return [row["credit_bp"] for row in rows]


def test_linear_attribution_spreads_credit_evenly_with_the_remainder_earliest(api):
    """PRD §3.6: "Under `LINEAR`, every eligible touchpoint carries a weight of 1, so credit
    spreads evenly and the rounding remainder lands on the earliest touchpoints — with three
    eligible touches the credits come out as 3,334 then 3,333 then 3,333 basis points."
    PRD §3.6: "Hop one writes the computed `credit_bp` onto every eligible touchpoint and records
    the outcome on the application: `eligible_touch_count` becomes the number of touchpoints in
    the input set, `attribution_model_applied` freezes the program's `attribution_model` value as
    it stood at this moment, and `attributed_credit_bp_total` becomes 10,000."

    Design: Difficulty/dual_variant_calc/attribution_linear_vs_position_based_on_identical_touch_set
    """
    _, _, channels, posting = _three_channel_program(api)

    decided = _qualify_across_three_channels(
        api, posting["id"], channels, "a1@example.com"
    )

    assert decided["status"] == "QUALIFIED", decided
    assert decided["attribution_model_applied"] == "LINEAR", decided
    assert decided["eligible_touch_count"] == 3, decided
    assert decided["attributed_credit_bp_total"] == 10000, decided
    credits = _credits_in_engine_order(api, decided["id"])
    assert credits == [3334, 3333, 3333], credits
    a.assert_basis_points_total(credits)


def test_position_based_attribution_reweights_the_identical_touch_set(api):
    """PRD §3.6: "Under `POSITION_BASED`, a single eligible touchpoint carries weight 1, two
    eligible touchpoints carry weights of 1 and 1, and with three or more the first touchpoint
    carries 4,000, the last carries 4,000, and each of the middle touchpoints carries 2,000
    divided by the number of middle touchpoints, held as an exact value — so the same three
    touches on the same application become 4,000 then 2,000 then 4,000 basis points."
    PRD §3.6: "The identical touchpoint set therefore yields a different per-channel credit
    picture depending on which model the program has chosen."

    Design: Difficulty/dual_variant_calc/attribution_linear_vs_position_based_on_identical_touch_set
    """
    program, _, channels, posting = _three_channel_program(api)
    board, social, programmatic = channels
    linear_application = _qualify_across_three_channels(
        api, posting["id"], channels, "a1@example.com"
    )

    switch = api.update_program(
        program["id"], {"attribution_model": "POSITION_BASED"}, brand_lead_headers()
    )
    validate_success(switch, 200)
    position_application = _qualify_across_three_channels(
        api, posting["id"], channels, "a2@example.com"
    )

    assert linear_application["attribution_model_applied"] == "LINEAR", linear_application
    assert position_application["attribution_model_applied"] == "POSITION_BASED", (
        position_application
    )
    assert position_application["eligible_touch_count"] == 3, position_application
    assert position_application["attributed_credit_bp_total"] == 10000, position_application
    position_credits = _credits_in_engine_order(api, position_application["id"])
    assert position_credits == [4000, 2000, 4000], position_credits
    assert fx.read_channel(api, board["id"])["credited_qualified_bp"] == 7334
    assert fx.read_channel(api, social["id"])["credited_qualified_bp"] == 5333
    assert fx.read_channel(api, programmatic["id"])["credited_qualified_bp"] == 7333
    social_row = fx.read_channel(api, social["id"])
    a.assert_cents(social_row["blended_target_cents"], 15000, "blended_target_cents")
    a.assert_cents(social_row["cpqa_cents"], 0, "cpqa_cents")
    assert social_row["pacing_status"] == "ON_TARGET", social_row


def _seven_touch_qualification(api):
    program = fx.create_program(api)
    family = fx.create_job_family(api, program["id"])
    channel = fx.create_channel(api, program["id"])
    posting = fx.published_posting(api, family["id"], channel["id"])
    application = fx.start_application(api, posting["id"])
    for occurred_at, touch_type in zip(SEVEN_TOUCH_INSTANTS, SEVEN_TOUCH_TYPES):
        fx.add_touchpoint(
            api, application["id"], channel["id"], occurred_at, touch_type=touch_type
        )
    fx.submit_application(api, application["id"])
    fx.screen_application(api, application["id"])
    decided = fx.decide_application(api, application["id"], "QUALIFIED")
    return channel, decided


def test_seven_linear_touches_floor_then_award_the_shortfall_to_the_earliest_rows(api):
    """PRD §2.5: "Where a formula distributes a fixed total of ten thousand basis points across
    several rows, the distribution uses floor-then-largest-remainder: each row's exact share is
    floored, the shortfall between the sum of floors and ten thousand is counted, and that many
    single basis points are awarded to the rows with the largest fractional parts."
    PRD §3.6: "Exactly ten thousand basis points are then distributed, in the pinned order
    described in §2.5. Each touchpoint's exact share is ten thousand multiplied by its own weight
    and divided by the sum of all the weights; each exact share is rounded down to a whole basis
    point; the shortfall between the sum of those floors and ten thousand is counted; and one
    extra basis point is awarded to each of that many touchpoints with the largest fractional
    parts, ties broken by `occurred_at` ascending and then `created_at` ascending."

    Design: Difficulty/combinatorial_formula/linear_attribution_remainder_uses_floor_then_largest_remainder_mode_b
    """
    _, decided = _seven_touch_qualification(api)

    assert decided["status"] == "QUALIFIED", decided
    assert decided["eligible_touch_count"] == 7, decided
    credits = _credits_in_engine_order(api, decided["id"])
    assert credits == [1429, 1429, 1429, 1429, 1428, 1428, 1428], credits


def test_seven_linear_touches_total_exactly_ten_thousand_basis_points(api):
    """PRD §2.5: "Rounding each row's exact share half up independently is explicitly wrong — it
    can total 9,999 or 10,001 — and any implementation that does so will disagree with the
    specification."
    PRD §3.6: "Hop two follows because those credits changed: each channel's
    `credited_qualified_bp` rises by the `credit_bp` of each of its touchpoints, and each flight's
    `qualified_credit_bp` rises by the `credit_bp` of the touchpoints whose `media_flight_id`
    names it."

    Design: Difficulty/combinatorial_formula/linear_attribution_remainder_uses_floor_then_largest_remainder_mode_b
    """
    channel, decided = _seven_touch_qualification(api)

    credits = _credits_in_engine_order(api, decided["id"])
    total = sum(credits)
    assert total == 10000, f"credit must total 10000 basis points, got {total}"
    assert total != 10003, "each share was rounded half up independently"
    assert total != 9996, "the floor shortfall was never redistributed"
    assert decided["attributed_credit_bp_total"] == 10000, decided
    assert fx.read_channel(api, channel["id"])["credited_qualified_bp"] == 10000


def _two_qualified_applications_on_two_channels(api):
    """Two qualified applications sharing a social channel, one of them also touched a board."""
    program = fx.create_program(api)
    family = fx.create_job_family(api, program["id"])
    board = fx.create_channel(api, program["id"], name="Board A", channel_type="JOB_BOARD")
    social = fx.create_channel(api, program["id"], name="Social B", channel_type="SOCIAL")
    posting = fx.published_posting(api, family["id"], board["id"])
    fx.move_clock(api, "2026-08-02T00:00:00Z")
    first = fx.start_application(api, posting["id"], "a1@example.com")
    fx.add_touchpoint(api, first["id"], board["id"], "2026-08-01T09:00:00Z")
    fx.add_touchpoint(api, first["id"], social["id"], "2026-08-01T10:00:00Z")
    fx.submit_application(api, first["id"])
    fx.screen_application(api, first["id"])
    fx.decide_application(api, first["id"], "QUALIFIED")
    second = fx.start_application(api, posting["id"], "a2@example.com")
    fx.add_touchpoint(api, second["id"], social["id"], "2026-08-01T11:00:00Z")
    fx.submit_application(api, second["id"])
    fx.screen_application(api, second["id"])
    fx.decide_application(api, second["id"], "QUALIFIED")
    return board, social, posting, first, second


def _conversion(api, posting_id):
    response = api.get_job_posting_conversion(posting_id, brand_lead_headers())
    return validate_success(response, 200)


def test_credited_basis_points_across_channels_equal_ten_thousand_per_qualified_application(api):
    """PRD §3.6: "Every touchpoint of the application has its `credit_bp` set back to 0, and each
    affected channel's `credited_qualified_bp` and each affected flight's `qualified_credit_bp`
    are lowered by precisely the amounts removed — so that the global identity holds: the sum of
    `credited_qualified_bp` across all channels always equals ten thousand multiplied by the
    number of applications currently in `QUALIFIED`."
    PRD §3.3: "`conversion_rate_bp` is null while `apply_start_count` is 0, and otherwise is ten
    thousand multiplied by `submitted_count`, divided by `apply_start_count`, and rounded down to
    a whole basis point."

    Design: Difficulty/compensating_invariant/attribution_basis_points_stay_conserved_when_a_qualified_application_is_disqualified
    """
    board, social, posting, first, second = _two_qualified_applications_on_two_channels(api)

    assert _credits_in_engine_order(api, first["id"]) == [5000, 5000]
    assert _credits_in_engine_order(api, second["id"]) == [10000]
    board_bp = fx.read_channel(api, board["id"])["credited_qualified_bp"]
    social_bp = fx.read_channel(api, social["id"])["credited_qualified_bp"]
    assert board_bp == 5000, board_bp
    assert social_bp == 15000, social_bp
    assert board_bp + social_bp == 20000, (board_bp, social_bp)
    conversion = _conversion(api, posting["id"])
    assert conversion["apply_start_count"] == 2, conversion
    assert conversion["submitted_count"] == 2, conversion
    assert conversion["qualified_count"] == 2, conversion
    assert conversion["conversion_rate_bp"] == 10000, conversion


def test_disqualifying_a_qualified_application_removes_exactly_its_own_credit(api):
    """PRD §3.6: "**Disqualification from `QUALIFIED`** is a compensating action that must undo
    hop one and hop two exactly."
    PRD §3.6: "The application's `attributed_credit_bp_total` returns to 0 and its
    `attribution_model_applied` returns to null, and the posting's `qualified_count` falls by 1."
    PRD §3.6: "Each affected channel's measured cost is then recomputed: a channel whose
    `credited_qualified_bp` has returned to zero goes back to `pacing_status` `PACING_UNKNOWN`
    with both `cpqa_cents` and `blended_target_cents` null."

    Design: Difficulty/compensating_invariant/attribution_basis_points_stay_conserved_when_a_qualified_application_is_disqualified
    """
    board, social, posting, first, second = _two_qualified_applications_on_two_channels(api)

    reversed_application = fx.decide_application(
        api, first["id"], "DISQUALIFIED", reason="withdrew from the process"
    )

    assert reversed_application["status"] == "DISQUALIFIED", reversed_application
    assert reversed_application["attributed_credit_bp_total"] == 0, reversed_application
    assert reversed_application["attribution_model_applied"] is None, reversed_application
    assert reversed_application["eligible_touch_count"] == 2, reversed_application
    assert _credits_in_engine_order(api, first["id"]) == [0, 0]
    assert _credits_in_engine_order(api, second["id"]) == [10000]
    board_row = fx.read_channel(api, board["id"])
    social_row = fx.read_channel(api, social["id"])
    assert board_row["credited_qualified_bp"] == 0, board_row
    assert board_row["cpqa_cents"] is None, board_row
    assert board_row["blended_target_cents"] is None, board_row
    assert board_row["pacing_status"] == "PACING_UNKNOWN", board_row
    assert social_row["credited_qualified_bp"] == 10000, social_row
    a.assert_cents(social_row["blended_target_cents"], 15000, "blended_target_cents")
    a.assert_cents(social_row["cpqa_cents"], 0, "cpqa_cents")
    assert social_row["pacing_status"] == "ON_TARGET", social_row
    assert (
        board_row["credited_qualified_bp"] + social_row["credited_qualified_bp"] == 10000
    ), (board_row, social_row)
    conversion = _conversion(api, posting["id"])
    assert conversion["qualified_count"] == 1, conversion
    assert conversion["submitted_count"] == 2, conversion
    assert conversion["conversion_rate_bp"] == 10000, conversion
