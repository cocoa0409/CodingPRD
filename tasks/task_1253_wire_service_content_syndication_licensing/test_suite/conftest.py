"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; the server is restarted
before every test, so each test starts against an empty database.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def salesops_headers():
    return TEST_USERS["salesops_headers"]


@pytest.fixture
def editor_headers():
    return TEST_USERS["editor_headers"]


@pytest.fixture
def legal_headers():
    return TEST_USERS["legal_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_headers"]
