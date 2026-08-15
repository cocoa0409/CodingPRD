"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def principal_headers():
    return TEST_USERS["principal_headers"]


@pytest.fixture
def responder_headers():
    return TEST_USERS["responder_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
