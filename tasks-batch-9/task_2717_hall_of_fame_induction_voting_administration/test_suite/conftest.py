"""Pytest wiring for the Hall of Fame induction and voting API suite.

The local runner owns the server lifecycle, ``API_BASE_URL`` and ``PYTHONPATH``;
this module only exposes the shared client and the per-role header bundles that
``test_helpers`` builds.
"""

import pytest

from test_helpers import (  # noqa: F401
    ADMIN_HEADERS,
    AUDITOR_HEADERS,
    CURATOR_HEADERS,
    TEST_USERS,
    ApiClient,
    api_client,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The shared API client. The runner restarts the server per test."""
    return api_client


@pytest.fixture
def admin_headers() -> dict:
    """``ElectionAdministrator`` headers (opaque identity)."""
    return dict(ADMIN_HEADERS)


@pytest.fixture
def auditor_headers() -> dict:
    """``IndependentAuditor`` headers (opaque identity)."""
    return dict(AUDITOR_HEADERS)


@pytest.fixture
def curator_headers() -> dict:
    """``CuratorialStaff`` headers (opaque identity)."""
    return dict(CURATOR_HEADERS)


@pytest.fixture
def second_auditor_headers() -> dict:
    """A second ``IndependentAuditor`` identity, for segregation-of-duties work."""
    return dict(TEST_USERS["second_auditor_headers"])
