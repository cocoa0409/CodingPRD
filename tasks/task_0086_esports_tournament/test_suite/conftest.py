"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest just
wires per-role headers and the session-scoped API client.

PRD §2.1 identity rules:
- LeagueAdmin is OPAQUE → shared constants are canonical.
- TeamManager is opaque but ownership-binding (X-User-ID must equal the
  manager_id on the registration). Tests that exercise team-side
  actions on a specific registration MUST use
  make_team_manager_headers(registration['manager_id']).
- Player is entity_backed:PlayerContract.player_id. Signing tests MUST
  use make_player_headers(contract['player_id']).
- Referee is entity_backed:Referee.user_id. Referee-acting tests MUST
  use make_referee_headers(referee['user_id']).

The fallback Player and Referee headers exposed here are for
ownership-irrelevant tests only (missing-auth, wrong-role, etc).
"""
from __future__ import annotations
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture(autouse=True)
def _reset_state_between_tests():
    """Wipe the implementation's in-memory store before each test so
    catalog state cannot leak. The /__test__/reset endpoint is a
    test-infrastructure extension parallel to the test-driver
    endpoints in PRD §2.7; a 404 from an implementation that does not
    expose it is tolerated for backward compatibility."""
    try:
        api_client._request("POST", "/__test__/reset", None, {})
    except Exception:
        pass
    yield


# ---------------------------------------------------------------------------
# LeagueAdmin headers (opaque — shared constants canonical)
# ---------------------------------------------------------------------------
@pytest.fixture
def league_admin_headers():
    return TEST_USERS["league_admin_headers"]


@pytest.fixture
def league_admin_headers_alt():
    return TEST_USERS["league_admin_headers_alt"]


# ---------------------------------------------------------------------------
# Team-manager / player / referee fallback headers (ownership-irrelevant)
# ---------------------------------------------------------------------------
@pytest.fixture
def team_manager_fallback_headers():
    """For tests that do NOT exercise ownership (missing-auth,
    wrong-role, missing-resource). For ownership-gated tests, use
    make_team_manager_headers(registration['manager_id'])."""
    return TEST_USERS["team_manager_headers"]


@pytest.fixture
def player_fallback_headers():
    """For tests that do NOT exercise ownership. For player-sign tests,
    use make_player_headers(contract['player_id'])."""
    return TEST_USERS["player_headers"]


@pytest.fixture
def referee_fallback_headers():
    """For tests that do NOT exercise ownership. For referee-acting
    tests, use make_referee_headers(referee['user_id'])."""
    return TEST_USERS["referee_headers"]
