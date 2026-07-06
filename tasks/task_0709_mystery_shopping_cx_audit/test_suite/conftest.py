"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, and injects
API_BASE_URL into the environment before launching pytest. The server is
restarted fresh before every individual test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def qa_validator_headers():
    return TEST_USERS["qa_validator_headers"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def client_manager_headers():
    return TEST_USERS["client_manager_headers"]


@pytest.fixture
def shopper_headers():
    return TEST_USERS["shopper_headers"]
