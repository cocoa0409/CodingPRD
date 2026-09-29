"""Shared pytest fixtures for the Fastener Cold Heading & Thread Rolling suite.

The harness relaunches the API server before every individual test, so each test
sees an empty plant whose logical clock reads exactly ``2026-08-01T00:00:00Z``
(PRD §2.4). Nothing is shared between tests: every fixture below is either
stateless (the client, header dicts) or builds its records from scratch through
the PRD's own endpoints.
"""

from typing import Any, Dict

import pytest

from test_helpers import TEST_USERS, api_client, fixtures


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def api():
    """The HTTP client for the API under test. Stateless, so shared for the session."""
    return api_client


# ---------------------------------------------------------------------------
# Operator headers, one fixture per role in PRD §2.1
# ---------------------------------------------------------------------------
@pytest.fixture
def engineer_headers() -> Dict[str, str]:
    """ProcessEngineer acting as ``eng-1``."""
    return TEST_USERS["engineer_headers"]


@pytest.fixture
def heat_treat_headers() -> Dict[str, str]:
    """HeatTreatOperator acting as ``ht-1``."""
    return TEST_USERS["heat_treat_headers"]


@pytest.fixture
def inspector_headers() -> Dict[str, str]:
    """QualityInspector acting as ``insp-1``."""
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def inspector_alt_headers() -> Dict[str, str]:
    """A second QualityInspector, ``insp-2``, for segregation-of-duties contrasts."""
    return TEST_USERS["inspector_alt_headers"]


@pytest.fixture
def manager_headers() -> Dict[str, str]:
    """QualityManager acting as ``qm-1``."""
    return TEST_USERS["manager_headers"]


@pytest.fixture
def manager_alt_headers() -> Dict[str, str]:
    """A second QualityManager, ``qm-2``, for segregation-of-duties contrasts."""
    return TEST_USERS["manager_alt_headers"]


@pytest.fixture
def clerk_headers() -> Dict[str, str]:
    """ShippingClerk acting as ``ship-1``."""
    return TEST_USERS["clerk_headers"]


@pytest.fixture
def admin_headers() -> Dict[str, str]:
    """PlantAdmin acting as ``admin-1``."""
    return TEST_USERS["admin_headers"]


# ---------------------------------------------------------------------------
# Frequently reused plant states
# ---------------------------------------------------------------------------
@pytest.fixture
def master_data() -> Dict[str, Any]:
    """Part spec, VERIFIED heat, RELEASED wire lot, MOUNTED die set and furnace."""
    return fixtures.setup_master_data()


@pytest.fixture
def unplated_master_data() -> Dict[str, Any]:
    """The same preamble for a part whose ``plating_spec`` is ``NONE``."""
    return fixtures.setup_master_data(unplated=True)
