"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def clinical_director_headers():
    return TEST_USERS["clinical_director_headers"]


@pytest.fixture
def therapist_headers():
    return TEST_USERS["therapist_headers"]


@pytest.fixture
def biller_headers():
    return TEST_USERS["biller_headers"]


@pytest.fixture
def front_desk_headers():
    return TEST_USERS["front_desk_headers"]
