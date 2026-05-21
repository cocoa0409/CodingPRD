"""Pytest fixtures exposing test_helpers infrastructure.

The runner injects API_BASE_URL and PYTHONPATH; this file only wires
test_helpers symbols into pytest fixtures so individual tests can
request them as parameters.

PRD §2.1: Boater is an entity_backed role. The shared-constant
`boater_headers` fixture below is a placeholder used only by tests that
probe auth / role / 404 paths without exercising ownership. Tests that
exercise ownership use make_boater_headers with the actual Boater.id.
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
# Shared-constant role headers. For ownership-gated calls, tests MUST
# mint headers via make_boater_headers(boater_id).
# ===========================================================================
@pytest.fixture
def boater_headers():
    """Placeholder Boater headers (NOT tied to any persisted Boater).
    Use only for auth / role-forbidden / 404 probes."""
    return TEST_USERS["boater_headers"]


@pytest.fixture
def dock_master_headers():
    return TEST_USERS["dock_master_headers"]


@pytest.fixture
def dock_master_secondary_headers():
    return TEST_USERS["dock_master_secondary_headers"]


@pytest.fixture
def billing_clerk_headers():
    return TEST_USERS["billing_clerk_headers"]
