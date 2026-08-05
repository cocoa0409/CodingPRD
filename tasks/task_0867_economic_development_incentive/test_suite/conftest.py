"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst_headers"]


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def public_headers():
    return TEST_USERS["public_headers"]
