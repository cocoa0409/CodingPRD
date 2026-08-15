"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def chief_headers():
    return TEST_USERS["chief_headers"]


@pytest.fixture
def cred_officer_headers():
    return TEST_USERS["cred_officer_headers"]


@pytest.fixture
def physician_headers():
    """Shared Physician headers — only for calls that are not ownership-gated.
    For ownership-gated calls use make_physician_headers(physician["id"])."""
    return TEST_USERS["physician_headers"]
