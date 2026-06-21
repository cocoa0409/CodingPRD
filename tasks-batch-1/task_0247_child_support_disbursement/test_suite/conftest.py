"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; each test starts against
a freshly-restarted (empty-database) API per the per-test-server isolation
contract.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def case_worker_headers() -> dict:
    return TEST_USERS["case_worker_headers"]


@pytest.fixture
def finance_officer_headers() -> dict:
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def supervisor_headers() -> dict:
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def employer_headers() -> dict:
    """Generic Employer headers (fake user-id). Use only for non-ownership
    tests (401/403/404 paths)."""
    return TEST_USERS["employer_headers"]


@pytest.fixture
def custodial_party_headers() -> dict:
    """Generic CustodialParty headers (fake user-id). Same caveat as
    employer_headers."""
    return TEST_USERS["custodial_party_headers"]
