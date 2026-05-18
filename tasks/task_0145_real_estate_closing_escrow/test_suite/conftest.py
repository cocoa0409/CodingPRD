"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH so `test_helpers` imports without sys.path
hacks. These fixtures expose the api client and per-role headers.
"""
from __future__ import annotations

import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by
    prd-bench-local-runner; tests assume the server is reachable at
    API_BASE_URL."""
    return api_client


# ---------------------------------------------------------------------------
# Role headers — OPAQUE roles (shared constant is canonical).
# Buyer / Seller headers are NOT exposed here because their X-User-ID is
# entity-backed (PRD §2.1). Tests build them via
# make_buyer_headers(escrow_file["buyer_party_id"]).
# ---------------------------------------------------------------------------
@pytest.fixture
def escrow_officer_headers():
    return TEST_USERS["escrow_officer_headers"]


@pytest.fixture
def escrow_officer_headers_alt():
    return TEST_USERS["escrow_officer_headers_alt"]


@pytest.fixture
def title_officer_headers():
    return TEST_USERS["title_officer_headers"]


@pytest.fixture
def disb_approver_headers():
    return TEST_USERS["disb_approver_headers"]


@pytest.fixture
def buyer_fallback_headers():
    """Entity-backed Buyer fallback — DO NOT use for ownership-gated
    calls. Safe only for header-missing / role-mismatch / 404 paths."""
    return TEST_USERS["buyer_fallback_headers"]


@pytest.fixture
def seller_fallback_headers():
    """Entity-backed Seller fallback — DO NOT use for ownership-gated
    calls. Safe only for header-missing / role-mismatch / 404 paths."""
    return TEST_USERS["seller_fallback_headers"]
