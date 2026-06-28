"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def petitioner_headers():
    return TEST_USERS["petitioner_headers"]


@pytest.fixture
def examiner_headers():
    return TEST_USERS["examiner_headers"]


@pytest.fixture
def judge_headers():
    return TEST_USERS["judge_headers"]


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def fiduciary_headers():
    return TEST_USERS["fiduciary_headers"]
