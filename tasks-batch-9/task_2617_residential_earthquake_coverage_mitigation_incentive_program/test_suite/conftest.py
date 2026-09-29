"""Pytest fixtures exposing the test helper infrastructure."""
from typing import Dict

import pytest
from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def program_admin_headers() -> Dict[str, str]:
    """Headers for a program administrator."""
    return TEST_USERS["program_admin"]


@pytest.fixture
def program_admin_alt_headers() -> Dict[str, str]:
    """Headers for a second, distinct program administrator."""
    return TEST_USERS["program_admin_alt"]


@pytest.fixture
def grant_reviewer_headers() -> Dict[str, str]:
    """Headers for a grant reviewer."""
    return TEST_USERS["grant_reviewer"]


@pytest.fixture
def grant_reviewer_alt_headers() -> Dict[str, str]:
    """Headers for a second, distinct grant reviewer."""
    return TEST_USERS["grant_reviewer_alt"]


@pytest.fixture
def field_inspector_headers() -> Dict[str, str]:
    """Headers for a field inspector."""
    return TEST_USERS["field_inspector"]


@pytest.fixture
def field_inspector_alt_headers() -> Dict[str, str]:
    """Headers for a second, distinct field inspector."""
    return TEST_USERS["field_inspector_alt"]


@pytest.fixture
def claim_adjuster_headers() -> Dict[str, str]:
    """Headers for a claim adjuster."""
    return TEST_USERS["claim_adjuster"]


@pytest.fixture
def claim_adjuster_alt_headers() -> Dict[str, str]:
    """Headers for a second, distinct claim adjuster."""
    return TEST_USERS["claim_adjuster_alt"]
