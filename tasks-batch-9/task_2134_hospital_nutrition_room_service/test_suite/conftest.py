"""Pytest fixtures exposing the nutrition test_helpers infrastructure."""
import pytest
from test_helpers import ANONYMOUS_HEADERS, TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def physician_headers():
    return TEST_USERS["physician_headers"]


@pytest.fixture
def physician_2_headers():
    return TEST_USERS["physician_2_headers"]


@pytest.fixture
def dietitian_headers():
    return TEST_USERS["dietitian_headers"]


@pytest.fixture
def dietitian_2_headers():
    return TEST_USERS["dietitian_2_headers"]


@pytest.fixture
def diet_clerk_headers():
    return TEST_USERS["diet_clerk_headers"]


@pytest.fixture
def tray_aide_headers():
    return TEST_USERS["tray_aide_headers"]


@pytest.fixture
def tray_aide_2_headers():
    return TEST_USERS["tray_aide_2_headers"]


@pytest.fixture
def nutrition_manager_headers():
    return TEST_USERS["nutrition_manager_headers"]


@pytest.fixture
def anonymous_headers():
    return ANONYMOUS_HEADERS
