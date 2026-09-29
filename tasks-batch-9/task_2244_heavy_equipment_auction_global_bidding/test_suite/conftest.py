"""Makes the shared helper package importable from every test module.

The helper package lives next to this suite rather than inside it, so the task root has
to be on the import path before ``import test_helpers`` can resolve.
"""
import sys
from pathlib import Path

TASK_ROOT = Path(__file__).resolve().parent.parent
if str(TASK_ROOT) not in sys.path:
    sys.path.insert(0, str(TASK_ROOT))
