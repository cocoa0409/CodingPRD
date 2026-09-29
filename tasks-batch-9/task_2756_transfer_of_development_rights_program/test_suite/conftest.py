"""Pytest fixtures exposing the program's test infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin_alt_headers():
    return TEST_USERS["admin_alt_headers"]


@pytest.fixture
def reviewer_headers():
    return TEST_USERS["reviewer_headers"]


@pytest.fixture
def reviewer_alt_headers():
    return TEST_USERS["reviewer_alt_headers"]


@pytest.fixture
def design_board_headers():
    return TEST_USERS["design_board_headers"]


@pytest.fixture
def monitor_headers():
    return TEST_USERS["monitor_headers"]


@pytest.fixture
def monitor_alt_headers():
    return TEST_USERS["monitor_alt_headers"]


@pytest.fixture
def landowner_headers():
    """Shared Landowner headers: use only where no ownership comparison applies."""
    return TEST_USERS["landowner_headers"]


@pytest.fixture
def developer_headers():
    """Shared Developer headers: use only where no ownership comparison applies."""
    return TEST_USERS["developer_headers"]
