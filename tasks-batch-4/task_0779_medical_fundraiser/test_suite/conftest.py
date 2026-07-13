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


# Opaque roles — shared constants are canonical (PRD §2.1).
@pytest.fixture
def guest_headers() -> dict:
    return TEST_USERS["guest_headers"]


@pytest.fixture
def ts_agent_headers() -> dict:
    return TEST_USERS["ts_agent_headers"]


@pytest.fixture
def admin_headers() -> dict:
    return TEST_USERS["admin_headers"]


# Entity-backed roles — placeholder X-User-IDs. Safe only for non-ownership
# tests; ownership-gated paths must use make_<role>_headers(entity_id).
@pytest.fixture
def organizer_headers() -> dict:
    return TEST_USERS["organizer_headers"]


@pytest.fixture
def beneficiary_headers() -> dict:
    return TEST_USERS["beneficiary_headers"]


@pytest.fixture
def donor_headers() -> dict:
    return TEST_USERS["donor_headers"]
