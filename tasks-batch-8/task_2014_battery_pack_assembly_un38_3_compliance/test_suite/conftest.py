"""Pytest fixtures exposing test_helpers infrastructure.

The runner handles PYTHONPATH so test_helpers is importable; the runner also
owns the server lifecycle and injects API_BASE_URL.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the test runner."""
    return api_client


@pytest.fixture
def assembly_lead_headers():
    return TEST_USERS["assembly_lead_headers"]


@pytest.fixture
def quality_engineer_headers():
    return TEST_USERS["quality_engineer_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def logistics_coordinator_headers():
    return TEST_USERS["logistics_coordinator_headers"]


@pytest.fixture
def carrier_agent_headers():
    return TEST_USERS["carrier_agent_headers"]


@pytest.fixture
def customer_service_headers():
    return TEST_USERS["customer_service_headers"]


@pytest.fixture
def any_headers():
    return TEST_USERS["any_headers"]
