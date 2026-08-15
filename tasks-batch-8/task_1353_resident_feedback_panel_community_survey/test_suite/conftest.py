"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def panel_manager():
    return TEST_USERS["panel_manager"]


@pytest.fixture
def survey_designer():
    return TEST_USERS["survey_designer"]


@pytest.fixture
def data_analyst():
    return TEST_USERS["data_analyst"]


@pytest.fixture
def incentive_clerk():
    return TEST_USERS["incentive_clerk"]


@pytest.fixture
def privacy_officer():
    return TEST_USERS["privacy_officer"]


@pytest.fixture
def department_liaison():
    return TEST_USERS["department_liaison"]
