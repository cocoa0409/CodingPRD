"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop/health) is managed by prd-bench-local-runner; the
runner kills and relaunches the API server before every test, so each test
starts against an empty database.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def advisor_headers():
    return TEST_USERS["advisor_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_headers"]
