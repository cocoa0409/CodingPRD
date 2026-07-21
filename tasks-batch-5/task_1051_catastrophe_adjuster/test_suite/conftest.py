"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def desk_examiner_headers():
    return TEST_USERS["desk_examiner_headers"]


@pytest.fixture
def licensing_admin_headers():
    return TEST_USERS["licensing_admin_headers"]


@pytest.fixture
def billing_manager_headers():
    return TEST_USERS["billing_manager_headers"]


@pytest.fixture
def field_adjuster_headers():
    return TEST_USERS["field_adjuster_headers"]


@pytest.fixture
def qa_reviewer_headers():
    return TEST_USERS["qa_reviewer_headers"]
