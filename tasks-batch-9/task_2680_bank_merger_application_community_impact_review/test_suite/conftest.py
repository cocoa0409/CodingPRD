"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def filer_headers():
    """A Filer whose X-User-ID matches no institution; use make_filer_headers for owners."""
    return TEST_USERS["filer_headers"]


@pytest.fixture
def commenter_headers():
    return TEST_USERS["commenter_headers"]


@pytest.fixture
def second_commenter_headers():
    return TEST_USERS["second_commenter_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def official_headers():
    return TEST_USERS["official_headers"]


@pytest.fixture
def second_official_headers():
    return TEST_USERS["second_official_headers"]


@pytest.fixture
def monitor_headers():
    return TEST_USERS["monitor_headers"]
