"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; the server is
restarted before every test, so each test begins against an empty database.
"""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client (server lifecycle owned by the runner)."""
    return api_client


@pytest.fixture
def director_headers():
    return TEST_USERS["director"]


@pytest.fixture
def director2_headers():
    return TEST_USERS["director2"]


@pytest.fixture
def asset_manager_headers():
    return TEST_USERS["asset_manager"]


@pytest.fixture
def asset_manager2_headers():
    return TEST_USERS["asset_manager2"]


@pytest.fixture
def committee_headers():
    return TEST_USERS["committee"]


@pytest.fixture
def committee2_headers():
    return TEST_USERS["committee2"]


@pytest.fixture
def lender_headers():
    return TEST_USERS["lender"]


@pytest.fixture
def analyst_headers():
    return TEST_USERS["analyst"]
