"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def oncologist_headers():
    return TEST_USERS["oncologist_headers"]


@pytest.fixture
def oncologist_b_headers():
    return TEST_USERS["oncologist_b_headers"]


@pytest.fixture
def dosimetrist_headers():
    return TEST_USERS["dosimetrist_headers"]


@pytest.fixture
def physicist_headers():
    return TEST_USERS["physicist_headers"]


@pytest.fixture
def physicist_b_headers():
    return TEST_USERS["physicist_b_headers"]


@pytest.fixture
def therapist_headers():
    return TEST_USERS["therapist_headers"]


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["scheduler_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]
