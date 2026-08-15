"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; tests assume the API
is reachable at API_BASE_URL.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def buyer_1_headers():
    return TEST_USERS["buyer_1_headers"]


@pytest.fixture
def seller_1_headers():
    return TEST_USERS["seller_1_headers"]


@pytest.fixture
def lender_1_headers():
    return TEST_USERS["lender_1_headers"]


@pytest.fixture
def insurer_1_headers():
    return TEST_USERS["insurer_1_headers"]


@pytest.fixture
def contr_1_headers():
    return TEST_USERS["contr_1_headers"]


@pytest.fixture
def contr_2_headers():
    return TEST_USERS["contr_2_headers"]


@pytest.fixture
def insp_1_headers():
    return TEST_USERS["insp_1_headers"]


@pytest.fixture
def insp_2_headers():
    return TEST_USERS["insp_2_headers"]
