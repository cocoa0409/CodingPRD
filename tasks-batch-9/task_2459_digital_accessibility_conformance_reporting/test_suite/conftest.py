"""Pytest fixtures exposing the shared test infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def lead_headers():
    return TEST_USERS["lead_headers"]


@pytest.fixture
def tester_headers():
    return TEST_USERS["tester_headers"]


@pytest.fixture
def second_tester_headers():
    return TEST_USERS["second_tester_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def second_reviewer_headers():
    return TEST_USERS["second_reviewer_headers"]


@pytest.fixture
def liaison_headers():
    return TEST_USERS["liaison_headers"]
