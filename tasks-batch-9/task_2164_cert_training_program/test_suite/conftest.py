"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client.  Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def reviewer_coordinator_headers():
    return TEST_USERS["reviewer_coordinator_headers"]


@pytest.fixture
def issuer_coordinator_headers():
    return TEST_USERS["issuer_coordinator_headers"]


@pytest.fixture
def logistics_headers():
    return TEST_USERS["logistics_headers"]


@pytest.fixture
def emergency_headers():
    return TEST_USERS["emergency_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def instructor_headers():
    return TEST_USERS["instructor_headers"]


@pytest.fixture
def evaluator_headers():
    return TEST_USERS["evaluator_headers"]


@pytest.fixture
def trainee_headers():
    return TEST_USERS["trainee_headers"]
