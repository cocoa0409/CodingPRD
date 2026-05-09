"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start, readiness, shutdown) is managed by the
prd-bench-local-runner framework. PYTHONPATH points at the parent
directory so `test_helpers` is importable directly.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client.

    The base URL and HTTP transport are managed by the runner; we just
    return the singleton.
    """
    return api_client


# --- Opaque-role headers (PRD §2.1) -------------------------------------
@pytest.fixture
def organizer_headers():
    return TEST_USERS["organizer_headers"]


@pytest.fixture
def organizer_headers_alt():
    return TEST_USERS["organizer_headers_alt"]


@pytest.fixture
def disciplinary_headers():
    return TEST_USERS["disciplinary_headers"]


@pytest.fixture
def doping_headers():
    return TEST_USERS["doping_headers"]


@pytest.fixture
def doping_headers_alt():
    return TEST_USERS["doping_headers_alt"]


@pytest.fixture
def appeals_headers():
    return TEST_USERS["appeals_headers"]


# --- Entity-backed-role fallback headers (PRD §2.1) ---------------------
# Use only for tests that don't exercise an ownership comparison.
@pytest.fixture
def referee_headers_fallback():
    return TEST_USERS["referee_headers"]


@pytest.fixture
def participant_headers_fallback():
    return TEST_USERS["participant_headers"]
