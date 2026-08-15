"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; the suite assumes the
API is already reachable at API_BASE_URL and that the server is relaunched
(with an empty database) before every test.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def fap_admin_headers():
    return TEST_USERS["fap_admin_headers"]


@pytest.fixture
def audit_analyst_headers():
    return TEST_USERS["audit_analyst_headers"]


@pytest.fixture
def finance_controller_headers():
    return TEST_USERS["finance_controller_headers"]


@pytest.fixture
def treasury_approver_headers():
    return TEST_USERS["treasury_approver_headers"]
