"""The two independent status dimensions, and the comment-window coupling."""
from test_helpers import (
    ApiErrorId,
    fixtures,
    get_success_data,
    make_council_admin_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_01_analysis_dimension_reaches_complete_while_review_stays_screened(api):
    """A proposal "carries **two independent status dimensions on the same
    row**", and each dimension-two move "increments the proposal's `version` by
    one and touches `review_status` not at all". So the walk `PENDING` →
    `PARTIAL` → `COMPLETE` over two analysis acceptances leaves `review_status`
    pinned at `SCREENED`, a combination reachable with no review transition at
    all. `energy_analysis_required` "is true when the proposal's `discipline` is
    `ENERGY` or its `stringency_direction` is `MORE_STRINGENT`".

    Design: Difficulty/non_linear_state_machine/amendment_proposal_parallel_dimensions_advance_independently
    """
    world = fixtures.setup_proposal_with_accepted_cost_benefit(api)

    before = fixtures.read_proposal(api, world["proposal_id"])
    assert before["analysis_status"] == "PARTIAL"
    assert before["review_status"] == "SCREENED"

    fixtures.file_energy_impact_analysis(api, world)
    fixtures.review_analysis(api, world["energy_impact_id"])

    proposal = fixtures.read_proposal(api, world["proposal_id"])
    assert proposal["analysis_status"] == "COMPLETE"
    assert proposal["review_status"] == "SCREENED"
    assert proposal["energy_analysis_required"] is True


def test_02_completing_the_analysis_dimension_opens_no_comment_window(api):
    """"`comment_window_status` begins at `NONE`" and only "opening a window"
    moves it, so a proposal that has merely finished its analyses still reads
    `NONE` with `comment_round` at 0, while both analyses stand `ACCEPTED` and
    the certified cost absorbed from the `COST_BENEFIT` filing stands.

    Design: Difficulty/non_linear_state_machine/amendment_proposal_parallel_dimensions_advance_independently
    """
    world = fixtures.setup_proposal_with_accepted_cost_benefit(api)
    fixtures.file_energy_impact_analysis(api, world)
    fixtures.review_analysis(api, world["energy_impact_id"])

    proposal = fixtures.read_proposal(api, world["proposal_id"])
    assert proposal["comment_window_status"] == "NONE"
    assert proposal["comment_round"] == 0
    assert proposal["statewide_incremental_cost_cents"] == 143002800

    cost_benefit = get_success_data(
        api.get_impact_analysis(world["cost_benefit_id"], make_council_admin_headers())
    )
    energy_impact = get_success_data(
        api.get_impact_analysis(world["energy_impact_id"], make_council_admin_headers())
    )
    assert cost_benefit["status"] == "ACCEPTED"
    assert energy_impact["status"] == "ACCEPTED"


def _partial_analysis_world(api):
    """A proposal that owes an ENERGY_IMPACT analysis nobody has filed, in a
    cycle that would otherwise admit a comment window."""
    world = fixtures.setup_proposal_with_accepted_cost_benefit(api)
    fixtures.set_cycle_status(api, world["cycle_id"], "DELIBERATION")
    return world


def test_03_a_window_is_refused_while_the_analysis_dimension_is_partial(api):
    """"The proposal's `analysis_status` must be `COMPLETE`, or the request is
    refused with `ERR_ANALYSIS_INCOMPLETE` — this is the first of the two
    couplings between the status dimensions." With only the `COST_BENEFIT`
    analysis accepted the dimension stands at `PARTIAL`, because the move
    `PARTIAL` → `COMPLETE` waits on "an `ACCEPTED` `ENERGY_IMPACT` analysis" that
    was never filed.

    Design: Difficulty/cross_entity_state_dependency/comment_window_open_blocked_until_analysis_dimension_complete
    """
    world = _partial_analysis_world(api)

    response = fixtures.open_comment_window(api, world)
    validate_error(response, ApiErrorId.ERR_ANALYSIS_INCOMPLETE, 409)


def test_04_the_refused_window_leaves_both_dimensions_where_they_were(api):
    """Only a successful open "advances `review_status` `SCREENED` →
    `COMMENT_OPEN`" and moves `comment_window_status` "from `NONE` or `CLOSED` to
    `OPEN`" with "`comment_round` increments by one", so the refusal leaves
    `SCREENED`, `PARTIAL`, `NONE` and round 0 intact.

    Design: Difficulty/cross_entity_state_dependency/comment_window_open_blocked_until_analysis_dimension_complete
    """
    world = _partial_analysis_world(api)

    fixtures.open_comment_window(api, world)

    proposal = fixtures.read_proposal(api, world["proposal_id"])
    assert proposal["review_status"] == "SCREENED"
    assert proposal["analysis_status"] == "PARTIAL"
    assert proposal["comment_window_status"] == "NONE"
    assert proposal["comment_round"] == 0


def test_05_a_window_spanning_exactly_thirty_days_is_accepted(api):
    """"The requested window must span at least 30 days from `opens_at` to
    `closes_at`, inclusive at the boundary: exactly 30 days is accepted, 29 days
    and 23 hours 59 minutes 59 seconds is not". 2026-08-10T00:00:00Z to
    2026-09-09T00:00:00Z is exactly 30 days, so the open succeeds and the
    proposal advances `SCREENED` → `COMMENT_OPEN`.

    Design: Difficulty/boundary_precision_check/comment_window_of_exactly_thirty_days_is_accepted
    """
    world = fixtures.setup_proposal_ready_for_comment(api)

    response = fixtures.open_comment_window(
        api,
        world,
        opens_at=fixtures.COMMENT_OPENS_AT,
        closes_at=fixtures.COMMENT_CLOSES_AT,
    )
    validate_success(response, 200)

    proposal = fixtures.read_proposal(api, world["proposal_id"])
    assert proposal["review_status"] == "COMMENT_OPEN"
    assert proposal["comment_window_status"] == "OPEN"
    assert proposal["comment_opens_at"] == "2026-08-10T00:00:00Z"
    assert proposal["comment_closes_at"] == "2026-09-09T00:00:00Z"


def test_06_the_boundary_window_starts_a_fresh_round_with_empty_tallies(api):
    """On a successful open "`comment_round` increments by one,
    `comment_extension_count` resets to 0, and the three tallies
    `support_comment_count`, `oppose_comment_count` and `total_comment_count`
    reset to 0 for the fresh round", and no comment has yet been submitted.

    Design: Difficulty/boundary_precision_check/comment_window_of_exactly_thirty_days_is_accepted
    """
    world = fixtures.setup_proposal_ready_for_comment(api)

    fixtures.open_comment_window(
        api,
        world,
        opens_at=fixtures.COMMENT_OPENS_AT,
        closes_at=fixtures.COMMENT_CLOSES_AT,
    )

    proposal = fixtures.read_proposal(api, world["proposal_id"])
    assert proposal["comment_round"] == 1
    assert proposal["comment_extension_count"] == 0
    assert proposal["total_comment_count"] == 0

    _, meta = validate_paginated(
        api.list_proposal_comments(world["proposal_id"], make_council_admin_headers())
    )
    assert meta["total_count"] == 0
