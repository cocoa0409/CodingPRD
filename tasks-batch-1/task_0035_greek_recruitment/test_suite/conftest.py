"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is managed by prd-bench-local-runner; each test starts
against a freshly-restarted (empty-database) API per the per-test-server
isolation contract.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


@pytest.fixture
def panhellenic_admin_headers() -> dict:
    return TEST_USERS["panhellenic_admin_headers"]


@pytest.fixture
def recruitment_chair_headers() -> dict:
    return TEST_USERS["recruitment_chair_headers"]


@pytest.fixture
def risk_officer_headers() -> dict:
    return TEST_USERS["risk_officer_headers"]


@pytest.fixture
def anonymous_headers() -> dict:
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def chapter_officer_headers() -> dict:
    """Fallback chapter-officer headers (fake user-id). For ownership-gated calls,
    use make_chapter_officer_headers(chapter['id']) instead."""
    return TEST_USERS["chapter_officer_headers"]


@pytest.fixture
def pnm_headers() -> dict:
    """Fallback PNM headers (fake user-id). For ownership-gated calls, use
    make_pnm_headers(pnm['id']) instead."""
    return TEST_USERS["pnm_headers"]
