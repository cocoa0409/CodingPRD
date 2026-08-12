"""Scene-window geometry and fiscal boundaries (PRD §3.2, §3.4, §2.8)."""
from test_helpers import (
    ApiErrorId,
    create_brand,
    create_episode,
    create_open_brief,
    create_opportunity,
    create_opportunity_payload,
    create_proposal,
    create_proposal_payload,
    create_series,
    get_brief,
    get_opportunity,
    get_success_data,
    list_episode_opportunities,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

MANAGER = TEST_USERS["manager_headers"]
PROD = TEST_USERS["production_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _brief_episode(api, budget_cents=1_000_000):
    brand = create_brand()
    brief = create_open_brief(brand["id"], budget_cents=budget_cents)
    series = create_series()
    episode = create_episode(series["id"])
    return brand, brief, series, episode


def test_scene_window_half_open_overlap(api):
    """PRD §3.2: "a new window is rejected with `ERR_SCENE_WINDOW_OVERLAP`
    (HTTP 409) when it intersects — under half-open semantics, where the start
    is inclusive and the end exclusive — any existing opportunity of the same
    episode in `IDENTIFIED`, `PITCHED`, or `RESERVED`; two windows that merely
    touch, one ending exactly where the other begins, do not overlap."

    Design: Difficulty/resource_temporal_overlap/scene_window_half_open_overlap
    """
    series = create_series()
    episode = create_episode(series["id"])
    create_opportunity(episode["id"], start=0, end=40, estimated_exposure_seconds=20)

    touching = validate_success(
        api.create_opportunity(
            episode["id"],
            create_opportunity_payload(
                scene_description="Garage",
                start_timecode_seconds=40,
                end_timecode_seconds=80,
                estimated_exposure_seconds=20,
            ),
            PROD,
        ),
        expected_status=201,
    )
    assert touching["status"] == "IDENTIFIED", (
        f"touching at 40 is not an overlap; got {touching['status']}"
    )

    resp = api.create_opportunity(
        episode["id"],
        create_opportunity_payload(
            scene_description="Hall",
            start_timecode_seconds=39,
            end_timecode_seconds=41,
            estimated_exposure_seconds=2,
        ),
        PROD,
    )
    validate_error(resp, ApiErrorId.ERR_SCENE_WINDOW_OVERLAP)

    rows = list_episode_opportunities(episode["id"])
    assert len(rows) == 2, f"only the two non-overlapping windows exist, got {len(rows)}"


def test_scene_window_touching_endpoints_coexist(api):
    """PRD §3.2: "two windows that merely touch, one ending exactly where the
    other begins, do not overlap."

    Design: Difficulty/resource_temporal_overlap/scene_window_half_open_overlap
    """
    series = create_series()
    episode = create_episode(series["id"])
    create_opportunity(episode["id"], start=0, end=40, estimated_exposure_seconds=20)
    # Both directions of touching: [40,80) after [0,40), then [0,40) touch at 40 again
    touching = validate_success(
        api.create_opportunity(
            episode["id"],
            create_opportunity_payload(
                scene_description="Garage",
                start_timecode_seconds=40,
                end_timecode_seconds=80,
                estimated_exposure_seconds=20,
            ),
            PROD,
        ),
        expected_status=201,
    )
    assert touching["status"] == "IDENTIFIED"
    rows = list_episode_opportunities(episode["id"])
    assert len(rows) == 2, f"both touching windows coexist, got {len(rows)}"


def test_opportunity_conflict_beats_budget_on_proposal_create(api):
    """PRD §2.8: "Every request is validated against an ordered pipeline; the
    first stage that fails determines the response, so an earlier failure
    always masks any later failure that would also have applied." PRD §2.8:
    stage 8 "Business constraints" include "opportunity availability for
    proposal creation (`ERR_OPPORTUNITY_UNAVAILABLE`, HTTP 409)"; stage 11
    "Fiscal rules" include the budget ceiling — stage 8 precedes stage 11.

    Design: Difficulty/priority_pair_validation_conflict/opportunity_conflict_beats_budget_on_proposal_create
    """
    brand, brief, series, episode = _brief_episode(api, budget_cents=100_000)
    opportunity = create_opportunity(episode["id"])
    proposal_a = create_proposal(
        brief["id"],
        opportunity["id"],
        proposed_fee_cents=60_000,
        guaranteed_seconds=10,
        rate_cents_per_second=2000,
    )
    get_success_data(api.submit_proposal(proposal_a["id"], MANAGER))
    # remaining budget now 40000; the opportunity is PITCHED.
    resp = api.create_proposal(
        create_proposal_payload(
            brief["id"],
            opportunity["id"],
            proposed_fee_cents=50_000,
            guaranteed_seconds=10,
            rate_cents_per_second=2000,
        ),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_OPPORTUNITY_UNAVAILABLE)
    brief_after = get_brief(brief["id"])
    assert brief_after["remaining_budget_cents"] == 40_000, (
        f"rejected create must not move the budget, got {brief_after['remaining_budget_cents']}"
    )


def test_opportunity_conflict_beats_budget_on_proposal_create_unchanged(api):
    """PRD §3.4: "the referenced opportunity must be `IDENTIFIED`
    (`ERR_OPPORTUNITY_UNAVAILABLE`, HTTP 409)". PRD §2.8: "the first stage that
    fails determines the response, so an earlier failure always masks any later
    failure that would also have applied."

    Design: Difficulty/priority_pair_validation_conflict/opportunity_conflict_beats_budget_on_proposal_create
    """
    brand, brief, series, episode = _brief_episode(api, budget_cents=100_000)
    opportunity = create_opportunity(episode["id"])
    proposal_a = create_proposal(
        brief["id"],
        opportunity["id"],
        proposed_fee_cents=60_000,
        guaranteed_seconds=10,
        rate_cents_per_second=2000,
    )
    get_success_data(api.submit_proposal(proposal_a["id"], MANAGER))

    resp = api.create_proposal(
        create_proposal_payload(
            brief["id"],
            opportunity["id"],
            proposed_fee_cents=50_000,
            guaranteed_seconds=10,
            rate_cents_per_second=2000,
        ),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_OPPORTUNITY_UNAVAILABLE)
    opp_after = get_opportunity(opportunity["id"])
    assert opp_after["status"] == "PITCHED", (
        f"the opportunity stays PITCHED under the first proposal, got {opp_after['status']}"
    )


def test_fee_equal_to_remaining_budget_allowed(api):
    """PRD §3.4: "it must not exceed the brief's current
    `remaining_budget_cents` (`ERR_BUDGET_EXCEEDED`, HTTP 422)" — a fee exactly
    equal to the remaining budget does not exceed it.

    Design: Difficulty/boundary_precision_check/fee_equal_to_remaining_budget_allowed
    """
    brand, brief, series, episode = _brief_episode(api, budget_cents=100_000)
    opp1 = create_opportunity(episode["id"], start=0, end=40, estimated_exposure_seconds=25)
    opp2 = create_opportunity(
        episode["id"], start=40, end=80, estimated_exposure_seconds=20,
        scene_description="Garage",
    )

    p1 = validate_success(
        api.create_proposal(
            create_proposal_payload(
                brief["id"],
                opp1["id"],
                proposed_fee_cents=100_000,
                guaranteed_seconds=10,
                rate_cents_per_second=2000,
            ),
            MANAGER,
        ),
        expected_status=201,
    )
    assert p1["status"] == "DRAFT", f"got {p1['status']}"

    resp = api.create_proposal(
        create_proposal_payload(
            brief["id"],
            opp2["id"],
            proposed_fee_cents=20_000,
            guaranteed_seconds=10,
            rate_cents_per_second=2000,
        ),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)
    brief_after = get_brief(brief["id"])
    assert brief_after["remaining_budget_cents"] == 0, (
        f"the first proposal holds the full budget, got {brief_after['remaining_budget_cents']}"
    )


def test_fee_one_cent_above_remaining_budget_rejected(api):
    """PRD §3.4: "it must not exceed the brief's current
    `remaining_budget_cents` (`ERR_BUDGET_EXCEEDED`, HTTP 422)" — 100001
    exceeds 100000.

    Design: Difficulty/boundary_precision_check/fee_equal_to_remaining_budget_allowed
    """
    brand, brief, series, episode = _brief_episode(api, budget_cents=100_000)
    opp1 = create_opportunity(episode["id"], start=0, end=40, estimated_exposure_seconds=25)
    resp = api.create_proposal(
        create_proposal_payload(
            brief["id"],
            opp1["id"],
            proposed_fee_cents=100_001,
            guaranteed_seconds=10,
            rate_cents_per_second=2000,
        ),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_BUDGET_EXCEEDED)
    brief_after = get_brief(brief["id"])
    assert brief_after["remaining_budget_cents"] == 100_000, (
        f"a rejected proposal holds nothing, got {brief_after['remaining_budget_cents']}"
    )


def test_scene_window_end_before_start_rejected(api):
    """PRD §3.2: "the start must be zero or greater, the end must be strictly
    greater than the start, and the end must not exceed the episode's
    `runtime_seconds`; a window failing any of these is rejected with
    `ERR_INVALID_SCENE_WINDOW` (HTTP 400)."

    Design: Corner/validations/scene_window_end_before_start_rejected
    """
    series = create_series()
    episode = create_episode(series["id"])
    resp = api.create_opportunity(
        episode["id"],
        create_opportunity_payload(
            scene_description="Broken",
            start_timecode_seconds=50,
            end_timecode_seconds=40,
            estimated_exposure_seconds=5,
        ),
        PROD,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_SCENE_WINDOW)


def test_opportunity_create_on_locked_episode_returns_invalid_state(api):
    """PRD §3.2: "While an episode is still in `SCRIPT_REVIEW`, the production
    team identifies integration opportunities in it." PRD §2.8 stage 6: "the
    target entity is in a valid from-state for the requested transition
    (`ERR_INVALID_STATE`, HTTP 409)".

    Design: Corner/validations/opportunity_create_on_locked_episode_returns_invalid_state
    """
    series = create_series()
    episode = create_episode(series["id"])
    get_success_data(api.lock_episode(episode["id"], PROD))
    resp = api.create_opportunity(
        episode["id"],
        create_opportunity_payload(
            scene_description="Late",
            start_timecode_seconds=0,
            end_timecode_seconds=40,
            estimated_exposure_seconds=5,
        ),
        PROD,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_proposal_create_on_aired_episode_rejected(api):
    """PRD §3.4: "the opportunity's episode must not yet have aired
    (`ERR_EPISODE_ALREADY_AIRED`)".

    Design: Corner/validations/proposal_create_on_aired_episode_rejected
    """
    from test_helpers import set_clock_payload

    brand, brief, series, episode = _brief_episode(api, budget_cents=1_000_000)
    opportunity = create_opportunity(episode["id"])
    get_success_data(api.lock_episode(episode["id"], PROD))
    get_success_data(api.set_clock(set_clock_payload("2026-06-02T00:00:00Z"), ADMIN))
    get_success_data(api.mark_episode_aired(episode["id"], PROD))

    resp = api.create_proposal(
        create_proposal_payload(
            brief["id"],
            opportunity["id"],
            proposed_fee_cents=60_000,
            guaranteed_seconds=10,
            rate_cents_per_second=2000,
        ),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_EPISODE_ALREADY_AIRED)


def test_proposal_fee_below_minimum_rejected(api):
    """PRD §3.4: "the proposed fee must be at least the guaranteed seconds
    multiplied by the per-second rate (`ERR_FEE_BELOW_MINIMUM`, HTTP 400)".
    PRD §3.4: "A created proposal immediately flips its opportunity from
    `IDENTIFIED` to `PITCHED`" — a rejected creation never flips it.

    Design: Corner/validations/proposal_fee_below_minimum_rejected
    """
    brand, brief, series, episode = _brief_episode(api, budget_cents=1_000_000)
    opportunity = create_opportunity(episode["id"])
    resp = api.create_proposal(
        create_proposal_payload(
            brief["id"],
            opportunity["id"],
            proposed_fee_cents=59_999,  # floor is 30 * 2000 = 60000
            guaranteed_seconds=30,
            rate_cents_per_second=2000,
        ),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_FEE_BELOW_MINIMUM)
    opp_after = get_opportunity(opportunity["id"])
    assert opp_after["status"] == "IDENTIFIED", (
        f"no PITCHED transition on failure, got {opp_after['status']}"
    )


def test_brief_not_open_blocks_proposal(api):
    """PRD §3.4: "the brief must be `OPEN` (`ERR_BRIEF_NOT_OPEN`)".

    Design: Corner/errors/brief_not_open_blocks_proposal
    """
    brand = create_brand()
    # Brief created but never submitted -> DRAFT.
    from test_helpers import create_brief_payload, make_brand_rep_headers

    rep = make_brand_rep_headers(brand["id"])
    brief = get_success_data(
        api.create_brief(brand["id"], create_brief_payload(budget_cents=1_000_000), rep)
    )
    assert brief["status"] == "DRAFT"
    series = create_series()
    episode = create_episode(series["id"])
    opportunity = create_opportunity(episode["id"])

    resp = api.create_proposal(
        create_proposal_payload(
            brief["id"],
            opportunity["id"],
            proposed_fee_cents=60_000,
            guaranteed_seconds=10,
            rate_cents_per_second=2000,
        ),
        MANAGER,
    )
    validate_error(resp, ApiErrorId.ERR_BRIEF_NOT_OPEN)


def test_budget_remaining_after_proposal_submit(api):
    """PRD §3.1: "The rule is always the same full computation — the brief's
    `budget_cents`, minus the sum of `proposed_fee_cents` over every proposal
    of the brief in `DRAFT`, `PRODUCTION_REVIEW`, `NETWORK_REVIEW`,
    `REVISION_REQUESTED`, or `APPROVED`".

    Design: Corner/calculations/budget_remaining_after_proposal_submit
    """
    brand, brief, series, episode = _brief_episode(api, budget_cents=100_000)
    opportunity = create_opportunity(episode["id"])
    create_proposal(
        brief["id"],
        opportunity["id"],
        proposed_fee_cents=60_000,
        guaranteed_seconds=10,
        rate_cents_per_second=2000,
    )
    brief_after = get_brief(brief["id"])
    assert brief_after["remaining_budget_cents"] == 40_000, (
        f"100000 - 60000 = 40000, got {brief_after['remaining_budget_cents']}"
    )
