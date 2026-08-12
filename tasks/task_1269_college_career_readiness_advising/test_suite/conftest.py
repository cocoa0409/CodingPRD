"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def district_admin_headers() -> dict:
    return TEST_USERS["district_admin_headers"]


@pytest.fixture
def wbl_coordinator_headers() -> dict:
    return TEST_USERS["wbl_coordinator_headers"]


@pytest.fixture
def advisor_headers() -> dict:
    """Shared Advisor headers — only for tests that do not exercise ownership."""
    return TEST_USERS["advisor_headers"]


@pytest.fixture
def student_headers() -> dict:
    """Shared Student headers — only for tests that do not exercise ownership."""
    return TEST_USERS["student_headers"]


@pytest.fixture
def teacher_headers() -> dict:
    """Shared Teacher headers — only for tests that do not exercise ownership."""
    return TEST_USERS["teacher_headers"]
