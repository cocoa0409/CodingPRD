"""Pytest fixtures exposing test_helpers infrastructure.

The runner handles PYTHONPATH so test_helpers is importable, and owns the
server lifecycle — tests assume the API is already reachable at API_BASE_URL.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def fair_director_headers():
    return TEST_USERS["fair_director_headers"]


@pytest.fixture
def ethics_reviewer_headers():
    return TEST_USERS["ethics_reviewer_headers"]


@pytest.fixture
def operations_lead_headers():
    return TEST_USERS["operations_lead_headers"]


@pytest.fixture
def safety_inspector_headers():
    return TEST_USERS["safety_inspector_headers"]


@pytest.fixture
def mentor_headers():
    return TEST_USERS["mentor_headers"]


@pytest.fixture
def judge_headers():
    return TEST_USERS["judge_headers"]
