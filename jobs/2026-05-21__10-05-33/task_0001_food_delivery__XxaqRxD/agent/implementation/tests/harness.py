"""Minimal self-test harness.

Each test registers via @test(category). The runner spins up a fresh Flask app
per test, then invokes via Flask's test client. We deliberately avoid pytest /
unittest dependencies so the harness runs against the actual implementation
with zero extra moving parts.
"""
from __future__ import annotations

import json
import sys
import time
import traceback
from dataclasses import dataclass, field
from typing import Callable

from server.app import create_app


@dataclass
class Test:
    category: str
    name: str
    fn: Callable


_tests: list[Test] = []


def test(category: str):
    def deco(fn):
        _tests.append(Test(category=category, name=fn.__name__, fn=fn))
        return fn

    return deco


@dataclass
class Result:
    name: str
    category: str
    passed: bool
    err: str = ""


class TestApp:
    """Wraps a fresh Flask app + test client and provides helpers."""

    def __init__(self):
        self.app = create_app()
        self.client = self.app.test_client()
        self.store = self.app.config["STORE"]

    def request(self, method, path, *, user_id=None, role=None, json_body=None, params=None):
        headers = {}
        if user_id is not None:
            headers["X-User-ID"] = user_id
        if role is not None:
            headers["X-User-Role"] = role
        if json_body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(json_body)
        else:
            data = None
        resp = self.client.open(
            path, method=method, headers=headers, data=data, query_string=params
        )
        try:
            body = json.loads(resp.data.decode("utf-8")) if resp.data else None
        except Exception:
            body = {"_raw": resp.data.decode("utf-8", "replace")}
        return resp.status_code, body

    def admin(self, method, path, **kw):
        return self.request(method, path, user_id="admin1", role="PlatformAdmin", **kw)

    def cs(self, method, path, **kw):
        return self.request(method, path, user_id="cs1", role="CustomerService", **kw)


def expect(cond, msg=""):
    if not cond:
        raise AssertionError(msg or "expectation failed")


def expect_eq(a, b, msg=""):
    if a != b:
        raise AssertionError(f"{msg}: expected {b!r}, got {a!r}")


def expect_err(resp_tuple, error_id: str, http: int | None = None):
    code, body = resp_tuple
    if body is None:
        raise AssertionError(f"expected error {error_id}, got empty body (status={code})")
    got_id = body.get("data", {}).get("error_id")
    if got_id != error_id:
        raise AssertionError(
            f"expected error_id={error_id}, got {got_id} (status={code}, body={body})"
        )
    if http is not None and code != http:
        raise AssertionError(f"expected http {http}, got {code} for error {error_id}")


def run_all() -> int:
    results: list[Result] = []
    by_cat: dict[str, list[Result]] = {}
    started = time.time()
    for t in _tests:
        try:
            app = TestApp()
            t.fn(app)
            results.append(Result(t.name, t.category, True))
        except Exception as e:
            err = "".join(traceback.format_exception(e))
            results.append(Result(t.name, t.category, False, err))
        by_cat.setdefault(t.category, []).append(results[-1])
    elapsed = time.time() - started

    total = len(results)
    failed = [r for r in results if not r.passed]
    for cat, rs in by_cat.items():
        pn = sum(1 for r in rs if r.passed)
        print(f"== {cat}: {pn}/{len(rs)} passed ==")
        for r in rs:
            mark = "PASS" if r.passed else "FAIL"
            print(f"  [{mark}] {r.name}")
            if not r.passed:
                print(r.err)
    print(f"\nTotal {total - len(failed)}/{total} passed in {elapsed:.2f}s")
    return 0 if not failed else 1
