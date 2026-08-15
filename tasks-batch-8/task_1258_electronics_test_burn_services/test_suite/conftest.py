"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def customer_rep_headers():
    """Shared CustomerRep fallback — only for tests that do NOT exercise
    ownership gating. Ownership-gated paths must build per-instance headers
    with make_customer_rep_headers(customer_id)."""
    return TEST_USERS["customer_rep_headers"]


@pytest.fixture
def test_engineer_headers():
    return TEST_USERS["test_engineer_headers"]


@pytest.fixture
def test_engineer_2_headers():
    return TEST_USERS["test_engineer_2_headers"]


@pytest.fixture
def operations_manager_headers():
    return TEST_USERS["operations_manager_headers"]


@pytest.fixture
def quality_engineer_headers():
    return TEST_USERS["quality_engineer_headers"]
