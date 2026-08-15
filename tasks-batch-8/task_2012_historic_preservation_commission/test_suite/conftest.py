"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def staff_headers():
    return TEST_USERS["staff_headers"]


@pytest.fixture
def commissioner_headers():
    return TEST_USERS["commissioner_headers"]


@pytest.fixture
def council_headers():
    return TEST_USERS["council_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def applicant_headers():
    """Shared Applicant headers — only for calls that are not ownership-gated.
    For ownership-gated calls use make_applicant_headers(owner["id"])."""
    return TEST_USERS["applicant_headers"]
