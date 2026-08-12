"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["quality_admin_headers"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["quality_analyst_headers"]


@pytest.fixture
def abstractor_headers():
    return TEST_USERS["abstractor_headers"]


@pytest.fixture
def overreader_headers():
    return TEST_USERS["overreader_headers"]


@pytest.fixture
def provider_relations_headers():
    return TEST_USERS["provider_relations_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def director_headers():
    return TEST_USERS["quality_director_headers"]
