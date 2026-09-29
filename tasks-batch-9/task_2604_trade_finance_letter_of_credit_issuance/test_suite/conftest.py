"""Fixture bridge.

The fixtures themselves live in `test_helpers.fixtures` next to the builders they wrap;
re-exporting them here is what makes them visible to every test module in this directory.
Importing `test_helpers` also installs the error-id to HTTP-status map, so a test may
assert an error id without restating its status code.
"""

import test_helpers  # noqa: F401  (installs the error-id to HTTP-status map)
from test_helpers.fixtures import (  # noqa: F401
    clock,
    credit_awaiting_issue,
    drafted_credit,
    parties,
    standard_credit,
)
