"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def lead_estimator_headers():
    return TEST_USERS["lead_estimator_headers"]


@pytest.fixture
def chief_estimator_headers():
    return TEST_USERS["chief_estimator_headers"]


@pytest.fixture
def prequal_reviewer_headers():
    return TEST_USERS["prequal_reviewer_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def subcontractor_headers():
    return TEST_USERS["subcontractor_headers"]
