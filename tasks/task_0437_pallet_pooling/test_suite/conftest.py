"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_pool_admin_headers,
    make_pool_operator_headers,
    make_participant_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def pool_admin_headers():
    return TEST_USERS["pool_admin_headers"]


@pytest.fixture
def pool_operator_headers():
    return TEST_USERS["pool_operator_headers"]


@pytest.fixture
def participant_headers():
    return TEST_USERS["participant_headers"]
