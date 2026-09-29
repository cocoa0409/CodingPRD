"""Pytest wiring for the Money Transmitter Licensing API compliance suite.

The runner owns the server lifecycle and restarts it before every test, so each
test starts against an empty database with the logical clock at its process-start
instant of 2026-08-01T00:00:00Z. All setup therefore runs through the API's own
declared endpoints.
"""

import pytest

from test_helpers import MoneyTransmitterApiClient, install_error_status_map
from test_helpers import constants as C
from test_helpers import fixtures as fx

# Teach the shared validators the HTTP status that PRD section 5 pins to each
# error id, so asserting an error id also asserts its status code.
install_error_status_map()


@pytest.fixture
def api() -> MoneyTransmitterApiClient:
    """A fresh client against the running server."""
    return MoneyTransmitterApiClient()


@pytest.fixture
def ca_jurisdiction(api: MoneyTransmitterApiClient) -> dict:
    """One configured jurisdiction: California DFPI."""
    return fx.create_jurisdiction(api, C.CA_CONFIG)


@pytest.fixture
def licensee(api: MoneyTransmitterApiClient) -> dict:
    """One registered money services business."""
    return fx.create_licensee(api)


@pytest.fixture
def pending_bond_license(api: MoneyTransmitterApiClient) -> fx.Scenario:
    """An approved licence still in PENDING_BOND with no bond on file."""
    return fx.setup_pending_bond_license(api)


@pytest.fixture
def active_license(api: MoneyTransmitterApiClient) -> fx.Scenario:
    """A bonded, ACTIVE California licence with its expansion gate OPEN."""
    return fx.setup_active_license(api)
