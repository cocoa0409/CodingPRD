"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def verifier_admin_headers():
    return TEST_USERS["verifier_admin_headers"]


@pytest.fixture
def lab_analyst_1_headers():
    return TEST_USERS["lab_analyst_1_headers"]


@pytest.fixture
def lab_analyst_2_headers():
    return TEST_USERS["lab_analyst_2_headers"]


@pytest.fixture
def auditor_1_headers():
    return TEST_USERS["auditor_1_headers"]


@pytest.fixture
def officer_1_headers():
    return TEST_USERS["officer_1_headers"]


@pytest.fixture
def officer_2_headers():
    return TEST_USERS["officer_2_headers"]


@pytest.fixture
def brand_rep_headers():
    return TEST_USERS["brand_rep_headers"]
