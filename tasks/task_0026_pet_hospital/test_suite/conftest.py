"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle (start, readiness, shutdown) is managed by the runner
framework. PYTHONPATH already exposes test_helpers so we can import it
directly.
"""
from __future__ import annotations

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the runner manages base URL and HTTP transport."""
    return api_client


# --- One pytest fixture per role from PRD §2.1 ----------------------------
@pytest.fixture
def triage_nurse_headers():
    return TEST_USERS["triage_nurse_headers"]


@pytest.fixture
def triage_nurse_headers_alt():
    return TEST_USERS["triage_nurse_headers_alt"]


@pytest.fixture
def drafting_vet_headers():
    return TEST_USERS["drafting_vet_headers"]


@pytest.fixture
def drafting_vet_headers_alt():
    return TEST_USERS["drafting_vet_headers_alt"]


@pytest.fixture
def reviewing_vet_headers():
    return TEST_USERS["reviewing_vet_headers"]


@pytest.fixture
def reviewing_vet_headers_alt():
    return TEST_USERS["reviewing_vet_headers_alt"]


@pytest.fixture
def pharmacist_headers():
    return TEST_USERS["pharmacist_headers"]


@pytest.fixture
def cashier_headers():
    return TEST_USERS["cashier_headers"]


@pytest.fixture
def owner_service_headers():
    return TEST_USERS["owner_service_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]
