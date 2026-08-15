"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the test runner; tests assume the API is
already reachable at API_BASE_URL and that the database starts empty for
every test.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def claims_examiner_headers():
    return TEST_USERS["claims_examiner_headers"]


@pytest.fixture
def actuarial_analyst_headers():
    return TEST_USERS["actuarial_analyst_headers"]


@pytest.fixture
def peer_reviewer_headers():
    return TEST_USERS["peer_reviewer_headers"]


@pytest.fixture
def appointed_actuary_headers():
    return TEST_USERS["appointed_actuary_headers"]
