"""Pytest fixtures exposing test_helpers infrastructure. Server lifecycle is
managed by prd-bench-local-runner; these tests assume the server is already
running and reachable at API_BASE_URL.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def program_admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def intake_coordinator_headers():
    return TEST_USERS["intake_coordinator_headers"]


@pytest.fixture
def medical_director_headers():
    return TEST_USERS["medical_director_headers"]


@pytest.fixture
def nurse_staff_headers():
    return TEST_USERS["nurse_staff_headers"]


@pytest.fixture
def billing_specialist_headers():
    return TEST_USERS["billing_specialist_headers"]


@pytest.fixture
def unknown_role_headers():
    return TEST_USERS["unknown_role_headers"]
