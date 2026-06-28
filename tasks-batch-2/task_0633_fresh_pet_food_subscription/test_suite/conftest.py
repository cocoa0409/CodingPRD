"""Pytest fixtures exposing test_helpers infrastructure.

The runner handles PYTHONPATH (so ``test_helpers`` is importable) and the server lifecycle
(restarting it before every test). These fixtures only wire the helpers into pytest.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def pet_parent_headers():
    """Fallback PetParent headers — use only for non-ownership paths (401/400/404/RBAC)."""
    return TEST_USERS["pet_parent_headers"]


@pytest.fixture
def nutrition_vet_headers():
    return TEST_USERS["nutrition_vet_headers"]


@pytest.fixture
def billing_admin_headers():
    return TEST_USERS["billing_admin_headers"]


@pytest.fixture
def fulfillment_ops_headers():
    return TEST_USERS["fulfillment_ops_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]
