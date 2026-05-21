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
# Session-scoped API client — server lifecycle is managed by the runner.
# ===========================================================================
@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by
    prd-bench-local-runner."""
    return api_client


# ===========================================================================
# Shared-constant role headers — opaque roles and entity_backed
# placeholders. For ownership-gated calls, tests MUST mint headers via
# make_filer_headers(entity_id) / make_registered_agent_headers(agent_id).
# ===========================================================================
@pytest.fixture
def filer_headers():
    """Placeholder Filer headers (NOT tied to any entity). Use only for
    auth / role-forbidden / 404 probes."""
    return TEST_USERS["filer_headers"]


@pytest.fixture
def state_registrar_headers():
    return TEST_USERS["state_registrar_headers"]


@pytest.fixture
def state_registrar_secondary_headers():
    return TEST_USERS["state_registrar_secondary_headers"]


@pytest.fixture
def tax_officer_headers():
    return TEST_USERS["tax_officer_headers"]


@pytest.fixture
def tax_officer_secondary_headers():
    return TEST_USERS["tax_officer_secondary_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def registered_agent_service_headers():
    """Placeholder RegisteredAgentService headers (NOT tied to any
    agent). For agent-create / agent-update tests, this is fine because
    PRD §3.2 doesn't gate creation on ownership; for /resign tests, use
    make_registered_agent_headers(agent_id)."""
    return TEST_USERS["registered_agent_service_headers"]


@pytest.fixture
def test_harness_headers():
    return TEST_USERS["test_harness_headers"]
