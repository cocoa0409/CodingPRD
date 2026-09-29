"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def retail_partner_headers():
    return TEST_USERS["retail_partner_headers"]


@pytest.fixture
def trial_support_agent_headers():
    return TEST_USERS["trial_support_agent_headers"]


@pytest.fixture
def logistics_coordinator_headers():
    return TEST_USERS["logistics_coordinator_headers"]


@pytest.fixture
def finance_controller_headers():
    return TEST_USERS["finance_controller_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
