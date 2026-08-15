"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the test runner."""
    return api_client


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin_headers"]


@pytest.fixture
def reporter_headers():
    return TEST_USERS["reporter_headers"]


@pytest.fixture
def case_manager_headers():
    return TEST_USERS["case_manager_headers"]


@pytest.fixture
def bit_chair_headers():
    return TEST_USERS["bit_chair_headers"]


@pytest.fixture
def counseling_evaluator_headers():
    return TEST_USERS["counseling_evaluator_headers"]


@pytest.fixture
def dean_headers():
    return TEST_USERS["dean_headers"]


@pytest.fixture
def privacy_officer_headers():
    return TEST_USERS["privacy_officer_headers"]
