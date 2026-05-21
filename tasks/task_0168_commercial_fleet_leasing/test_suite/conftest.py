"""Pytest fixtures exposing test_helpers infrastructure.

The runner injects API_BASE_URL and PYTHONPATH; this file only wires
test_helpers symbols into pytest fixtures so individual tests can
request them as parameters.

PRD §2.1: Lessee is an entity_backed role. The shared-constant fixture
below is a placeholder used only by tests that probe auth / role / 404
paths without exercising ownership. Tests that exercise ownership use
make_lessee_headers with the actual Lessee.id.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
)


# ===========================================================================
# Session-scoped API client — server lifecycle managed by the runner.
# ===========================================================================
@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client."""
    return api_client


# ===========================================================================
# Shared-constant role headers. For ownership-gated calls (dispute),
# tests MUST mint headers via make_lessee_headers(lessee_id).
# ===========================================================================
@pytest.fixture
def fleet_manager_headers():
    return TEST_USERS["fleet_manager_headers"]


@pytest.fixture
def fleet_manager_secondary_headers():
    return TEST_USERS["fleet_manager_secondary_headers"]


@pytest.fixture
def tax_admin_headers():
    return TEST_USERS["tax_admin_headers"]


@pytest.fixture
def claim_adjuster_headers():
    return TEST_USERS["claim_adjuster_headers"]


@pytest.fixture
def vendor_ops_headers():
    return TEST_USERS["vendor_ops_headers"]


@pytest.fixture
def lessee_headers():
    """Placeholder Lessee headers (NOT tied to any persisted Lessee).
    Use only for auth / role-forbidden / 404 probes."""
    return TEST_USERS["lessee_headers"]
