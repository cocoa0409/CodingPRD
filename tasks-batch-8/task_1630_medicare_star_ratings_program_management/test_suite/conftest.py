"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def stars_admin_headers():
    return TEST_USERS["stars_admin_headers"]


@pytest.fixture
def stars_analyst_headers():
    return TEST_USERS["stars_analyst_headers"]


@pytest.fixture
def quality_ops_headers():
    return TEST_USERS["quality_ops_headers"]


@pytest.fixture
def survey_coordinator_headers():
    return TEST_USERS["survey_coordinator_headers"]


@pytest.fixture
def incentive_manager_headers():
    return TEST_USERS["incentive_manager_headers"]


@pytest.fixture
def complaints_auditor_headers():
    return TEST_USERS["complaints_auditor_headers"]
