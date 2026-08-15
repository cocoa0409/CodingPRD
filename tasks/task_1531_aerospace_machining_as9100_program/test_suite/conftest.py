"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def contracts_manager_headers():
    return TEST_USERS["contracts_manager"]


@pytest.fixture
def supply_chain_manager_headers():
    return TEST_USERS["supply_chain_manager"]


@pytest.fixture
def manufacturing_planner_headers():
    return TEST_USERS["manufacturing_planner"]


@pytest.fixture
def quality_inspector_headers():
    return TEST_USERS["quality_inspector"]


@pytest.fixture
def mrb_member_headers():
    return TEST_USERS["mrb_member"]


@pytest.fixture
def quality_manager_headers():
    return TEST_USERS["quality_manager"]


@pytest.fixture
def customer_quality_rep_headers():
    return TEST_USERS["customer_quality_rep"]


@pytest.fixture
def system_admin_headers():
    return TEST_USERS["system_admin"]
