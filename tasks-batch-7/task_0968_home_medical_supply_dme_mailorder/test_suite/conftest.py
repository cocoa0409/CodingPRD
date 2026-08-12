"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def patient_headers():
    """Fallback Patient headers — only for tests that do not exercise ownership."""
    return TEST_USERS["patient_headers"]


@pytest.fixture
def intake_coordinator_headers():
    return TEST_USERS["intake_coordinator_headers"]


@pytest.fixture
def prior_auth_specialist_headers():
    return TEST_USERS["prior_auth_specialist_headers"]


@pytest.fixture
def fulfillment_agent_headers():
    return TEST_USERS["fulfillment_agent_headers"]


@pytest.fixture
def billing_specialist_headers():
    return TEST_USERS["billing_specialist_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
