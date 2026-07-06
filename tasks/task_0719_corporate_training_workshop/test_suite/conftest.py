"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def program_designer_headers():
    return TEST_USERS["program_designer_headers"]


@pytest.fixture
def scheduling_coordinator_headers():
    return TEST_USERS["scheduling_coordinator_headers"]


@pytest.fixture
def learner_headers():
    return TEST_USERS["learner_headers"]


@pytest.fixture
def finance_manager_headers():
    return TEST_USERS["finance_manager_headers"]


@pytest.fixture
def facilitator_headers():
    return TEST_USERS["facilitator_headers"]
