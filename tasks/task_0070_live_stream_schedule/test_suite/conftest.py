"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so ``test_helpers`` is importable directly.
"""

import pytest

from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    ADMIN_HEADERS,
    OPS_HEADERS,
    COMPLIANCE_HEADERS,
    OPS_HEADERS_2,
    COMPLIANCE_HEADERS_2,
    PLACEHOLDER_STREAMER_HEADERS,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def admin_headers():
    return ADMIN_HEADERS


@pytest.fixture
def ops_headers():
    return OPS_HEADERS


@pytest.fixture
def compliance_headers():
    return COMPLIANCE_HEADERS


@pytest.fixture
def ops_headers_2():
    return OPS_HEADERS_2


@pytest.fixture
def compliance_headers_2():
    return COMPLIANCE_HEADERS_2


@pytest.fixture
def placeholder_streamer_headers():
    """Streamer headers with a non-matching X-User-ID — for ownership-failure tests."""
    return PLACEHOLDER_STREAMER_HEADERS
