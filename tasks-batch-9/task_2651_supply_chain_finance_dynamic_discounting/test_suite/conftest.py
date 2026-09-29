"""pytest configuration for the supply-chain-finance / dynamic-discounting suite.

The task root is put on ``sys.path`` so ``test_helpers`` imports as a package,
and the fixtures declared in ``test_helpers.fixtures`` are re-exported here so
every test module can request them by name.

The harness restarts the API server before each individual test, so every test
below starts against an empty database and builds all of its own state through
the public API.
"""

import os
import sys

_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers.fixtures import (  # noqa: E402,F401
    accepted_offer,
    api,
    base_program,
    clock_at_default,
    deployed_payment,
    eligible_invoice,
    named_offer,
    ops_headers,
    reserved_payment,
)
