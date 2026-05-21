"""HTTP client for self-tests. Wraps requests.Session with the required headers."""
import os
import requests

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:10010")


def hdrs(role, uid):
    return {"X-User-ID": uid, "X-User-Role": role, "Content-Type": "application/json"}


def get(path, *, role=None, uid=None, headers=None, **kwargs):
    if headers is None:
        headers = hdrs(role, uid) if role else {}
    return requests.get(BASE + path, headers=headers, **kwargs)


def post(path, *, json=None, role=None, uid=None, headers=None, **kwargs):
    if headers is None:
        headers = hdrs(role, uid) if role else {}
    return requests.post(BASE + path, json=json, headers=headers, **kwargs)


def patch(path, *, json=None, role=None, uid=None, headers=None, **kwargs):
    if headers is None:
        headers = hdrs(role, uid) if role else {}
    return requests.patch(BASE + path, json=json, headers=headers, **kwargs)


ADMIN_ID = "admin-1"
CS_ID = "cs-1"


def reset():
    r = post("/api/_admin/reset", role="PlatformAdmin", uid=ADMIN_ID, json={})
    assert r.status_code == 200, r.text
