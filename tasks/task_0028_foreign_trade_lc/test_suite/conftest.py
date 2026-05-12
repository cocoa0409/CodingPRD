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


# --- One pytest fixture per role from PRD §2.1 ---------------------------
# These shared-constant headers are appropriate ONLY for tests that do
# not exercise an ownership check (RBAC forbidden-role checks before any
# entity exists, missing-resource 404s, malformed-payload 400s). Tests
# that exercise an ownership-gated endpoint must use the per-instance
# builders (make_*_headers from test_helpers) with the actual entity id.

@pytest.fixture
def applicant_headers():
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def beneficiary_headers():
    return TEST_USERS["beneficiary_headers"]


@pytest.fixture
def issuing_bank_headers():
    return TEST_USERS["issuing_bank_headers"]


@pytest.fixture
def advising_bank_headers():
    return TEST_USERS["advising_bank_headers"]


@pytest.fixture
def confirming_bank_headers():
    return TEST_USERS["confirming_bank_headers"]


@pytest.fixture
def negotiating_bank_headers():
    return TEST_USERS["negotiating_bank_headers"]


@pytest.fixture
def operator_headers():
    return TEST_USERS["operator_headers"]


@pytest.fixture
def operator_headers_alt():
    return TEST_USERS["operator_headers_alt"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]
