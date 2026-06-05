"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH (so `test_helpers` is importable) and the server
lifecycle (restarted before every test). These fixtures are thin accessors.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def gift_admin_headers():
    return TEST_USERS["gift_admin_headers"]


@pytest.fixture
def campaign_manager_headers():
    return TEST_USERS["campaign_manager_headers"]


@pytest.fixture
def donor_relations_headers():
    return TEST_USERS["donor_relations_headers"]
