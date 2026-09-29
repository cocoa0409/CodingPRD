"""Pytest fixtures exposing the Brand Inspection Board test helpers."""

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is the runner's concern."""
    return api_client


@pytest.fixture
def board_admin_headers():
    return TEST_USERS["board_admin_headers"]


@pytest.fixture
def brand_recorder_headers():
    return TEST_USERS["brand_recorder_headers"]


@pytest.fixture
def second_brand_recorder_headers():
    return TEST_USERS["second_brand_recorder_headers"]


@pytest.fixture
def fee_administrator_headers():
    return TEST_USERS["fee_administrator_headers"]


@pytest.fixture
def theft_investigator_headers():
    return TEST_USERS["theft_investigator_headers"]


@pytest.fixture
def livestock_owner_headers():
    return TEST_USERS["livestock_owner_headers"]


@pytest.fixture
def field_inspector_headers():
    return TEST_USERS["field_inspector_headers"]
