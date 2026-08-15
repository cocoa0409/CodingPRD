"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def reporter_headers():
    return TEST_USERS["reporter_headers"]


@pytest.fixture
def acm_headers():
    return TEST_USERS["acm_headers"]


@pytest.fixture
def intake_headers():
    return TEST_USERS["intake_headers"]


@pytest.fixture
def investigator_headers():
    return TEST_USERS["investigator_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]
