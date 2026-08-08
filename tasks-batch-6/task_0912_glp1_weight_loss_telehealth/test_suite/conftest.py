"""Pytest fixtures exposing the GLP-1 telehealth test helpers."""

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def platform_admin():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def billing_admin():
    return TEST_USERS["billing_admin_headers"]


@pytest.fixture
def anonymous_patient_headers():
    """Shared Patient headers — safe only where ownership is not exercised."""
    return TEST_USERS["patient_headers"]


@pytest.fixture
def anonymous_provider_headers():
    """Shared Provider headers — safe only where ownership is not exercised."""
    return TEST_USERS["provider_headers"]


@pytest.fixture
def anonymous_coach_headers():
    """Shared Coach headers — safe only where ownership is not exercised."""
    return TEST_USERS["coach_headers"]


@pytest.fixture
def anonymous_pharmacy_operator_headers():
    """Shared PharmacyOperator headers — safe only where ownership is not exercised."""
    return TEST_USERS["pharmacy_operator_headers"]
