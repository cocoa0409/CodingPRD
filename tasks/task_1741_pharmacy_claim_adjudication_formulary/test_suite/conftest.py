"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def pbm_admin_headers():
    return TEST_USERS["pbm_admin_headers"]


@pytest.fixture
def clinical_reviewer_headers():
    return TEST_USERS["clinical_reviewer_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def pharmacist_headers():
    """Fallback Pharmacist headers for non-ownership tests only (role is
    entity-backed by Pharmacy; ownership-gated calls need a real pharmacy id)."""
    return TEST_USERS["pharmacist_headers"]


@pytest.fixture
def member_headers():
    """Fallback Member headers for non-ownership tests only (role is
    entity-backed by Member; ownership-gated calls need a real member id)."""
    return TEST_USERS["member_headers"]
