"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by the runner; tests assume the API is reachable
at API_BASE_URL and starts from a fresh database for every test.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client (server lifecycle managed externally)."""
    return api_client


@pytest.fixture
def servicing_admin_headers():
    return TEST_USERS["servicing_admin_headers"]


@pytest.fixture
def specialist_headers():
    return TEST_USERS["specialist_headers"]


@pytest.fixture
def specialist_2_headers():
    return TEST_USERS["specialist_2_headers"]


@pytest.fixture
def workout_manager_headers():
    return TEST_USERS["workout_manager_headers"]


@pytest.fixture
def title_officer_headers():
    return TEST_USERS["title_officer_headers"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def inspector_2_headers():
    return TEST_USERS["inspector_2_headers"]


@pytest.fixture
def disbursement_officer_1_headers():
    return TEST_USERS["disbursement_officer_1_headers"]


@pytest.fixture
def disbursement_officer_2_headers():
    return TEST_USERS["disbursement_officer_2_headers"]


@pytest.fixture
def legal_counsel_headers():
    return TEST_USERS["legal_counsel_headers"]


@pytest.fixture
def borrower_headers():
    return TEST_USERS["borrower_headers"]
