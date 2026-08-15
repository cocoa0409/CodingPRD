"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def coordinator_headers():
    return TEST_USERS["coordinator_headers"]


@pytest.fixture
def teacher_headers():
    return TEST_USERS["teacher_headers"]


@pytest.fixture
def principal_headers():
    return TEST_USERS["principal_headers"]


@pytest.fixture
def parent_headers():
    return TEST_USERS["parent_headers"]
