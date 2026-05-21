"""Pytest fixtures exposing test_helpers infrastructure.

The runner injects API_BASE_URL and PYTHONPATH; this file only wires
test_helpers symbols into pytest fixtures so individual tests can
request them as parameters.

PRD §2.1: Coach, Referee, and Guardian are entity_backed. The shared-
constant fixtures (`coach_headers`, `referee_headers`,
`guardian_headers`) below are placeholder probes used only for tests
that exercise auth, role-forbidden, or 404 paths WITHOUT exercising
ownership. Tests that exercise ownership mint headers via
`make_*_headers(entity_id)` with the actual id.

FIELD-ID NAMESPACING (test isolation): the implementation correctly
enforces PRD §2.7 field-overlap across all games in the store. Tests
share that store across the session, so two independent tests both
writing "F1" at the same wall-clock window would collide. The autouse
fixture below namespaces `field_id` in create_game / reschedule_game
payloads by a per-test prefix so each test operates in its own field
namespace while still preserving the equivalence ("F1" == "F1") inside
one test and the inequality ("F1" != "F2") inside one test.
"""
from __future__ import annotations

import uuid

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
)


# ===========================================================================
# Per-test field-id namespacing (test isolation, NOT a PRD behavior).
# ===========================================================================
@pytest.fixture(autouse=True)
def _isolate_field_ids(monkeypatch, request):
    """Prefix `field_id` in create_game / reschedule_game payloads with a
    per-test salt so tests don't leak field state into each other.

    The PRD treats `field_id` as an opaque caller-supplied string; the
    server only compares strings. Prefixing preserves all equivalence
    and inequality relations inside a single test.
    """
    salt = f"t{uuid.uuid4().hex[:8]}_"

    real_create = api_client.create_game
    real_reschedule = api_client.reschedule_game

    def _ns(field_id):
        if field_id is None:
            return field_id
        if isinstance(field_id, str) and field_id.startswith(salt):
            return field_id
        return f"{salt}{field_id}"

    def patched_create_game(payload, headers):
        if isinstance(payload, dict) and "field_id" in payload \
                and isinstance(payload["field_id"], str):
            payload = dict(payload)
            payload["field_id"] = _ns(payload["field_id"])
        return real_create(payload, headers)

    def patched_reschedule_game(game_id, payload, headers):
        if isinstance(payload, dict) and "field_id" in payload \
                and isinstance(payload["field_id"], str):
            payload = dict(payload)
            payload["field_id"] = _ns(payload["field_id"])
        return real_reschedule(game_id, payload, headers)

    monkeypatch.setattr(api_client, "create_game", patched_create_game)
    monkeypatch.setattr(
        api_client, "reschedule_game", patched_reschedule_game,
    )
    yield


# ===========================================================================
# Session-scoped API client — server lifecycle is managed by the runner.
# ===========================================================================
@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


# ===========================================================================
# Shared-constant role headers — for non-ownership paths only.
# ===========================================================================
@pytest.fixture
def league_admin_headers():
    return TEST_USERS["league_admin_headers"]


@pytest.fixture
def league_admin_secondary_headers():
    return TEST_USERS["league_admin_secondary_headers"]


@pytest.fixture
def coach_headers():
    """Placeholder Coach headers — NOT tied to any real coach. Use only
    for auth, role-forbidden, or 404 probes."""
    return TEST_USERS["coach_headers"]


@pytest.fixture
def referee_headers():
    """Placeholder Referee headers — NOT tied to any real referee. Use
    only for auth, role-forbidden, or 404 probes."""
    return TEST_USERS["referee_headers"]


@pytest.fixture
def guardian_headers():
    """Placeholder Guardian headers — NOT tied to any real guardian. Use
    only for auth, role-forbidden, or 404 probes."""
    return TEST_USERS["guardian_headers"]
