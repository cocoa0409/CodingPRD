"""Test harness: fresh app + helpers."""
from __future__ import annotations

import json
import sys
import traceback

from app.clock import clock
from app.main import create_app
from app.store import store


_TESTS: list[tuple[str, callable]] = []


def test(name: str):
    def wrap(fn):
        _TESTS.append((name, fn))
        return fn
    return wrap


def reset_world():
    store.reset()
    clock.reset()


def headers(role: str, user_id: str = "u1"):
    return {
        "X-User-ID": user_id,
        "X-User-Role": role,
        "Content-Type": "application/json",
    }


class Client:
    def __init__(self):
        self.app = create_app()
        self.c = self.app.test_client()

    def req(self, method: str, path: str, *, role: str, user_id: str = "u1", body=None, query=None):
        h = headers(role, user_id)
        if query:
            from urllib.parse import urlencode
            path = path + ("?" + urlencode(query))
        resp = self.c.open(path, method=method, json=body, headers=h)
        return resp.status_code, resp.get_json()

    def get(self, path, **kw): return self.req("GET", path, **kw)
    def post(self, path, **kw): return self.req("POST", path, **kw)
    def patch(self, path, **kw): return self.req("PATCH", path, **kw)


def expect(cond: bool, msg: str = ""):
    if not cond:
        raise AssertionError(msg or "expectation failed")


def expect_err(resp_tuple, error_id: str, http: int | None = None):
    status, body = resp_tuple
    if http is not None and status != http:
        raise AssertionError(f"expected HTTP {http}, got {status}: {body}")
    if not body or body.get("response_type") != "error":
        raise AssertionError(f"expected error response, got: status={status} body={body}")
    eid = body.get("data", {}).get("error_id")
    if eid != error_id:
        raise AssertionError(f"expected error_id={error_id}, got {eid}: {body}")


def expect_ok(resp_tuple, http: int | None = None):
    status, body = resp_tuple
    if http is not None and status != http:
        raise AssertionError(f"expected HTTP {http}, got {status}: {body}")
    if not body or body.get("response_type") == "error":
        raise AssertionError(f"expected success response, got: status={status} body={body}")
    return body["data"]


def run_all(filter_name: str | None = None) -> int:
    passed = 0
    failed = 0
    failures = []
    for name, fn in _TESTS:
        if filter_name and filter_name not in name:
            continue
        reset_world()
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception as e:
            failed += 1
            tb = traceback.format_exc()
            failures.append((name, tb))
            print(f"  FAIL  {name}: {e}")
    print()
    print(f"=== {passed} passed, {failed} failed ===")
    if failed:
        for name, tb in failures:
            print(f"\n--- {name} ---\n{tb}")
    return 0 if failed == 0 else 1


def discover_and_run():
    # Import all test modules so they register
    import importlib
    import os
    test_dir = os.path.dirname(__file__)
    for fn in sorted(os.listdir(test_dir)):
        if fn.startswith("test_") and fn.endswith(".py"):
            modname = "tests." + fn[:-3]
            importlib.import_module(modname)
    filter_name = sys.argv[1] if len(sys.argv) > 1 else None
    return run_all(filter_name)


if __name__ == "__main__":
    sys.exit(discover_and_run())
