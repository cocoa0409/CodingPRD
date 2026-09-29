"""Shared pytest fixtures for the price-integrity compliance suite.

The harness restarts the API before every individual test, so each test opens
against an empty database and builds its own preconditions.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import Builder, PriceIntegrityApiClient  # noqa: E402
from test_helpers.constants import DEFAULT_CLOCK  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    make_compliance_officer_headers,
    make_customer_service_desk_headers,
    make_pricing_admin_headers,
)


@pytest.fixture
def api() -> PriceIntegrityApiClient:
    """A client pointed at the API under test."""
    return PriceIntegrityApiClient()


@pytest.fixture
def build(api: PriceIntegrityApiClient) -> Builder:
    """Precondition builder with the logical clock pinned to its default."""
    builder = Builder(api)
    builder.set_clock(DEFAULT_CLOCK)
    return builder


@pytest.fixture
def admin_headers():
    return make_pricing_admin_headers()


@pytest.fixture
def officer_headers():
    return make_compliance_officer_headers()


@pytest.fixture
def desk_headers():
    return make_customer_service_desk_headers()
