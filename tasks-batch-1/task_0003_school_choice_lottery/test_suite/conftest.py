"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is owned by the runner; this file only wires pytest fixtures.
Under per-test-server isolation, every test begins against an empty database,
so each test pins the clock and constructs its own preconditions through the
composite helpers in test_helpers.fixtures.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def district_admin_headers():
    return TEST_USERS["district_admin_headers"]


@pytest.fixture
def guardian_headers():
    """Generic Guardian headers (X-User-ID = fallback). Do NOT use for
    ownership-gated calls — use make_guardian_headers(family_id) instead."""
    return TEST_USERS["guardian_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
