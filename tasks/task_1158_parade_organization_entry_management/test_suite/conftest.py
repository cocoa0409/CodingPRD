"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def committee_admin_headers():
    return TEST_USERS["committee_admin_headers"]


@pytest.fixture
def agency_reviewer_headers():
    return TEST_USERS["agency_reviewer_headers"]


@pytest.fixture
def safety_inspector_headers():
    return TEST_USERS["safety_inspector_headers"]


@pytest.fixture
def entrant_headers():
    return TEST_USERS["entrant_headers"]


@pytest.fixture
def judge_headers():
    return TEST_USERS["judge_headers"]


@pytest.fixture
def marshal_headers():
    return TEST_USERS["marshal_headers"]
