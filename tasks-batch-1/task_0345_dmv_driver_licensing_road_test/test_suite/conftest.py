"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start/stop/health) is owned by prd-bench-local-runner; this file
only wires test_helpers into pytest fixtures.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def clerk_headers():
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def clerk2_headers():
    return TEST_USERS["clerk2_headers"]


@pytest.fixture
def proctor_headers():
    return TEST_USERS["proctor_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def officer2_headers():
    return TEST_USERS["officer2_headers"]


@pytest.fixture
def examiner_headers():
    return TEST_USERS["examiner_headers"]
