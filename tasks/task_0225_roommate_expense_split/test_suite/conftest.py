"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def roommate_headers():
    return TEST_USERS["roommate_headers"]


@pytest.fixture
def mediator_headers():
    return TEST_USERS["mediator_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]
