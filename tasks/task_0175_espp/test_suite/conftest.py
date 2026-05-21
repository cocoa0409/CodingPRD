"""Pytest fixtures exposing test_helpers infrastructure.

The runner injects API_BASE_URL and PYTHONPATH; this file only wires
test_helpers symbols into pytest fixtures so individual tests can
request them as parameters.

PRD §2.1: Participant is the only entity_backed role. The shared-
constant `participant_headers` fixture is a placeholder used only by
tests that probe auth / role / 404 paths without exercising ownership.
Tests that exercise ownership mint headers via
`make_participant_headers(participant_id)` with the actual id.
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
# Shared-constant role headers.
# ===========================================================================
@pytest.fixture
def plan_admin_headers():
    return TEST_USERS["plan_admin_headers"]


@pytest.fixture
def plan_admin_secondary_headers():
    return TEST_USERS["plan_admin_secondary_headers"]


@pytest.fixture
def payroll_agent_headers():
    return TEST_USERS["payroll_agent_headers"]


@pytest.fixture
def payroll_agent_secondary_headers():
    return TEST_USERS["payroll_agent_secondary_headers"]


@pytest.fixture
def participant_headers():
    """Placeholder Participant headers (NOT tied to any real participant).
    Use only for auth / role-forbidden / 404 probes."""
    return TEST_USERS["participant_headers"]


@pytest.fixture
def tax_authority_headers():
    return TEST_USERS["tax_authority_headers"]
