"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def lab_admin_headers():
    return TEST_USERS["lab_admin_headers"]


@pytest.fixture
def histotech_headers():
    return TEST_USERS["histotech_headers"]


@pytest.fixture
def pathology_assistant_headers():
    return TEST_USERS["pathology_assistant_headers"]


@pytest.fixture
def pathologist_headers():
    return TEST_USERS["pathologist_headers"]
