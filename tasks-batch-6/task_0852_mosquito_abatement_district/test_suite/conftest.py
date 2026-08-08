"""Pytest fixtures exposing the district test infrastructure."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle belongs to the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def lab_headers():
    return TEST_USERS["lab_headers"]


@pytest.fixture
def ecologist_headers():
    return TEST_USERS["ecologist_headers"]


@pytest.fixture
def manager_headers():
    return TEST_USERS["manager_headers"]


@pytest.fixture
def manager2_headers():
    return TEST_USERS["manager2_headers"]


@pytest.fixture
def resident_headers():
    return TEST_USERS["resident_headers"]


@pytest.fixture
def field_tech_headers():
    """Shared FieldTech constant — only for calls that touch no ownership check."""
    return TEST_USERS["field_tech_headers"]


@pytest.fixture
def site_operator_headers():
    """Shared SensitiveSiteOperator constant — no ownership-gated use."""
    return TEST_USERS["site_operator_headers"]
