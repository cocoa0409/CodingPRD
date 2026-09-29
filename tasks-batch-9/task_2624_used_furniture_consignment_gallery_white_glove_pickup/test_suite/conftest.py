"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def gallery_manager_headers():
    return TEST_USERS["gallery_manager"]


@pytest.fixture
def gallery_manager_2_headers():
    return TEST_USERS["gallery_manager_2"]


@pytest.fixture
def intake_appraiser_headers():
    return TEST_USERS["intake_appraiser"]


@pytest.fixture
def intake_appraiser_2_headers():
    return TEST_USERS["intake_appraiser_2"]


@pytest.fixture
def floor_operator_headers():
    return TEST_USERS["floor_operator"]


@pytest.fixture
def floor_operator_2_headers():
    return TEST_USERS["floor_operator_2"]


@pytest.fixture
def logistics_coordinator_headers():
    return TEST_USERS["logistics_coordinator"]


@pytest.fixture
def logistics_coordinator_2_headers():
    return TEST_USERS["logistics_coordinator_2"]


@pytest.fixture
def system_operator_headers():
    return TEST_USERS["system_operator"]
