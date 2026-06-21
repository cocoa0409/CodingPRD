"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, and injects
API_BASE_URL. The server is started/restarted by the runner before each test.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def claims_adjudicator_headers():
    return TEST_USERS["claims_adjudicator_headers"]


@pytest.fixture
def system_operator_headers():
    return TEST_USERS["system_operator_headers"]


@pytest.fixture
def policyholder_headers():
    return TEST_USERS["policyholder_headers"]
