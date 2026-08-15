"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def officer_b_headers():
    return TEST_USERS["officer_b_headers"]


@pytest.fixture
def vet_headers():
    return TEST_USERS["vet_headers"]


@pytest.fixture
def lab_headers():
    return TEST_USERS["lab_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
