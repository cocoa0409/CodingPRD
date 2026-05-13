"""Pytest fixtures exposing test_helpers infrastructure.

Server lifecycle is owned by prd-bench-local-runner; conftest only
wires up shared in-test infrastructure.
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
    """Session-scoped API client. Server lifecycle is managed externally."""
    return api_client


# ===========================================================================
# Opaque-role header fixtures (PRD §2.1: ProcurementOfficer, Regulator,
# EvaluationExpert identities are opaque operator ids).
# ===========================================================================
@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def officer_headers_alt():
    return TEST_USERS["officer_headers_alt"]


@pytest.fixture
def regulator_headers():
    return TEST_USERS["regulator_headers"]


@pytest.fixture
def regulator_headers_alt():
    return TEST_USERS["regulator_headers_alt"]


@pytest.fixture
def expert_headers():
    return TEST_USERS["expert_headers"]


@pytest.fixture
def expert_headers_alt():
    return TEST_USERS["expert_headers_alt"]


@pytest.fixture
def expert_headers_third():
    return TEST_USERS["expert_headers_third"]


@pytest.fixture
def supplier_fallback_headers():
    """Non-ownership Supplier fallback. PRD §2.1 requires real Supplier
    calls to use make_supplier_headers(<supplier_id>) — this fallback is
    only for negative tests that don't traverse ownership."""
    return TEST_USERS["supplier_fallback_headers"]
