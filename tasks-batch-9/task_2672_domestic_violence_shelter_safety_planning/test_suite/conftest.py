"""Pytest fixtures exposing the test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def hotline_advocate_headers():
    return TEST_USERS["hotline_advocate_headers"]


@pytest.fixture
def shelter_manager_headers():
    return TEST_USERS["shelter_manager_headers"]


@pytest.fixture
def legal_advocate_headers():
    return TEST_USERS["legal_advocate_headers"]


@pytest.fixture
def housing_specialist_headers():
    return TEST_USERS["housing_specialist_headers"]


@pytest.fixture
def privacy_officer_headers():
    return TEST_USERS["privacy_officer_headers"]


@pytest.fixture
def agency_admin_headers():
    return TEST_USERS["agency_admin_headers"]
