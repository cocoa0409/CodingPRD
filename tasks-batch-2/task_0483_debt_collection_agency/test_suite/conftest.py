"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def creditor_headers():
    return TEST_USERS["creditor_headers"]


@pytest.fixture
def collector_headers():
    return TEST_USERS["collector_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def bureau_operator_headers():
    return TEST_USERS["bureau_operator_headers"]


@pytest.fixture
def system_headers():
    return TEST_USERS["system_headers"]
