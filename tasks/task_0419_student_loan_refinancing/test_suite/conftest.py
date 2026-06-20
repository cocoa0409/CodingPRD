"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def borrower_headers():
    return TEST_USERS["borrower_headers"]


@pytest.fixture
def cosigner_headers():
    return TEST_USERS["cosigner_headers"]


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def disbursement_officer_headers():
    return TEST_USERS["disbursement_officer_headers"]


@pytest.fixture
def servicing_agent_headers():
    return TEST_USERS["servicing_agent_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
