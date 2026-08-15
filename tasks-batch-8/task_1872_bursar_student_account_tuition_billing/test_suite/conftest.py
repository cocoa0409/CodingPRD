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
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def bursar_staff_headers():
    return TEST_USERS["bursar_staff_headers"]


@pytest.fixture
def bursar_manager_headers():
    return TEST_USERS["bursar_manager_headers"]
