"""Pytest fixtures exposing the shared test_helpers infrastructure."""

import pytest

from test_helpers import (
    EMPTY_USER_ID_HEADERS,
    NO_AUTH_HEADERS,
    TEST_USERS,
    UNKNOWN_ROLE_HEADERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture
def program_admin() -> dict:
    return TEST_USERS["program_admin"]


@pytest.fixture
def compliance_officer() -> dict:
    return TEST_USERS["compliance_officer"]


@pytest.fixture
def second_compliance_officer() -> dict:
    return TEST_USERS["second_compliance_officer"]


@pytest.fixture
def developer() -> dict:
    return TEST_USERS["developer"]


@pytest.fixture
def rival_developer() -> dict:
    return TEST_USERS["rival_developer"]


@pytest.fixture
def fund_auditor() -> dict:
    return TEST_USERS["fund_auditor"]


@pytest.fixture
def no_auth_headers() -> dict:
    return NO_AUTH_HEADERS


@pytest.fixture
def empty_user_id_headers() -> dict:
    return EMPTY_USER_ID_HEADERS


@pytest.fixture
def unknown_role_headers() -> dict:
    return UNKNOWN_ROLE_HEADERS
