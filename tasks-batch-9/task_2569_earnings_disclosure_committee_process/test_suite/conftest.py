"""Shared pytest fixtures for the Earnings Disclosure Committee Process suite.

The fixtures themselves live in ``test_helpers.fixtures``; importing them here
registers them for every test module in this directory. The error catalogue is
registered with the framework's validator on import, so ``validate_error``
cross-checks the HTTP status of any identifier a test names.
"""

from test_helpers.api_errors import register_error_status_map
from test_helpers.fixtures import (  # noqa: F401
    abandoned_cycle,
    api,
    certification_open_cycle,
    close_open_cycle,
    committee,
    draft_call_script,
    draft_committee,
    draft_correction_cycle,
    draft_periodic_filing,
    filed_cycle,
    filing_ready_cycle,
    planning_cycle,
    review_open_cycle,
)

register_error_status_map()
