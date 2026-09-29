"""
Shared pytest configuration for the guitar factory operations suite.

Importing the error module registers the documented error-id to HTTP-status map,
so every error assertion in the suite is cross-checked against the status the
specification pins for that identifier. The fixtures are re-exported here so a
test file can request a precondition by name without importing anything.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import test_helpers.api_errors  # noqa: F401,E402  (registers the status map)
from test_helpers.fixtures import (  # noqa: F401,E402
    api,
    chain_a,
    chain_b,
    chain_c,
    chain_two_orders,
    clock,
    comp_routed,
    four_lots,
    lot_after_big_cut,
    lot_permit_hold,
    lot_received,
    lot_rejected,
    lot_released,
    machine_shop,
    one_cnc_station,
    order_at_inspection,
    order_in_assembly,
    order_two_components_released,
    order_two_options,
    order_with_vine,
    shipment_docs_pending,
    two_authorized_shops,
    two_confirmed_orders_on_cnc1,
    two_lots_one_conditioned,
    two_orders_custom_and_standard,
)
