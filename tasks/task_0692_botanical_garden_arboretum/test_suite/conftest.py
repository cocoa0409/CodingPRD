"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def staff_headers():
    return TEST_USERS["staff_headers"]


@pytest.fixture
def rental_coordinator_headers():
    return TEST_USERS["rental_coordinator_headers"]


@pytest.fixture
def development_officer_headers():
    return TEST_USERS["development_officer_headers"]


@pytest.fixture
def visitor_headers():
    return TEST_USERS["visitor_headers"]
