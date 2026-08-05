"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, and manages server
lifecycle (a fresh server + empty DB before every individual test).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def medicaid_coordinator_headers():
    return TEST_USERS["medicaid_coordinator_headers"]


@pytest.fixture
def billing_coordinator_headers():
    return TEST_USERS["billing_coordinator_headers"]


@pytest.fixture
def state_reviewer_headers():
    return TEST_USERS["state_reviewer_headers"]


@pytest.fixture
def service_provider_headers():
    return TEST_USERS["service_provider_headers"]
