"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def jury_administrator_headers():
    return TEST_USERS["jury_administrator_headers"]


@pytest.fixture
def court_clerk_headers():
    return TEST_USERS["court_clerk_headers"]


@pytest.fixture
def judge_headers():
    return TEST_USERS["judge_headers"]


@pytest.fixture
def juror_headers():
    return TEST_USERS["juror_headers"]
