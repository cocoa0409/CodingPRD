"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def aid_officer_headers():
    return TEST_USERS["aid_officer_headers"]


@pytest.fixture
def committee_headers():
    return TEST_USERS["committee_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def aid_admin_headers():
    return TEST_USERS["aid_admin_headers"]


@pytest.fixture
def student_headers():
    """Shared Student headers. Ownership-gated calls must instead use
    make_student_headers(student["id"])."""
    return TEST_USERS["student_headers"]
