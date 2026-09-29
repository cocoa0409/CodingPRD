"""
Test-suite wiring.

The task root is placed on ``sys.path`` so ``test_helpers`` imports the same way no
matter which directory pytest was started from, and the shared fixtures are re-exported
here so every test file can request them by name.
"""

import sys
from pathlib import Path

TASK_ROOT = str(Path(__file__).resolve().parent.parent)
if TASK_ROOT not in sys.path:
    sys.path.insert(0, TASK_ROOT)

from test_helpers.fixtures import (  # noqa: E402,F401
    admin,
    api,
    approved,
    assessed,
    bound,
    closed,
    enrolled,
    implementing,
    lender,
    obligated,
    planned,
    quoted,
    registry,
    reviewer,
    reviewer_beta,
    reviewer_gamma,
    sited,
)
