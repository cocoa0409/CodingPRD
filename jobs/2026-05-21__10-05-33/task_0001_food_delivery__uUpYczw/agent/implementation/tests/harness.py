"""Tiny test harness — each test is a function; pass/fail is reported per test.

The harness uses Flask's in-process test client for speed. Every test creates
a fresh app instance, so state never bleeds across tests.
"""
from __future__ import annotations

import json
import sys
import traceback
from typing import Any, Callable

# Make project importable regardless of cwd.
import os, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app import create_app


class Ctx:
    """A fresh app + helpers wrapped together."""

    def __init__(self):
        self.app = create_app()
        self.client = self.app.test_client()

    # --------------------------------------------------------------
    # Low-level
    # --------------------------------------------------------------
    def request(self, method: str, path: str, *, role: str | None = None,
                user_id: str | None = None, json_body: Any | None = None,
                query: dict | None = None) -> tuple[int, dict]:
        headers = {}
        if role is not None:
            headers["X-User-Role"] = role
        if user_id is not None:
            headers["X-User-ID"] = user_id
        kwargs: dict[str, Any] = {"headers": headers}
        if json_body is not None:
            kwargs["data"] = json.dumps(json_body)
            kwargs["content_type"] = "application/json"
        if query:
            kwargs["query_string"] = query
        r = self.client.open(path, method=method, **kwargs)
        try:
            body = json.loads(r.data.decode())
        except Exception:
            body = {"raw": r.data.decode()}
        return r.status_code, body

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, **kw):
        return self.request("POST", path, **kw)

    def patch(self, path, **kw):
        return self.request("PATCH", path, **kw)

    # --------------------------------------------------------------
    # Fixtures
    # --------------------------------------------------------------
    def admin(self, user_id: str = "admin-1"):
        return {"user_id": user_id, "role": "PlatformAdmin"}

    def cs(self, user_id: str = "cs-1"):
        return {"user_id": user_id, "role": "CustomerService"}

    def register_restaurant(self, *, name="R1", address="Addr", lat=40.0, lng=-74.0,
                             commission_rate_override=None) -> dict:
        body = {"name": name, "address": address, "lat": lat, "lng": lng}
        if commission_rate_override is not None:
            body["commission_rate_override"] = commission_rate_override
        s, r = self.post("/api/restaurants", role="PlatformAdmin", user_id="admin", json_body=body)
        assert s == 201, r
        return r["data"]

    def approve_restaurant(self, rid):
        s, r = self.post(f"/api/restaurants/{rid}/approve", role="PlatformAdmin", user_id="admin")
        assert s == 200, r
        return r["data"]

    def make_active_restaurant(self, **kwargs):
        rec = self.register_restaurant(**kwargs)
        return self.approve_restaurant(rec["id"])

    def add_menu_item(self, rid, *, name="Dish", price_cents=500, is_listed=True):
        s, r = self.post(f"/api/restaurants/{rid}/menu-items",
                          role="Restaurant", user_id=rid,
                          json_body={"name": name, "price_cents": price_cents, "is_listed": is_listed})
        assert s == 201, r
        return r["data"]

    def register_rider(self, *, name="Rider", phone=None):
        phone = phone or f"phone-{name}-{id(name)}"
        s, r = self.post("/api/riders", role="PlatformAdmin", user_id="admin",
                          json_body={"name": name, "phone": phone})
        assert s == 201, r
        return r["data"]

    def register_customer(self, *, name="Cust", phone=None,
                            address="Home", lat=40.05, lng=-74.05):
        phone = phone or f"cphone-{id(name)}"
        s, r = self.post("/api/customers", role="PlatformAdmin", user_id="admin",
                          json_body={"name": name, "phone": phone, "address": address,
                                       "lat": lat, "lng": lng})
        assert s == 201, r
        return r["data"]

    def place_order(self, *, customer, restaurant, items):
        body = {
            "customer_id": customer["id"],
            "restaurant_id": restaurant["id"],
            "items": items,
        }
        s, r = self.post("/api/orders", role="Customer", user_id=customer["id"], json_body=body)
        return s, r

    def go_online(self, rider):
        s, r = self.post(f"/api/riders/{rider['id']}/go-online", role="Rider", user_id=rider["id"])
        assert s == 200, r
        return r["data"]

    def clock_advance(self, seconds: int | float):
        s, r = self.post("/api/_clock/advance", role="PlatformAdmin", user_id="admin",
                          json_body={"seconds": seconds})
        assert s == 200, r
        return r["data"]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


_TESTS: list[tuple[str, Callable[[Ctx], None]]] = []


def test(name: str):
    """Decorator that registers a test function under a human-readable name."""
    def deco(fn):
        _TESTS.append((name, fn))
        return fn
    return deco


def run_all(filter_substr: str | None = None) -> int:
    passed = 0
    failed: list[tuple[str, str]] = []
    selected = _TESTS if not filter_substr else [t for t in _TESTS if filter_substr in t[0]]
    for name, fn in selected:
        ctx = Ctx()
        try:
            fn(ctx)
            passed += 1
            print(f"PASS  {name}")
        except AssertionError as e:
            failed.append((name, f"assertion: {e}"))
            print(f"FAIL  {name}\n      {e}")
        except Exception as e:
            tb = traceback.format_exc()
            failed.append((name, f"error: {e}\n{tb}"))
            print(f"ERROR {name}\n      {e}")
            print(tb)
    print(f"\n{passed} passed, {len(failed)} failed / {len(selected)} total")
    return 0 if not failed else 1
