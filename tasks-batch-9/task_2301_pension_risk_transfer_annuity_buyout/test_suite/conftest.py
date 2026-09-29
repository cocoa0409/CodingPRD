"""Shared pytest fixtures for the Pension Risk Transfer & Annuity Buyout suite.

The harness relaunches the API server before every single test, so each test
begins against an empty database and builds all of its own preconditions
through declared endpoints.
"""

import os
import sys
from typing import Dict

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    PrtApiClient,
    actuary_alt_headers,
    actuary_headers,
    administrator_headers,
    api_client,
    fiduciary_alt_headers,
    fiduciary_headers,
    regulator_headers,
    sponsor_alt_headers,
    sponsor_headers,
)


@pytest.fixture(scope="session")
def api() -> PrtApiClient:
    """The endpoint-shaped HTTP client every test drives the API through."""
    return api_client()


@pytest.fixture
def sponsor() -> Dict[str, str]:
    """Headers for the acting `PlanSponsor`."""
    return sponsor_headers()


@pytest.fixture
def sponsor_alt() -> Dict[str, str]:
    """Headers for a second, distinct `PlanSponsor` identity."""
    return sponsor_alt_headers()


@pytest.fixture
def fiduciary() -> Dict[str, str]:
    """Headers for the acting `PlanFiduciary`."""
    return fiduciary_headers()


@pytest.fixture
def fiduciary_alt() -> Dict[str, str]:
    """Headers for a second, distinct `PlanFiduciary` identity."""
    return fiduciary_alt_headers()


@pytest.fixture
def actuary() -> Dict[str, str]:
    """Headers for the acting `Actuary`."""
    return actuary_headers()


@pytest.fixture
def actuary_alt() -> Dict[str, str]:
    """Headers for a second, distinct `Actuary` identity."""
    return actuary_alt_headers()


@pytest.fixture
def administrator() -> Dict[str, str]:
    """Headers for the acting `PlanAdministrator`."""
    return administrator_headers()


@pytest.fixture
def regulator() -> Dict[str, str]:
    """Headers for the acting `Regulator`."""
    return regulator_headers()
