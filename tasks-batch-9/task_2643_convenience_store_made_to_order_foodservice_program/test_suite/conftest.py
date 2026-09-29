"""Shared pytest wiring for the made-to-order foodservice compliance suite.

The runner restarts the service against an empty store before every single
test, so nothing here caches domain state. Each fixture either hands the test a
client or hands it headers; every precondition a test needs is built inside
that test through declared endpoints.
"""

import os
import sys
from typing import Dict

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_errors  # noqa: E402,F401  (registers the status map)
from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    CHAIN_ADMIN_HEADERS,
    FOOD_SAFETY_LEAD_HEADERS,
    KITCHEN_ASSOCIATE_2_HEADERS,
    KITCHEN_ASSOCIATE_HEADERS,
    SHIFT_LEAD_2_HEADERS,
    SHIFT_LEAD_HEADERS,
    STORE_MANAGER_HEADERS,
    STORE_TERMINAL_HEADERS,
)


@pytest.fixture()
def api() -> ApiClient:
    """A client bound to the service under test."""
    return ApiClient()


@pytest.fixture()
def admin() -> Dict[str, str]:
    """`ChainAdmin` headers: chain configuration and the logical clock."""
    return dict(CHAIN_ADMIN_HEADERS)


@pytest.fixture()
def manager() -> Dict[str, str]:
    """`StoreManager` headers: site setup, labor plans, daypart flips."""
    return dict(STORE_MANAGER_HEADERS)


@pytest.fixture()
def associate() -> Dict[str, str]:
    """`KitchenAssociate` headers: baking, holding and the make line."""
    return dict(KITCHEN_ASSOCIATE_HEADERS)


@pytest.fixture()
def associate_alt() -> Dict[str, str]:
    """A second, distinct `KitchenAssociate` identity."""
    return dict(KITCHEN_ASSOCIATE_2_HEADERS)


@pytest.fixture()
def lead() -> Dict[str, str]:
    """`ShiftLead` headers: rework, write-offs, voids and refunds."""
    return dict(SHIFT_LEAD_HEADERS)


@pytest.fixture()
def lead_alt() -> Dict[str, str]:
    """A second, distinct `ShiftLead` identity."""
    return dict(SHIFT_LEAD_2_HEADERS)


@pytest.fixture()
def safety() -> Dict[str, str]:
    """`FoodSafetyLead` headers: probe readings and corrective actions."""
    return dict(FOOD_SAFETY_LEAD_HEADERS)


@pytest.fixture()
def terminal() -> Dict[str, str]:
    """`StoreTerminal` headers: the in-store ordering surface."""
    return dict(STORE_TERMINAL_HEADERS)
