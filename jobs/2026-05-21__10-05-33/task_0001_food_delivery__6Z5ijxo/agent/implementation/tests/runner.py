"""Self-test runner: discovers test functions, runs them against a live server."""
import inspect
import sys
import traceback
import importlib
from . import client

TEST_MODULES = [
    "tests.test_envelope_auth",
    "tests.test_clock",
    "tests.test_restaurants",
    "tests.test_menu_items",
    "tests.test_customers",
    "tests.test_riders",
    "tests.test_orders_place",
    "tests.test_orders_flow",
    "tests.test_assignments",
    "tests.test_delivery_cascade",
    "tests.test_route_merge",
    "tests.test_returns",
    "tests.test_workorders",
    "tests.test_fines",
    "tests.test_occ_and_pagination",
    "tests.test_pricing_units",
    "tests.test_coverage_gaps",
]


def main():
    passed = 0
    failed = []
    for mod_name in TEST_MODULES:
        mod = importlib.import_module(mod_name)
        funcs = [(n, f) for n, f in inspect.getmembers(mod, inspect.isfunction)
                 if n.startswith("test_")]
        for name, fn in funcs:
            try:
                client.reset()
                fn()
                print(f"  PASS  {mod_name}.{name}")
                passed += 1
            except AssertionError as e:
                msg = str(e) or "assertion"
                print(f"  FAIL  {mod_name}.{name}: {msg}")
                traceback.print_exc(file=sys.stdout)
                failed.append((mod_name, name, msg))
            except Exception as e:
                print(f"  ERR   {mod_name}.{name}: {e}")
                traceback.print_exc(file=sys.stdout)
                failed.append((mod_name, name, repr(e)))
    print(f"\n=== {passed} passed, {len(failed)} failed ===")
    if failed:
        for m, n, msg in failed:
            print(f"  - {m}.{n}: {msg}")
        sys.exit(1)


if __name__ == "__main__":
    main()
