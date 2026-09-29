"""
Pytest configuration for the warehouse receipt & commodity collateral suite.

Re-exports the composite fixtures defined in test_helpers.fixtures so every
test module can request them by name. The API server is restarted before every
test, so each fixture rebuilds its preconditions from scratch.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.fixtures import (  # noqa: E402,F401
    accept_ticket,
    accepted_ticket,
    api,
    assess_bin,
    base_clock,
    base_full,
    base_pre,
    booked_delivery_order,
    claims_open_warehouse,
    filed_claim,
    issue_receipt,
    licensed_warehouse,
    new_agreement,
    new_bin,
    new_commercial_depositor,
    new_lender,
    new_producer,
    new_warehouse,
    perfected_lien,
    request_lien,
    set_clock,
    submitted_report,
    weighed_ticket,
)
