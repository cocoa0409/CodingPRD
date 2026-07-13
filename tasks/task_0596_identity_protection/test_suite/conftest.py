"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin_alt_headers():
    return TEST_USERS["admin_alt_headers"]


@pytest.fixture
def adjuster_headers():
    return TEST_USERS["adjuster_headers"]


@pytest.fixture
def adjuster_alt_headers():
    return TEST_USERS["adjuster_alt_headers"]


@pytest.fixture
def subscriber_headers():
    """Fallback Subscriber headers — never use for ownership-gated calls."""
    return TEST_USERS["subscriber_headers"]


@pytest.fixture
def specialist_headers():
    """Fallback RestorationSpecialist headers — never use for ownership-gated calls."""
    return TEST_USERS["specialist_headers"]