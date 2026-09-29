"""Make the sibling ``test_helpers`` package importable when pytest is run by hand.

The harness already places the task root on ``PYTHONPATH``; this shim only keeps
a direct ``pytest test_suite`` invocation working from any working directory.
"""

import sys
from pathlib import Path

TASK_ROOT = Path(__file__).resolve().parent.parent
if str(TASK_ROOT) not in sys.path:
    sys.path.insert(0, str(TASK_ROOT))
