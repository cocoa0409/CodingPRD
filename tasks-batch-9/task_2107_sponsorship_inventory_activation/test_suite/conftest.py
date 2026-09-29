"""Pytest fixtures exposing the sponsorship test infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture
def property_admin_headers():
    return TEST_USERS["property_admin_headers"]


@pytest.fixture
def seller_headers():
    return TEST_USERS["seller_headers"]


@pytest.fixture
def approver_headers():
    return TEST_USERS["approver_headers"]


@pytest.fixture
def activation_headers():
    return TEST_USERS["activation_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def sponsor_contact_headers():
    return TEST_USERS["sponsor_contact_headers"]
