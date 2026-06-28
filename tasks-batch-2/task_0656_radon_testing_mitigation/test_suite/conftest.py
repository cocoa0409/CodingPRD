"""Pytest fixtures exposing test_helpers infrastructure.

The runner handles PYTHONPATH so `test_helpers` is importable, and it manages
the server lifecycle (restart before every test). conftest only wires fixtures.
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
def mitigation_designer_headers():
    return TEST_USERS["mitigation_designer_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def crew_lead_headers():
    return TEST_USERS["crew_lead_headers"]


@pytest.fixture
def client_contact_headers():
    return TEST_USERS["client_contact_headers"]
