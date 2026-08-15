"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def participant_headers():
    return TEST_USERS["participant_headers"]


@pytest.fixture
def plan_sponsor_headers():
    return TEST_USERS["plan_sponsor_headers"]


@pytest.fixture
def provider_ops_headers():
    return TEST_USERS["provider_ops_headers"]


@pytest.fixture
def fiduciary_reviewer_headers():
    return TEST_USERS["fiduciary_reviewer_headers"]
