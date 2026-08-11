"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop, API_BASE_URL injection, PYTHONPATH) is managed
by prd-bench-local-runner; these fixtures only bridge the helpers into tests.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. The server is already running."""
    return api_client


@pytest.fixture
def student_headers():
    return TEST_USERS["student_headers"]


@pytest.fixture
def front_desk_headers():
    return TEST_USERS["front_desk_headers"]


@pytest.fixture
def nurse_headers():
    return TEST_USERS["nurse_headers"]


@pytest.fixture
def clinician_headers():
    return TEST_USERS["clinician_headers"]


@pytest.fixture
def pharmacist_headers():
    return TEST_USERS["pharmacist_headers"]


@pytest.fixture
def billing_officer_headers():
    return TEST_USERS["billing_officer_headers"]


@pytest.fixture
def health_admin_headers():
    return TEST_USERS["health_admin_headers"]
