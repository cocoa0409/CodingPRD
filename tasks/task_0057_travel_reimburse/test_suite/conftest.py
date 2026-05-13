"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable without
sys.path hacks. Server lifecycle (start/stop/readiness/crash-recovery)
is the runner's job — these fixtures only wire up the API client and
the role headers from PRD §2.1.
"""
from __future__ import annotations

import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by
    prd-bench-local-runner."""
    return api_client


# --- Opaque-role headers (PRD §2.1: Admin is opaque) ---
@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]


@pytest.fixture
def admin_headers_alt():
    return TEST_USERS["admin_headers_alt"]


# --- Entity-backed fallbacks (PRD §2.1) ---
#
# These are SAFE only for tests that do NOT exercise ownership. Tests
# that need real ownership/chain-step semantics call the per-instance
# builders (make_*_headers) or use a fixture from test_helpers.fixtures
# whose returned ApprovalCast carries identity-threaded headers.
@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def dept_head_headers():
    return TEST_USERS["dept_head_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def general_manager_headers():
    return TEST_USERS["general_manager_headers"]
