"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def charge_nurse_headers():
    return TEST_USERS["charge_nurse_headers"]


@pytest.fixture
def bedside_nurse_headers():
    return TEST_USERS["bedside_nurse_headers"]


@pytest.fixture
def obstetrician_headers():
    return TEST_USERS["obstetrician_headers"]


@pytest.fixture
def anesthesia_lead_headers():
    return TEST_USERS["anesthesia_lead_headers"]


@pytest.fixture
def safety_officer_headers():
    return TEST_USERS["safety_officer_headers"]


@pytest.fixture
def access_coordinator_headers():
    return TEST_USERS["access_coordinator_headers"]
