"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def organizer_headers():
    return TEST_USERS["organizer_headers"]


@pytest.fixture
def organizer2_headers():
    return TEST_USERS["organizer2_headers"]


@pytest.fixture
def cashier_headers():
    return TEST_USERS["cashier_headers"]


@pytest.fixture
def linestaff_headers():
    return TEST_USERS["linestaff_headers"]


@pytest.fixture
def school_coordinator_headers():
    return TEST_USERS["school_coordinator_headers"]


@pytest.fixture
def publisher_rep_headers():
    return TEST_USERS["publisher_rep_headers"]


@pytest.fixture
def author_rep_headers():
    return TEST_USERS["author_rep_headers"]
