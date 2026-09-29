"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns the server lifecycle and restarts it before every test, so each
test observes an empty registry and builds its own preconditions.
"""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["platform_admin"]


@pytest.fixture
def diligence_headers():
    return TEST_USERS["diligence_lead"]


@pytest.fixture
def diligence_headers_2():
    return TEST_USERS["diligence_lead_2"]


@pytest.fixture
def counsel_headers():
    return TEST_USERS["trust_counsel"]


@pytest.fixture
def regulator_headers():
    return TEST_USERS["charities_regulator"]


@pytest.fixture
def integration_headers():
    return TEST_USERS["integration_manager"]
