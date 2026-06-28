"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_program_admin_headers,
    make_medicaid_agency_headers,
    make_beneficiary_headers,
    make_representative_headers,
    make_invalid_role_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["program_admin_headers"]


@pytest.fixture
def medicaid_headers():
    return TEST_USERS["medicaid_agency_headers"]


@pytest.fixture
def beneficiary_headers():
    return TEST_USERS["beneficiary_headers"]


@pytest.fixture
def representative_headers():
    return TEST_USERS["representative_headers"]
