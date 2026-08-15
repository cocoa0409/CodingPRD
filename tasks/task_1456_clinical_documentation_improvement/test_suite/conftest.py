"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def cdi_manager_headers():
    return TEST_USERS["cdi_manager_headers"]


@pytest.fixture
def cdi_specialist_headers():
    return TEST_USERS["cdi_specialist_headers"]


@pytest.fixture
def him_coder_headers():
    return TEST_USERS["him_coder_headers"]


@pytest.fixture
def compliance_auditor_headers():
    return TEST_USERS["compliance_auditor_headers"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def provider_headers():
    return TEST_USERS["provider_headers"]
