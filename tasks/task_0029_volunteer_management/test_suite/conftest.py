"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start, readiness, shutdown) is managed by the
prd-bench-local-runner framework. PYTHONPATH points at the parent
directory so `test_helpers` is importable directly.
"""
from __future__ import annotations

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


# --- Opaque-role headers (PRD §2.1) ---------------------------------------
@pytest.fixture
def skilladmin_headers():
    return TEST_USERS["skilladmin_headers"]


@pytest.fixture
def skilladmin_headers_alt():
    return TEST_USERS["skilladmin_headers_alt"]


# --- Entity-backed-role fallback headers (PRD §2.1) -----------------------
# Use only for tests that don't exercise an ownership comparison. Tests
# whose success depends on Application.volunteer_id == X-User-ID or
# Activity.organizer_id == X-User-ID must call
# make_volunteer_headers(volunteer["id"]) or
# make_organizer_headers(volunteer["id"]) instead.
@pytest.fixture
def volunteer_headers_fallback():
    return TEST_USERS["volunteer_headers"]


@pytest.fixture
def organizer_headers_fallback():
    return TEST_USERS["organizer_headers"]
