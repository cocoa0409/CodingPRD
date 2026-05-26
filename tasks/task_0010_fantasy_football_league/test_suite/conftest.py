"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_commissioner_headers,
    make_team_owner_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def commissioner_headers():
    """Shared Commissioner header constant. Commissioner identity is opaque
    per PRD §2.1, so the shared constant is canonical.
    """
    return TEST_USERS["commissioner_headers"]


@pytest.fixture
def team_owner_headers():
    """Shared TeamOwner header constant.

    USE ONLY for non-ownership-gated calls (list-resource GETs that don't
    assert ownership). For ownership-gated calls, build per-team headers via
    make_team_owner_headers(team["id"]) per PRD §2.1.
    """
    return TEST_USERS["team_owner_headers"]


@pytest.fixture
def headers_factory():
    """Factory exposing builder functions so tests can mint per-team headers."""
    return {
        "commissioner": make_commissioner_headers,
        "team_owner": make_team_owner_headers,
    }
