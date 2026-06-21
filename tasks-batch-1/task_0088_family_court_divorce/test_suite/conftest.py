"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, and re-launches the
API server before every test (empty DB each time).
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def judge_headers():
    return TEST_USERS["judge_headers"]


@pytest.fixture
def mediator_headers():
    return TEST_USERS["mediator_headers"]


@pytest.fixture
def petitioner_headers():
    return TEST_USERS["petitioner_headers"]


@pytest.fixture
def respondent_headers():
    return TEST_USERS["respondent_headers"]
