"""Pytest fixtures exposing the ``test_helpers`` infrastructure.

The runner owns the server lifecycle and the ``PYTHONPATH``, so
``test_helpers`` imports without any path manipulation. The server is
relaunched against an empty store before each test, so every fixture that
builds data is function-scoped and constructs its state through the API's own
endpoints.
"""

import pytest

from test_helpers import (
    ADMIN_HEADERS,
    PLANT_COUNTER_HEADERS,
    ApiClient,
    api_client,
)

# The data fixtures defined alongside the composite state builders are
# re-exported here so pytest can discover them by name.
from test_helpers.fixtures import (
    counted_bag_drop,
    counted_visit,
    distributor,
    enrolled_account,
    obligated_retailer,
    open_period,
    operational_center,
    registered_product,
    world,
)

__all__ = [
    "admin_headers",
    "api",
    "counted_bag_drop",
    "counted_visit",
    "distributor",
    "enrolled_account",
    "obligated_retailer",
    "open_period",
    "operational_center",
    "plant_counter_headers",
    "registered_product",
    "world",
]


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """The API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def admin_headers():
    """Programme staff headers; the acting id is an opaque operator id."""
    return ADMIN_HEADERS


@pytest.fixture
def plant_counter_headers():
    """Central plant counting staff headers; the acting id is opaque."""
    return PLANT_COUNTER_HEADERS
