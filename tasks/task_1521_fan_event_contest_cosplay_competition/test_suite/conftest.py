"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; tests assume the server is
already running and reachable at API_BASE_URL.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def contest_lead_headers():
    return TEST_USERS["contest_lead_headers"]


@pytest.fixture
def contestant_headers():
    return TEST_USERS["contestant_headers"]


@pytest.fixture
def judge_headers():
    return TEST_USERS["judge_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def stage_manager_headers():
    return TEST_USERS["stage_manager_headers"]


@pytest.fixture
def treasurer_headers():
    return TEST_USERS["treasurer_headers"]


@pytest.fixture
def treasurer_2_headers():
    return TEST_USERS["treasurer_2_headers"]
