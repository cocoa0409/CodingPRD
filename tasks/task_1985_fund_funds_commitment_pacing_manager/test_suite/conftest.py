"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def cio_headers():
    return TEST_USERS["cio_headers"]


@pytest.fixture
def compliance_headers():
    return TEST_USERS["compliance_headers"]
