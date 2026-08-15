"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; the server is restarted
(via start.sh) before every test, so each test starts against an empty
database and builds its own preconditions.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client bound to API_BASE_URL."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin2_headers():
    return TEST_USERS["admin2_headers"]


@pytest.fixture
def fieldtech_headers():
    return TEST_USERS["fieldtech_headers"]


@pytest.fixture
def fieldtech2_headers():
    return TEST_USERS["fieldtech2_headers"]


@pytest.fixture
def grower_headers():
    return TEST_USERS["grower_headers"]


@pytest.fixture
def feedmill_headers():
    return TEST_USERS["feedmill_headers"]


@pytest.fixture
def transport_headers():
    return TEST_USERS["transport_headers"]


@pytest.fixture
def envmgr_headers():
    return TEST_USERS["envmgr_headers"]
