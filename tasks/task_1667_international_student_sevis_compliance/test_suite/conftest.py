"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def pdso_headers():
    return TEST_USERS["pdso_headers"]


@pytest.fixture
def dso_headers():
    return TEST_USERS["dso_headers"]


@pytest.fixture
def student_headers():
    return TEST_USERS["student_headers"]
