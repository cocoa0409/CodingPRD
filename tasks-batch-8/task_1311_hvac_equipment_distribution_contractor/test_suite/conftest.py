"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["distributor_admin_headers"]


@pytest.fixture
def contractor_user_headers():
    return TEST_USERS["contractor_user_headers"]


@pytest.fixture
def warranty_processor_headers():
    return TEST_USERS["warranty_processor_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def training_coordinator_headers():
    return TEST_USERS["training_coordinator_headers"]
