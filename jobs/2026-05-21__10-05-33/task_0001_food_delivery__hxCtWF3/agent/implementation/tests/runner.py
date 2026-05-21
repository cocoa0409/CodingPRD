"""Tiny test runner. Each test module exposes a `run(suite)` that registers checks.

The runner emits pass/fail per test and a final summary. Returns non-zero exit code on any failure.
"""
import importlib
import sys
import traceback


class Suite:
    def __init__(self):
        self.results = []  # list[(name, ok, msg)]

    def case(self, name, fn):
        try:
            fn()
            self.results.append((name, True, ""))
            print(f"  PASS  {name}")
        except AssertionError as e:
            self.results.append((name, False, str(e)))
            print(f"  FAIL  {name}: {e}")
        except Exception:
            tb = traceback.format_exc()
            self.results.append((name, False, tb))
            print(f"  ERROR {name}:\n{tb}")


def main(argv):
    suite = Suite()
    modules = argv[1:] or [
        "tests.test_envelope",
        "tests.test_auth",
        "tests.test_restaurants",
        "tests.test_menu_items",
        "tests.test_customers",
        "tests.test_riders",
        "tests.test_formulas",
        "tests.test_orders",
        "tests.test_dispatch",
        "tests.test_delivery",
        "tests.test_returns",
        "tests.test_work_orders",
        "tests.test_fines",
        "tests.test_clock",
        "tests.test_validation_order",
        "tests.test_concurrency",
        "tests.test_pagination",
        "tests.test_coverage_gaps",
    ]
    for m in modules:
        print(f"\n== {m} ==")
        mod = importlib.import_module(m)
        mod.run(suite)
    total = len(suite.results)
    fails = sum(1 for _, ok, _ in suite.results if not ok)
    print(f"\n{'PASS' if fails == 0 else 'FAIL'}: {total - fails}/{total} passed, {fails} failed")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
