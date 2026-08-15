"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; the suite assumes the
API is already reachable at API_BASE_URL and that the server is relaunched
(with an empty database) before every test.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def radiopharmacist_headers():
    return TEST_USERS["radiopharmacist_headers"]


@pytest.fixture
def technologist_headers():
    return TEST_USERS["technologist_headers"]


@pytest.fixture
def rso_headers():
    return TEST_USERS["rso_headers"]
