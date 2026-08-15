"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def brand_rep_headers():
    return TEST_USERS["brand_rep_headers"]


@pytest.fixture
def production_planner_headers():
    return TEST_USERS["production_planner_headers"]


@pytest.fixture
def production_operator_headers():
    return TEST_USERS["production_operator_headers"]


@pytest.fixture
def qa_chemist_headers():
    return TEST_USERS["qa_chemist_headers"]


@pytest.fixture
def qa_manager_headers():
    return TEST_USERS["qa_manager_headers"]
