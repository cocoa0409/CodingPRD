"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def row_agent_headers():
    return TEST_USERS["row_agent_headers"]


@pytest.fixture
def title_examiner_headers():
    return TEST_USERS["title_examiner_headers"]


@pytest.fixture
def vegetation_inspector_headers():
    return TEST_USERS["vegetation_inspector_headers"]


@pytest.fixture
def litigation_counsel_headers():
    return TEST_USERS["litigation_counsel_headers"]


@pytest.fixture
def department_director_headers():
    return TEST_USERS["department_director_headers"]
