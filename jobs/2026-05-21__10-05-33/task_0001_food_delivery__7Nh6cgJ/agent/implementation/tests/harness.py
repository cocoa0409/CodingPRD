"""Test harness — boots the Flask app, exercises HTTP endpoints via the test client."""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any

sys.path.insert(0, "..")
sys.path.insert(0, ".")

from server import create_app  # noqa: E402
from store import STORE  # noqa: E402
from clock import CLOCK  # noqa: E402


class TestClient:
    def __init__(self):
        self.app = create_app()
        self.client = self.app.test_client()

    def reset(self):
        STORE.reset()
        # Reset clock offset
        with CLOCK._lock:  # type: ignore[attr-defined]
            CLOCK._offset_seconds = 0.0

    def request(self, method: str, path: str, *, role: str | None = None,
                user_id: str | None = None, body: Any = None) -> tuple[int, dict]:
        headers = {}
        if user_id is not None:
            headers["X-User-ID"] = user_id
        if role is not None:
            headers["X-User-Role"] = role
        kwargs = {"headers": headers}
        if body is not None:
            kwargs["data"] = json.dumps(body)
            kwargs["content_type"] = "application/json"
        resp = self.client.open(path, method=method, **kwargs)
        try:
            data = json.loads(resp.data.decode("utf-8") or "{}")
        except Exception:
            data = {"raw": resp.data.decode("utf-8", errors="replace")}
        return resp.status_code, data


class TestRunner:
    def __init__(self):
        self.results: list[tuple[str, bool, str]] = []

    def run(self, name: str, fn) -> None:
        try:
            fn()
            self.results.append((name, True, ""))
        except AssertionError as e:
            tb = traceback.format_exc(limit=3)
            self.results.append((name, False, f"AssertionError: {e}\n{tb}"))
        except Exception as e:
            tb = traceback.format_exc(limit=5)
            self.results.append((name, False, f"{type(e).__name__}: {e}\n{tb}"))

    def report(self) -> bool:
        passed = sum(1 for _, ok, _ in self.results if ok)
        total = len(self.results)
        print(f"\n=== TEST RESULTS: {passed}/{total} passed ===")
        for name, ok, err in self.results:
            marker = "PASS" if ok else "FAIL"
            print(f"  [{marker}] {name}")
            if not ok:
                print(f"      {err}")
        return passed == total
