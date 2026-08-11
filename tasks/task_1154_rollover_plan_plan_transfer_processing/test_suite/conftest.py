"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def participant_headers():
    return TEST_USERS["participant_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def processor_headers():
    return TEST_USERS["processor_headers"]


@pytest.fixture
def tax_officer_headers():
    return TEST_USERS["tax_officer_headers"]


@pytest.fixture
def operations_headers():
    return TEST_USERS["operations_headers"]
