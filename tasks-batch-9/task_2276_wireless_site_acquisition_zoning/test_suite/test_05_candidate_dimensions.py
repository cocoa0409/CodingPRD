"""The candidate's two state dimensions advance independently."""

from test_helpers import constants as C
from test_helpers import fixtures as S
from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_fields, assert_score, ok


def test_rf_qualification_moves_only_the_feasibility_dimension(api: ApiClient) -> None:
    """Scoring the candidate leaves the real-estate track untouched.

    PRD: "A candidate advances along **two independent state dimensions on one
    record**."

    PRD: "A score of at least 55.00 moves the feasibility dimension `UNSCREENED →
    RF_QUALIFIED`."

    PRD: "The resulting figure is clamped to the range 0 through 100 and only then
    rounded, half up, to two decimal places, and stored as
    `rf_qualification_score`."

    Design: Difficulty/non_linear_state_machine/candidate_parallel_dimensions_advance_independently
    """
    chain = S.base_reference_data(api)
    candidate = S.create_candidate(
        api, chain["ring_id"], chain["ll_id"], chain["jur_id"]
    )
    assert_fields(
        candidate, acquisition_status="PROSPECTING", feasibility_status="UNSCREENED"
    )

    scored = ok(api.rf_qualify(candidate["id"], headers=S.rf()))

    assert_fields(
        scored, feasibility_status="RF_QUALIFIED", acquisition_status="PROSPECTING"
    )
    assert_score(
        scored["rf_qualification_score"], C.CANDIDATE_RF_SCORE, "rf_qualification_score"
    )
    assert_fields(scored, outreach_event_count=0)


def test_an_outreach_event_moves_only_the_acquisition_dimension(api: ApiClient) -> None:
    """Recording outreach on a scored candidate does not disturb the score or its state.

    PRD: "An `OUTREACH_SENT` event moves the acquisition dimension `PROSPECTING →
    OUTREACH_SENT` and is only accepted while the candidate is in `PROSPECTING`."

    PRD: "Each recorded event increments `outreach_event_count` by one and
    increments the candidate's `version`."

    PRD: "The two dimensions advance through different operations and neither
    blocks the other except where a specific rule names the other dimension
    explicitly."

    Design: Difficulty/non_linear_state_machine/candidate_parallel_dimensions_advance_independently
    """
    chain = S.base_reference_data(api)
    candidate = S.create_candidate(
        api, chain["ring_id"], chain["ll_id"], chain["jur_id"]
    )
    S.rf_qualify(api, candidate["id"])

    ok(
        api.add_outreach_event(
            candidate["id"], {"event_type": "OUTREACH_SENT"}, headers=S.agent()
        )
    )

    after = ok(api.get_candidate(candidate["id"], headers=S.agent()))
    assert_fields(
        after,
        acquisition_status="OUTREACH_SENT",
        feasibility_status="RF_QUALIFIED",
        outreach_event_count=1,
    )
    assert_score(
        after["rf_qualification_score"], C.CANDIDATE_RF_SCORE, "rf_qualification_score"
    )
