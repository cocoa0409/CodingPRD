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
def scheduler_headers():
    return TEST_USERS["scheduler_headers"]


@pytest.fixture
def chemist_headers():
    return TEST_USERS["chemist_headers"]


@pytest.fixture
def qc_headers():
    return TEST_USERS["qc_headers"]


@pytest.fixture
def qm_headers():
    return TEST_USERS["qm_headers"]
