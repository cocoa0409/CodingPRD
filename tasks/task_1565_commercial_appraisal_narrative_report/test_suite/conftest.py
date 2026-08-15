"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def engagement_manager_headers():
    return TEST_USERS["engagement_manager_headers"]


@pytest.fixture
def records_manager_headers():
    return TEST_USERS["records_manager_headers"]


@pytest.fixture
def legal_counsel_headers():
    return TEST_USERS["legal_counsel_headers"]


@pytest.fixture
def client_headers():
    return TEST_USERS["client_headers"]


@pytest.fixture
def staff_appraiser_headers():
    return TEST_USERS["staff_appraiser_headers"]


@pytest.fixture
def review_appraiser_headers():
    return TEST_USERS["review_appraiser_headers"]


@pytest.fixture
def mai_signer_headers():
    return TEST_USERS["mai_signer_headers"]
