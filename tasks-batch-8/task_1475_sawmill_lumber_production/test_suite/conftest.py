"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def scaler_headers():
    return TEST_USERS["scaler_headers"]


@pytest.fixture
def sawyer_headers():
    return TEST_USERS["sawyer_headers"]


@pytest.fixture
def kiln_operator_headers():
    return TEST_USERS["kiln_operator_headers"]


@pytest.fixture
def grader_headers():
    return TEST_USERS["grader_headers"]


@pytest.fixture
def sales_rep_headers():
    return TEST_USERS["sales_rep_headers"]


@pytest.fixture
def mill_manager_headers():
    return TEST_USERS["mill_manager_headers"]
