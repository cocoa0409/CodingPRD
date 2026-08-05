"""Pytest fixtures exposing the shared test infrastructure."""

import pytest

from test_helpers import ADMIN, BILLING, CARE_COORDINATOR, REGISTRAR, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def admin_headers():
    return ADMIN


@pytest.fixture
def registrar_headers():
    return REGISTRAR


@pytest.fixture
def care_coordinator_headers():
    return CARE_COORDINATOR


@pytest.fixture
def billing_headers():
    return BILLING
