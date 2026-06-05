"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable and injects API_BASE_URL.
The server is restarted before every test, so every test starts against an empty DB.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def election_admin_headers():
    return TEST_USERS["election_admin_headers"]


@pytest.fixture
def election_official_headers():
    return TEST_USERS["election_official_headers"]


@pytest.fixture
def election_official2_headers():
    return TEST_USERS["election_official2_headers"]


@pytest.fixture
def poll_worker_headers():
    return TEST_USERS["poll_worker_headers"]


@pytest.fixture
def canvasser_tally_headers():
    return TEST_USERS["canvasser_tally_headers"]


@pytest.fixture
def canvasser_recount_headers():
    return TEST_USERS["canvasser_recount_headers"]


@pytest.fixture
def voter_headers():
    return TEST_USERS["voter_headers"]
