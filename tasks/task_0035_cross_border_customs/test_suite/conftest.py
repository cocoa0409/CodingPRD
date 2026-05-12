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
    """Session-scoped API client. The base URL is supplied by the runner."""
    return api_client


# --- Opaque-role canonical headers (PRD §2.1) ---

@pytest.fixture
def customs_officer_headers():
    return TEST_USERS["customs_officer_headers"]


@pytest.fixture
def customs_officer_headers_alt():
    return TEST_USERS["customs_officer_headers_alt"]


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def finance_officer_headers_alt():
    return TEST_USERS["finance_officer_headers_alt"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


# --- Entity-backed fallbacks (PRD §2.1) ---
# These are ONLY for tests that don't reach an ownership check —
# wrong-role 403 tests, missing-resource 404 tests. Any ownership-
# gated test must call make_declarant_headers(declarant['id']) /
# make_importer_headers(importer['id']) with a real entity id.

@pytest.fixture
def declarant_headers_fallback():
    return TEST_USERS["declarant_headers"]


@pytest.fixture
def importer_headers_fallback():
    return TEST_USERS["importer_headers"]
