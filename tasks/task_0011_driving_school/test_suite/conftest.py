"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def examiner_headers():
    return TEST_USERS["examiner_headers"]


@pytest.fixture
def complaint_handler_headers():
    return TEST_USERS["complaint_handler_headers"]


@pytest.fixture
def shared_student_headers():
    """Shared-constant student headers — only safe for tests that don't exercise ownership."""
    return TEST_USERS["student_headers"]


@pytest.fixture
def shared_instructor_headers():
    """Shared-constant instructor headers — only safe for tests that don't exercise ownership."""
    return TEST_USERS["instructor_headers"]
