"""Pytest fixtures exposing the SALT test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def tax_manager_headers():
    return TEST_USERS["tax_manager_headers"]


@pytest.fixture
def state_analyst_headers():
    return TEST_USERS["state_analyst_headers"]


@pytest.fixture
def controller_headers():
    return TEST_USERS["controller_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
