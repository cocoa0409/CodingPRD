"""Pytest fixtures exposing test_helpers infrastructure."""

import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def artistic_admin_headers():
    return TEST_USERS["artistic_admin_headers"]


@pytest.fixture
def orchestra_manager_headers():
    return TEST_USERS["orchestra_manager_headers"]


@pytest.fixture
def box_office_headers():
    return TEST_USERS["box_office_headers"]


@pytest.fixture
def advertising_sales_headers():
    return TEST_USERS["advertising_sales_headers"]


@pytest.fixture
def patron_headers():
    return TEST_USERS["patron_headers"]


@pytest.fixture
def musician_headers():
    return TEST_USERS["musician_headers"]


@pytest.fixture
def guest_artist_headers():
    return TEST_USERS["guest_artist_headers"]
