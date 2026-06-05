"""HTTP client for the National Park Reservations API.

Wraps `requests`, prefixes the configured base URL, sends the two identity
headers (``X-User-ID`` and ``X-User-Role``) the API requires on non-public
endpoints, and never raises on 4xx/5xx so tests can assert on the response.

The base URL comes from the ``API_BASE_URL`` environment variable supplied by
the runner.
"""
import os

import requests


def headers_for(role, user_id=None, idempotency_key=None):
    """Build request headers. `role` is the X-User-Role; `user_id` the
    X-User-ID (the acting Account.id for visitor/ranger/park_admin, or any
    opaque operator id for finance/system)."""
    h = {}
    if role is not None:
        h["X-User-Role"] = role
    if user_id is not None:
        h["X-User-ID"] = str(user_id)
    if idempotency_key is not None:
        h["Idempotency-Key"] = idempotency_key
    return h


class ApiClient:
    def __init__(self, base_url=None):
        self.base_url = (base_url or os.environ.get("API_BASE_URL", "http://localhost:10000")).rstrip("/")

    def request(self, method, path, role=None, user_id=None, json=None,
                params=None, idempotency_key=None):
        url = self.base_url + path
        h = headers_for(role, user_id, idempotency_key)
        return requests.request(method, url, headers=h, json=json, params=params, timeout=30)

    # Convenience verbs ------------------------------------------------------
    def get(self, path, role=None, user_id=None, params=None):
        return self.request("GET", path, role=role, user_id=user_id, params=params)

    def post(self, path, role=None, user_id=None, json=None, idempotency_key=None):
        return self.request("POST", path, role=role, user_id=user_id, json=json,
                            idempotency_key=idempotency_key)
