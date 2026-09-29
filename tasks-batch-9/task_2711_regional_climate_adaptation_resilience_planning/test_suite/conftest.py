"""Shared pytest wiring for the resilience planning suite."""

import os
import sys
from typing import Dict

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ApiClient,
    api_client,
    make_bca_reviewer_headers,
    make_equity_officer_headers,
    make_hazard_analyst_headers,
    make_regional_administrator_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    return api_client


@pytest.fixture
def admin_headers() -> Dict[str, str]:
    """A `RegionalAdministrator` caller (PRD 2.1)."""
    return make_regional_administrator_headers()


@pytest.fixture
def analyst_headers() -> Dict[str, str]:
    """A `HazardAnalyst` caller (PRD 2.1)."""
    return make_hazard_analyst_headers()


@pytest.fixture
def reviewer_headers() -> Dict[str, str]:
    """A `BCAReviewer` caller (PRD 2.1)."""
    return make_bca_reviewer_headers()


@pytest.fixture
def equity_officer_headers() -> Dict[str, str]:
    """An `EquityOfficer` caller (PRD 2.1)."""
    return make_equity_officer_headers()
