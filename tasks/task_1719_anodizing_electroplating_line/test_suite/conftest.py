"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def customer_headers():
    return TEST_USERS["customer_headers"]


@pytest.fixture
def line_operator_headers():
    return TEST_USERS["line_operator_headers"]


@pytest.fixture
def lab_chemist_headers():
    return TEST_USERS["lab_chemist_headers"]


@pytest.fixture
def qc_inspector_headers():
    return TEST_USERS["qc_inspector_headers"]


@pytest.fixture
def ehs_officer_headers():
    return TEST_USERS["ehs_officer_headers"]


@pytest.fixture
def shop_manager_headers():
    return TEST_USERS["shop_manager_headers"]
