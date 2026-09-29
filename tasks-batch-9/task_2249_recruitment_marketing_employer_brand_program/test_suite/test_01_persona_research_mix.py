"""Channel-mix research: the two weighting variants over one identical signal set."""
from typing import Any, Dict, Tuple

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.api_client import ApiClient

#: The two research signals both personas are given, in collection order.
BOARD_SIGNAL = {
    "preference_score": 80,
    "sample_size": 300,
    "engagement_events": 100,
    "collected_at": "2026-07-31T00:00:00Z",
}
SOCIAL_SIGNAL = {
    "preference_score": 40,
    "sample_size": 100,
    "engagement_events": 500,
    "collected_at": "2026-05-03T00:00:00Z",
}


def _program_with_two_channels(api: ApiClient) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """A job family plus a job-board channel and a social channel, created in that order."""
    program = fx.create_program(api)
    family = fx.create_job_family(api, program["id"])
    board = fx.create_channel(api, program["id"], name="Board A", channel_type="JOB_BOARD")
    social = fx.create_channel(api, program["id"], name="Social B", channel_type="SOCIAL")
    return family, board, social


def _persona_with_both_signals(
    api: ApiClient,
    family_id: str,
    board_id: str,
    social_id: str,
    name: str,
    mix_method: str,
) -> Dict[str, Any]:
    persona = fx.create_persona(
        api, family_id, name=name, mix_method=mix_method, research_window_days=180
    )
    fx.add_signal(api, persona["id"], board_id, **BOARD_SIGNAL)
    fx.add_signal(api, persona["id"], social_id, **SOCIAL_SIGNAL)
    return persona


def test_survey_weighted_mix_weights_by_sample_size_without_decay(api):
    """PRD §3.2: "Under `SURVEY_WEIGHTED`, a signal's weight is simply its `sample_size`,
    with no time decay at all — the practical consequence being that an old survey with a
    large respondent base can dominate the mix indefinitely."
    PRD §3.2: "When the grand total is positive, exactly ten thousand basis points are
    distributed across the channels: each channel's exact share is ten thousand multiplied
    by that channel's raw score and divided by the grand total, each exact share is rounded
    down to a whole basis point, the shortfall between the sum of those floors and ten
    thousand is counted, and one additional basis point is awarded to each of that many
    channels with the largest fractional parts, ties broken by the channel's `created_at`
    ascending and then the channel's `name` ascending — never by the channel's `id`."

    Design: Difficulty/dual_variant_calc/persona_mix_survey_weighted_vs_engagement_weighted_on_identical_signals
    """
    family, board, social = _program_with_two_channels(api)
    persona = _persona_with_both_signals(
        api, family["id"], board["id"], social["id"], "Survey Persona", "SURVEY_WEIGHTED"
    )

    submitted = fx.submit_persona(api, persona["id"])

    assert submitted["state"] == "IN_REVIEW", submitted
    assert submitted["signal_count"] == 2, submitted
    assert submitted["mix_confidence_pct"] == 40, submitted
    a.assert_channel_mix(
        submitted["channel_mix"], [(board["id"], 8571), (social["id"], 1429)]
    )


def test_engagement_weighted_mix_decays_the_older_signal_and_reverses_the_ranking(api):
    """PRD §3.2: "Under `ENGAGEMENT_WEIGHTED`, the signal's age in whole days is the elapsed
    time from `collected_at` to the logical clock divided by 86,400 seconds and rounded down;
    a decay percentage is then 100 less 10 for each complete 30-day step of that age, with
    the number of complete steps obtained by rounding the age in days divided by 30 down to a
    whole number, and the result held to a floor of 10 percent no matter how old the signal
    is; the signal's weight is its `engagement_events` multiplied by that decay percentage and
    divided by 100, kept as an exact value with no rounding."
    PRD §3.2: "The resulting `channel_mix` is an array of objects each pairing a `channel_id`
    with its `share_bp`, containing only channels whose raw score was greater than zero,
    ordered by `share_bp` descending and then by the channel's `created_at` ascending."

    Design: Difficulty/dual_variant_calc/persona_mix_survey_weighted_vs_engagement_weighted_on_identical_signals
    """
    family, board, social = _program_with_two_channels(api)
    survey_persona = _persona_with_both_signals(
        api, family["id"], board["id"], social["id"], "Survey Persona", "SURVEY_WEIGHTED"
    )
    engagement_persona = _persona_with_both_signals(
        api, family["id"], board["id"], social["id"], "Engagement Persona", "ENGAGEMENT_WEIGHTED"
    )

    survey = fx.submit_persona(api, survey_persona["id"])
    engagement = fx.submit_persona(api, engagement_persona["id"])

    assert engagement["state"] == "IN_REVIEW", engagement
    assert engagement["signal_count"] == 2, engagement
    assert engagement["mix_confidence_pct"] == 40, engagement
    a.assert_channel_mix(
        engagement["channel_mix"], [(social["id"], 6364), (board["id"], 3636)]
    )
    survey_ranking = [entry["channel_id"] for entry in survey["channel_mix"]]
    engagement_ranking = [entry["channel_id"] for entry in engagement["channel_mix"]]
    assert engagement_ranking == list(reversed(survey_ranking)), (
        f"the two variants must rank the same signals oppositely: "
        f"{survey_ranking} vs {engagement_ranking}"
    )
