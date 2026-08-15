"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def quality_manager_headers():
    return TEST_USERS["quality_manager_headers"]


@pytest.fixture
def batch_scheduler_headers():
    return TEST_USERS["batch_scheduler_headers"]


@pytest.fixture
def tank_operator_headers():
    return TEST_USERS["tank_operator_headers"]


@pytest.fixture
def qa_validator_headers():
    return TEST_USERS["qa_validator_headers"]


@pytest.fixture
def sds_author_headers():
    return TEST_USERS["sds_author_headers"]


@pytest.fixture
def shipping_clerk_headers():
    return TEST_USERS["shipping_clerk_headers"]
