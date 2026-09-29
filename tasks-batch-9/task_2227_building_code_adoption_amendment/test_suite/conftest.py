"""Shared pytest fixtures for the building code adoption and amendment suite."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The API client under test."""
    return api_client


@pytest.fixture
def council_admin_headers() -> dict:
    return TEST_USERS["council_admin_headers"]


@pytest.fixture
def technical_staff_headers() -> dict:
    return TEST_USERS["technical_staff_headers"]


@pytest.fixture
def petitioner_headers() -> dict:
    return TEST_USERS["petitioner_headers"]


@pytest.fixture
def committee_member_headers() -> dict:
    return TEST_USERS["committee_member_headers"]


@pytest.fixture
def council_chair_headers() -> dict:
    return TEST_USERS["council_chair_headers"]


@pytest.fixture
def jurisdiction_official_headers() -> dict:
    return TEST_USERS["jurisdiction_official_headers"]
