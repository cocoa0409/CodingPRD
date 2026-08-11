"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def aqo_headers():
    return TEST_USERS["aqo_headers"]


@pytest.fixture
def commander_headers():
    return TEST_USERS["commander_headers"]


@pytest.fixture
def landowner_headers():
    return TEST_USERS["landowner_headers"]


@pytest.fixture
def burn_boss_headers():
    return TEST_USERS["burn_boss_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def contractor_headers():
    return TEST_USERS["contractor_headers"]
