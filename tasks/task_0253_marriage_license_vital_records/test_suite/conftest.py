"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages server lifecycle (restart before every test) and PYTHONPATH,
so test_helpers is importable directly and the API client needs no health-check.
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
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def registrar2_headers():
    return TEST_USERS["registrar2_headers"]


@pytest.fixture
def waiver_officer_headers():
    return TEST_USERS["waiver_officer_headers"]


@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def officiant_headers():
    return TEST_USERS["officiant_headers"]
