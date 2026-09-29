"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def practice_admin_headers():
    return TEST_USERS["practice_admin_headers"]


@pytest.fixture
def scheduling_coordinator_headers():
    return TEST_USERS["scheduling_coordinator_headers"]


@pytest.fixture
def benefits_specialist_headers():
    return TEST_USERS["benefits_specialist_headers"]


@pytest.fixture
def inventory_manager_headers():
    return TEST_USERS["inventory_manager_headers"]


@pytest.fixture
def surgeon_headers():
    return TEST_USERS["surgeon_headers"]


@pytest.fixture
def anesthesia_coordinator_headers():
    return TEST_USERS["anesthesia_coordinator_headers"]


@pytest.fixture
def quality_reviewer_headers():
    return TEST_USERS["quality_reviewer_headers"]
