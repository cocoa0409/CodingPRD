"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def manager_headers():
    return TEST_USERS["terminal_manager_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["terminal_operator_headers"]


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["scheduler_headers"]


@pytest.fixture
def gauger_headers():
    return TEST_USERS["gauger_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["quality_inspector_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["billing_clerk_headers"]
