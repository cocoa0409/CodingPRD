"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_admin_headers,
    make_analyst_headers,
    make_examiner_headers,
    make_manager_headers,
    make_officer_headers,
    make_teller_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return make_admin_headers()


@pytest.fixture
def manager_headers():
    return make_manager_headers()


@pytest.fixture
def teller_headers():
    return make_teller_headers()


@pytest.fixture
def analyst_headers():
    return make_analyst_headers()


@pytest.fixture
def officer_headers():
    return make_officer_headers()


@pytest.fixture
def examiner_headers():
    return make_examiner_headers()
