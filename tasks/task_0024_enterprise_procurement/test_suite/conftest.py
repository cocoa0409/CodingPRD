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
def requester_headers():
    return TEST_USERS["requester_headers"]


@pytest.fixture
def requester_headers_alt():
    return TEST_USERS["requester_headers_alt"]


@pytest.fixture
def buyer_headers():
    return TEST_USERS["buyer_headers"]


@pytest.fixture
def buyer_headers_alt():
    return TEST_USERS["buyer_headers_alt"]


@pytest.fixture
def dept_head_headers():
    return TEST_USERS["dept_head_headers"]


@pytest.fixture
def dept_head_headers_alt():
    return TEST_USERS["dept_head_headers_alt"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def finance_headers_alt():
    return TEST_USERS["finance_headers_alt"]


@pytest.fixture
def finance_headers_third():
    return TEST_USERS["finance_headers_third"]


@pytest.fixture
def legal_headers():
    return TEST_USERS["legal_headers"]


@pytest.fixture
def legal_headers_alt():
    return TEST_USERS["legal_headers_alt"]


@pytest.fixture
def gm_headers():
    return TEST_USERS["gm_headers"]


@pytest.fixture
def gm_headers_alt():
    return TEST_USERS["gm_headers_alt"]


@pytest.fixture
def inspector_headers():
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


# --- Entity-backed Supplier fallback headers (PRD §2.1) -----------------
# Use only for tests that don't exercise an ownership comparison; otherwise
# tests must call make_supplier_headers(supplier["id"]).
@pytest.fixture
def supplier_headers_fallback():
    return TEST_USERS["supplier_headers"]
