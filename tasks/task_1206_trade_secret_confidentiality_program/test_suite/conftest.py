"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def ip_counsel_headers():
    return TEST_USERS["ip_counsel_headers"]


@pytest.fixture
def ip_counsel_2_headers():
    return TEST_USERS["ip_counsel_2_headers"]


@pytest.fixture
def senior_counsel_headers():
    return TEST_USERS["senior_counsel_headers"]


@pytest.fixture
def hr_partner_headers():
    return TEST_USERS["hr_partner_headers"]


@pytest.fixture
def security_officer_headers():
    return TEST_USERS["security_officer_headers"]


@pytest.fixture
def employee_headers():
    return TEST_USERS["employee_headers"]


@pytest.fixture
def counterparty_rep_headers():
    return TEST_USERS["counterparty_rep_headers"]
