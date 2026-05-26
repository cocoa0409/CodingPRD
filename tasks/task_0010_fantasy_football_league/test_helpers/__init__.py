"""Barrel export: framework generics + PRD-specific code."""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    validate_success,
    validate_error,
    validate_paginated,
    validate_error_is_one_of,
    get_success_data,
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
    assert_version_incremented,
    assert_timestamp_format,
    assert_race_outcome,
    assert_exactly_one_succeeds,
    assert_at_least_one_succeeds,
    run_race,
    build_user_headers,
    NON_EXISTENT_UUID,
)

# PRD-specific
from .types import *  # noqa: F401,F403
from .api_client import api_client, ApiClient
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import (
    assert_league,
    assert_team,
    assert_player,
    assert_draft_pick,
    assert_roster_slot,
    assert_waiver_claim,
    assert_trade,
    assert_veto_vote,
    assert_playoff_matchup,
    assert_total_faab_pool_invariant,
)
from .factories import (
    create_league_payload,
    create_team_payload,
    create_player_payload,
    create_draft_pick_payload,
    create_waiver_claim_payload,
    create_trade_payload,
    create_matchup_payload,
)
from .constants import (
    INJURY_PENALTY,
    KEEPER_FLOOR_ROUND,
    TEST_DEFAULTS,
)
from .test_users import (
    TEST_USERS,
    make_commissioner_headers,
    make_team_owner_headers,
)
from .fixtures import (
    set_clock,
    create_league,
    create_team,
    create_player,
    create_draft_pick,
    start_draft,
    finalize_draft,
    advance_week,
    draft_pairs_serpent,
    setup_in_season_league,
    propose_trade,
    accept_trade,
    cast_veto_vote,
    create_regular_matchup,
    start_matchup,
    finalize_matchup_with_scores,
    finalize_matchup_auto,
    set_lineup_for_team,
    submit_waiver_claim,
)
