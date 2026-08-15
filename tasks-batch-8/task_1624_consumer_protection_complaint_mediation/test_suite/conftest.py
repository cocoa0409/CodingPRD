"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def consumer_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["consumer_headers"]


@pytest.fixture
def business_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["business_headers"]


@pytest.fixture
def mediator_headers():
    # Shared fallback: only safe for tests that do not exercise ownership.
    return TEST_USERS["mediator_headers"]


@pytest.fixture
def intake_officer_headers():
    return TEST_USERS["intake_officer_headers"]


@pytest.fixture
def enforcement_attorney_headers():
    return TEST_USERS["enforcement_attorney_headers"]


@pytest.fixture
def unit_director_headers():
    return TEST_USERS["unit_director_headers"]
