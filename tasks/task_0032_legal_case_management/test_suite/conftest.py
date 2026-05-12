"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start, readiness, shutdown) is managed by the
prd-bench-local-runner. Here we only wire up data fixtures.
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
    """Session-scoped API client. Base URL is supplied by the runner."""
    return api_client


# --- Opaque-role headers (PRD §2.1) ---------------------------------------
@pytest.fixture
def intake_clerk_headers():
    return TEST_USERS["intake_clerk_headers"]


@pytest.fixture
def intake_clerk_headers_alt():
    return TEST_USERS["intake_clerk_headers_alt"]


@pytest.fixture
def system_integrator_headers():
    return TEST_USERS["system_integrator_headers"]


# --- Entity-backed-role fallbacks (use only for non-ownership tests) ------
@pytest.fixture
def partner_headers_fallback():
    return TEST_USERS["partner_headers_fallback"]


@pytest.fixture
def senior_headers_fallback():
    return TEST_USERS["senior_headers_fallback"]


@pytest.fixture
def junior_headers_fallback():
    return TEST_USERS["junior_headers_fallback"]
