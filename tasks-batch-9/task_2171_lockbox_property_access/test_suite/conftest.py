"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's responsibility."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def second_auditor_headers():
    return TEST_USERS["second_auditor_headers"]


@pytest.fixture
def device_headers():
    return TEST_USERS["device_headers"]


@pytest.fixture
def member_headers():
    return TEST_USERS["member_headers"]
