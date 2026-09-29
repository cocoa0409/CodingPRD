"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def ops_headers():
    """Network operations, acting under an opaque operator identifier."""
    return TEST_USERS["ops"]


@pytest.fixture
def ops_second_headers():
    """A second, distinct network operations identity."""
    return TEST_USERS["ops_second"]


@pytest.fixture
def ops_third_headers():
    """A third, distinct network operations identity."""
    return TEST_USERS["ops_third"]


@pytest.fixture
def ops_reviewer_headers():
    """The reviewing operator used wherever a case is taken up and adjudicated."""
    return TEST_USERS["ops_reviewer"]
