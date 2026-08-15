"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def desk_admin_headers():
    return TEST_USERS["desk_admin_headers"]


@pytest.fixture
def editor_headers():
    return TEST_USERS["editor_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def finance_2_headers():
    return TEST_USERS["finance_2_headers"]


@pytest.fixture
def verification_editor_headers():
    return TEST_USERS["verification_editor_headers"]


@pytest.fixture
def contributor_headers():
    return TEST_USERS["contributor_headers"]
