"""Pytest fixtures exposing test_helpers infrastructure.

The runner restarts the API server before every pytest test, so every test
begins against an empty database. Each test pins the clock and constructs
its own preconditions through the helpers in test_helpers.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def planner_headers():
    return TEST_USERS["scheduling_planner_headers"]


@pytest.fixture
def ops_headers():
    return TEST_USERS["operations_controller_headers"]


@pytest.fixture
def crew_headers():
    """Generic CrewMember headers — only safe for non-ownership tests.
    Ownership-gated calls must use `make_crew_member_headers(cm_id)`."""
    return TEST_USERS["crew_member_headers"]
