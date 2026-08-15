"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def plant_manager_headers():
    return TEST_USERS["plant_manager_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def operator_headers():
    """Shared Operator-role header — only for tests that do not exercise
    ownership. Ownership-gated calls must use make_operator_headers(op_id)."""
    return TEST_USERS["operator_headers"]
