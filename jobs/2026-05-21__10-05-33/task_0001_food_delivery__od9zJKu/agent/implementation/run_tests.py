"""Test runner. Discovers all tests/test_*.py and runs registered tests."""
from __future__ import annotations

import importlib
import os
import sys
import traceback

# Ensure the implementation root is on the path
sys.path.insert(0, os.path.dirname(__file__))


def main(argv):
    from tests._harness import _TESTS, run_all  # noqa
    test_dir = os.path.join(os.path.dirname(__file__), "tests")
    for fn in sorted(os.listdir(test_dir)):
        if fn.startswith("test_") and fn.endswith(".py"):
            modname = "tests." + fn[:-3]
            importlib.import_module(modname)
    filter_name = argv[1] if len(argv) > 1 else None
    return run_all(filter_name)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
