"""Pytest fixtures exposing the shared test infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def intake_headers():
    return TEST_USERS["intake_headers"]


@pytest.fixture
def physician_headers():
    return TEST_USERS["physician_headers"]


@pytest.fixture
def physician_2_headers():
    return TEST_USERS["physician_2_headers"]


@pytest.fixture
def nurse_headers():
    return TEST_USERS["nurse_headers"]


@pytest.fixture
def social_worker_headers():
    return TEST_USERS["social_worker_headers"]


@pytest.fixture
def chaplain_headers():
    return TEST_USERS["chaplain_headers"]


@pytest.fixture
def hospice_director_headers():
    return TEST_USERS["hospice_director_headers"]


@pytest.fixture
def oncall_headers():
    return TEST_USERS["oncall_headers"]


@pytest.fixture
def billing_headers():
    return TEST_USERS["billing_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]
