"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop/health) is owned by prd-bench-local-runner; these
fixtures only surface the shared API client and role headers.
"""
import pytest
from test_helpers import (
    api_client, ApiClient, TEST_USERS,
    make_applicant_headers, make_reviewer_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def police_headers():
    return TEST_USERS["police_headers"]


@pytest.fixture
def fire_headers():
    return TEST_USERS["fire_headers"]


@pytest.fixture
def ems_headers():
    return TEST_USERS["ems_headers"]


@pytest.fixture
def public_works_headers():
    return TEST_USERS["public_works_headers"]
