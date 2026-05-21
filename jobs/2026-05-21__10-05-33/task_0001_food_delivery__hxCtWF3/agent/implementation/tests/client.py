"""Light-weight in-process API client used by the self-tests.

Uses Flask's test_client so the tests don't require booting a real server.
"""
import json
import sys
import os

# Allow `python tests/test_*.py` from the implementation directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.server import create_app, reset_state  # noqa: E402


class Client:
    def __init__(self):
        reset_state()
        self.app = create_app()
        self.flask_client = self.app.test_client()

    def request(self, method, path, body=None, role=None, user_id=None, headers=None):
        h = {"Content-Type": "application/json"}
        if role is not None:
            h["X-User-Role"] = role
        if user_id is not None:
            h["X-User-ID"] = user_id
        if headers:
            h.update(headers)
        data = None if body is None else json.dumps(body)
        resp = self.flask_client.open(path, method=method, headers=h, data=data)
        try:
            payload = resp.get_json()
        except Exception:
            payload = None
        return resp.status_code, payload

    def post(self, path, body=None, role=None, user_id=None, headers=None):
        return self.request("POST", path, body, role, user_id, headers)

    def get(self, path, role=None, user_id=None, headers=None):
        return self.request("GET", path, None, role, user_id, headers)

    def patch(self, path, body=None, role=None, user_id=None, headers=None):
        return self.request("PATCH", path, body, role, user_id, headers)


ADMIN = ("PlatformAdmin", "admin-op-1")
CS = ("CustomerService", "cs-op-1")


def admin_post(c, path, body=None):
    return c.post(path, body, role=ADMIN[0], user_id=ADMIN[1])
def admin_get(c, path):
    return c.get(path, role=ADMIN[0], user_id=ADMIN[1])
def admin_patch(c, path, body=None):
    return c.patch(path, body, role=ADMIN[0], user_id=ADMIN[1])
