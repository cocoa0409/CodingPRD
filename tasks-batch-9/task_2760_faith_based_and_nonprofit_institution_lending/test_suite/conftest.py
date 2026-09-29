"""
Suite-wide pytest configuration.

The runner puts the task root on PYTHONPATH and owns API_BASE_URL, so the
helper package is importable as ``test_helpers``. Re-exporting the fixture
module here makes every composite fixture available to all test modules
without per-module imports.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers.fixtures import (  # noqa: E402,F401
    api,
    chain_approved,
    chain_assigned,
    chain_authorized,
    chain_loan,
    chain_periods,
    chain_underwriting,
    generic_api,
    institution,
)
