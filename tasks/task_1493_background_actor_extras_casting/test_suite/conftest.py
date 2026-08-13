"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def associate_headers():
    return TEST_USERS["associate_headers"]


@pytest.fixture
def payroll_headers():
    return TEST_USERS["payroll_headers"]


@pytest.fixture
def union_rep_headers():
    return TEST_USERS["union_rep_headers"]


@pytest.fixture
def actor_headers():
    return TEST_USERS["actor_headers"]
