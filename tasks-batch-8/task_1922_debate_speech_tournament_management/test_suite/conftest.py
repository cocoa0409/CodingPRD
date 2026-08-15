"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def tabstaff_headers():
    return TEST_USERS["tabstaff_headers"]


@pytest.fixture
def coach_headers():
    # Shared fallback: safe only for tests that do not exercise ownership.
    return TEST_USERS["coach_headers"]


@pytest.fixture
def judge_headers():
    # Shared fallback: safe only for tests that do not exercise ownership.
    return TEST_USERS["judge_headers"]
