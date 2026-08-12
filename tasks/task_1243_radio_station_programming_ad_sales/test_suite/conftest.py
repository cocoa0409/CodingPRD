"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_billing_admin_headers,
    make_headers,
    make_program_director_headers,
    make_sales_manager_headers,
    make_sales_rep_headers,
    make_traffic_director_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def program_director_headers():
    return TEST_USERS["program_director_headers"]


@pytest.fixture
def traffic_director_headers():
    return TEST_USERS["traffic_director_headers"]


@pytest.fixture
def sales_rep_headers():
    return TEST_USERS["sales_rep_headers"]


@pytest.fixture
def sales_manager_headers():
    return TEST_USERS["sales_manager_headers"]


@pytest.fixture
def billing_admin_headers():
    return TEST_USERS["billing_admin_headers"]


@pytest.fixture
def make_role_headers():
    """Generic (role, user_id) -> headers builder."""
    return make_headers


@pytest.fixture
def header_builders():
    return {
        "ProgramDirector": make_program_director_headers,
        "TrafficDirector": make_traffic_director_headers,
        "SalesRep": make_sales_rep_headers,
        "SalesManager": make_sales_manager_headers,
        "BillingAdmin": make_billing_admin_headers,
    }
