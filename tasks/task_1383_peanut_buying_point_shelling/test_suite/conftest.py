"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def inspector_2_headers():
    return TEST_USERS["inspector_2_headers"]


@pytest.fixture
def lab_tech_headers():
    return TEST_USERS["lab_tech_headers"]


@pytest.fixture
def lab_tech_2_headers():
    return TEST_USERS["lab_tech_2_headers"]


@pytest.fixture
def clerk_1_headers():
    return TEST_USERS["clerk_1_headers"]


@pytest.fixture
def clerk_2_headers():
    return TEST_USERS["clerk_2_headers"]


@pytest.fixture
def clerk_3_headers():
    return TEST_USERS["clerk_3_headers"]


@pytest.fixture
def sheller_rep_headers():
    return TEST_USERS["sheller_rep_headers"]
