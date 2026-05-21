"""Self-test harness.

The harness uses Flask's in-process test client, so each test runs against
a fresh in-memory store. Tests register themselves via the @test()
decorator and are discoverable by name.
"""

import json
import os
import sys
import traceback

# Ensure parent dir is on the path so `import app` works when invoked from
# different working directories.
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(THIS_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

import state  # noqa: E402
import app as app_module  # noqa: E402


_TESTS = []  # list of (name, fn)


def test(name):
    def deco(fn):
        _TESTS.append((name, fn))
        return fn
    return deco


def fresh_client():
    """Reset the global store and return a Flask test client."""
    state.STORE.reset()
    return app_module.create_app().test_client()


def admin_headers(uid="admin1"):
    return {"X-User-ID": uid, "X-User-Role": "PlatformAdmin"}


def cs_headers(uid="cs1"):
    return {"X-User-ID": uid, "X-User-Role": "CustomerService"}


def cust_headers(uid):
    return {"X-User-ID": uid, "X-User-Role": "Customer"}


def rest_headers(uid):
    return {"X-User-ID": uid, "X-User-Role": "Restaurant"}


def rider_headers(uid):
    return {"X-User-ID": uid, "X-User-Role": "Rider"}


def jpost(client, path, body=None, headers=None):
    return client.post(
        path,
        data=json.dumps(body or {}),
        content_type="application/json",
        headers=headers or {},
    )


def jpatch(client, path, body=None, headers=None):
    return client.patch(
        path,
        data=json.dumps(body or {}),
        content_type="application/json",
        headers=headers or {},
    )


def jget(client, path, headers=None):
    return client.get(path, headers=headers or {})


def body_of(resp):
    return json.loads(resp.get_data(as_text=True))


def assert_eq(actual, expected, label=""):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_in(haystack, needle, label=""):
    if needle not in haystack:
        raise AssertionError(f"{label}: {needle!r} not in {haystack!r}")


def assert_err(resp, status, error_id):
    body = body_of(resp)
    assert_eq(resp.status_code, status, f"status code for {error_id}")
    assert_eq(body.get("response_type"), "error", "response_type is error")
    assert_eq(body["data"].get("error_id"), error_id, "error_id")


def run_all(filter_substr=None):
    passed = 0
    failed = 0
    errors = []
    for name, fn in _TESTS:
        if filter_substr and filter_substr not in name:
            continue
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except AssertionError as ex:
            failed += 1
            errors.append((name, str(ex)))
            print(f"  FAIL  {name}: {ex}")
        except Exception as ex:
            failed += 1
            tb = traceback.format_exc()
            errors.append((name, tb))
            print(f"  ERR   {name}: {ex}\n{tb}")
    total = passed + failed
    print(f"\n{passed}/{total} passed.")
    return failed == 0


# Allow importing all test modules so that decorators register tests.
def _load_test_modules():
    here = os.path.dirname(__file__)
    for entry in sorted(os.listdir(here)):
        if entry.startswith("test_") and entry.endswith(".py"):
            mod_name = "tests." + entry[:-3]
            __import__(mod_name)


if __name__ == "__main__":
    # When invoked as __main__, alias this module so test modules importing
    # `tests.harness` get the same _TESTS registry.
    sys.modules.setdefault("tests.harness", sys.modules["__main__"])
    _load_test_modules()
    flt = sys.argv[1] if len(sys.argv) > 1 else None
    ok = run_all(flt)
    sys.exit(0 if ok else 1)
