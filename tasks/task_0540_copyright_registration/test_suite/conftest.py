"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, injects API_BASE_URL,
and restarts the server (via start.sh) before every test — so each test begins
against an empty database.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def rightsholder_headers():
    return TEST_USERS["rightsholder_headers"]


@pytest.fixture
def rightsholder2_headers():
    return TEST_USERS["rightsholder2_headers"]


@pytest.fixture
def examiner_headers():
    return TEST_USERS["examiner_headers"]


@pytest.fixture
def complainant_headers():
    return TEST_USERS["complainant_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def unknown_role_headers():
    return TEST_USERS["unknown_role_headers"]
