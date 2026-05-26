"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def claims_adjuster_headers():
    return TEST_USERS["claims_adjuster_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def owner_headers_shared():
    """Shared-constant Owner headers — only valid for tests that do NOT exercise
    ownership (e.g., 400-on-bad-payload, 403-on-forbidden-role). Tests that need
    ownership semantics MUST instead call make_owner_headers(owner_id)."""
    return TEST_USERS["owner_headers"]


@pytest.fixture
def sitter_headers_shared():
    """Shared-constant Sitter headers — only valid for tests that do NOT exercise
    ownership. Tests that need ownership semantics MUST instead call
    make_sitter_headers(sitter_id)."""
    return TEST_USERS["sitter_headers"]
