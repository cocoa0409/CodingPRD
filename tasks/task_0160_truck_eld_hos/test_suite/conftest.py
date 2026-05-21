"""Pytest fixtures exposing test_helpers infrastructure.

The runner injects API_BASE_URL and PYTHONPATH; this file only wires
test_helpers symbols into pytest fixtures so individual tests can
request them as parameters.
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
# Shared-constant role headers. For ownership-gated Driver calls, tests
# MUST mint headers via make_driver_headers(driver_id) — the
# driver_headers fixture below is a placeholder used only for RBAC /
# 401 / 404 probes.
# ===========================================================================
@pytest.fixture
def driver_headers():
    """Placeholder Driver headers (NOT tied to any persisted Driver).
    Use only for auth / role-forbidden / 404 probes."""
    return TEST_USERS["driver_headers"]


@pytest.fixture
def officer_headers():
    return TEST_USERS["officer_headers"]


@pytest.fixture
def officer_secondary_headers():
    return TEST_USERS["officer_secondary_headers"]


@pytest.fixture
def auditor_headers():
    return TEST_USERS["auditor_headers"]


@pytest.fixture
def admin_headers():
    return TEST_USERS["admin_headers"]
