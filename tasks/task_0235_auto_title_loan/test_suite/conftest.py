"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle and PYTHONPATH; this file only wires up
fixtures. The server is killed and relaunched before every individual test, so
each test starts against an empty database.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def compliance_admin_headers():
    return TEST_USERS["compliance_admin_headers"]


@pytest.fixture
def appraiser_headers():
    return TEST_USERS["appraiser_headers"]


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def loan_servicer_headers():
    return TEST_USERS["loan_servicer_headers"]


@pytest.fixture
def recovery_manager_headers():
    return TEST_USERS["recovery_manager_headers"]


@pytest.fixture
def title_clerk_headers():
    return TEST_USERS["title_clerk_headers"]
