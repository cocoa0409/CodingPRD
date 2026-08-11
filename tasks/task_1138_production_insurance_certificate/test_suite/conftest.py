"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def broker_headers():
    return TEST_USERS["broker_headers"]


@pytest.fixture
def production_manager_headers():
    return TEST_USERS["production_manager_headers"]


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def clearance_counsel_headers():
    return TEST_USERS["clearance_counsel_headers"]


@pytest.fixture
def surety_underwriter_headers():
    return TEST_USERS["surety_underwriter_headers"]


@pytest.fixture
def external_auditor_headers():
    return TEST_USERS["external_auditor_headers"]


@pytest.fixture
def platform_operator_headers():
    return TEST_USERS["platform_operator_headers"]
