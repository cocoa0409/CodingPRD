"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def clinic_admin_headers():
    return TEST_USERS["clinic_admin_headers"]


@pytest.fixture
def front_desk_headers():
    return TEST_USERS["front_desk_headers"]


@pytest.fixture
def inventory_manager_headers():
    return TEST_USERS["inventory_manager_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def physician_headers():
    """Fallback only: a Physician's X-User-ID must be a real Provider id
    wherever the identity is compared."""
    return TEST_USERS["physician_headers"]


@pytest.fixture
def nurse_injector_headers():
    """Fallback only: see physician_headers."""
    return TEST_USERS["nurse_injector_headers"]


@pytest.fixture
def patient_headers():
    """Fallback only: a Patient's X-User-ID must be a real Patient id
    wherever ownership is compared."""
    return TEST_USERS["patient_headers"]
