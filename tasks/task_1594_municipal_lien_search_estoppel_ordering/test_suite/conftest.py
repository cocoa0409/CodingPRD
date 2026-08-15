"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def title_agent_headers():
    return TEST_USERS["title_agent_headers"]


@pytest.fixture
def title_agent_2_headers():
    return TEST_USERS["title_agent_2_headers"]


@pytest.fixture
def research_analyst_headers():
    return TEST_USERS["research_analyst_headers"]


@pytest.fixture
def qa_reviewer_headers():
    return TEST_USERS["qa_reviewer_headers"]


@pytest.fixture
def qa_reviewer_2_headers():
    return TEST_USERS["qa_reviewer_2_headers"]


@pytest.fixture
def provider_admin_headers():
    return TEST_USERS["provider_admin_headers"]
