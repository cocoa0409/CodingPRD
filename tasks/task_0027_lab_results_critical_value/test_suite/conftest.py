"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; each test starts against a
freshly-restarted (empty-database) API per the per-test-server isolation contract.
"""
import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def anonymous_headers() -> dict:
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def ordering_provider_headers() -> dict:
    """Generic (entity-unbound) OrderingProvider headers. PRD §2.1: for
    ownership-gated tests, use `make_ordering_provider_headers(clinician_id)`
    instead.
    """
    return TEST_USERS["ordering_provider_headers"]


@pytest.fixture
def phlebotomist_headers() -> dict:
    return TEST_USERS["phlebotomist_headers"]


@pytest.fixture
def lab_tech_headers() -> dict:
    return TEST_USERS["lab_tech_headers"]


@pytest.fixture
def lab_director_headers() -> dict:
    return TEST_USERS["lab_director_headers"]
