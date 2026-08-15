"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import (
    NO_AUTH_HEADERS,
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def school_admin_headers():
    return TEST_USERS["school_admin_headers"]


@pytest.fixture
def front_office_headers():
    return TEST_USERS["front_office_headers"]


@pytest.fixture
def teacher_headers_fixture():
    # Fallback only: ownership-gated Teacher calls must use
    # make_teacher_headers(teacher["id"]) instead.
    return TEST_USERS["teacher_headers"]


@pytest.fixture
def family_guardian_headers():
    # Fallback only: ownership-gated FamilyGuardian calls must use
    # make_family_guardian_headers(family["id"]) instead.
    return TEST_USERS["family_guardian_headers"]


@pytest.fixture
def interpreter_headers_fixture():
    # Fallback only: ownership-gated Interpreter calls must use
    # make_interpreter_headers(interpreter["id"]) instead.
    return TEST_USERS["interpreter_headers"]


@pytest.fixture
def no_auth_headers():
    return NO_AUTH_HEADERS
