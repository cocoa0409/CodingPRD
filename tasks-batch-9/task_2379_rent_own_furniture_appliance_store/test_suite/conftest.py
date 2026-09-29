"""Suite-wide wiring.

The server is relaunched against an empty database before every individual test,
so nothing here is shared state: the fixtures below simply re-expose the workflow
builders from ``test_helpers`` so each test can construct the story it needs from
scratch through the public API.
"""

from __future__ import annotations

import os
import sys

_TASK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TASK_ROOT not in sys.path:
    sys.path.insert(0, _TASK_ROOT)

from test_helpers.fixtures import (  # noqa: E402,F401  (re-exported as fixtures)
    api,
    tx_defaulted,
    tx_delinquent,
    tx_delivered,
    tx_floor,
    tx_signed,
    world,
)
