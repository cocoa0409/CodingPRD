"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def salesrep_headers():
    return TEST_USERS["salesrep_headers"]


@pytest.fixture
def agronomist_headers():
    return TEST_USERS["agronomist_headers"]


@pytest.fixture
def adjuster_headers():
    return TEST_USERS["adjuster_headers"]


@pytest.fixture
def grower_headers():
    """Shared Grower headers — only for calls that are not ownership-gated.
    For ownership-gated calls use make_grower_headers(grower["id"])."""
    return TEST_USERS["grower_headers"]
