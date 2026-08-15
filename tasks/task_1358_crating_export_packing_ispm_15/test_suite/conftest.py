"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def sales_rep_headers():
    return TEST_USERS["sales_rep_headers"]


@pytest.fixture
def crating_designer_headers():
    return TEST_USERS["crating_designer_headers"]


@pytest.fixture
def shop_foreman_headers():
    return TEST_USERS["shop_foreman_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def logistics_coordinator_headers():
    return TEST_USERS["logistics_coordinator_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
