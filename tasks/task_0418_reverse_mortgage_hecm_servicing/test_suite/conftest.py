"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def servicer_ops_headers():
    return TEST_USERS["servicer_ops_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def hud_auditor_headers():
    return TEST_USERS["hud_auditor_headers"]


@pytest.fixture
def system_headers():
    return TEST_USERS["system_headers"]


@pytest.fixture
def borrower_headers():
    return TEST_USERS["borrower_headers"]
