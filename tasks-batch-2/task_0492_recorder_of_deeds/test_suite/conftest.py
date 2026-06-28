"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def submitter_headers():
    return TEST_USERS["submitter_headers"]


@pytest.fixture
def examiner_headers():
    return TEST_USERS["examiner_headers"]


@pytest.fixture
def recorder_headers():
    return TEST_USERS["recorder_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]
