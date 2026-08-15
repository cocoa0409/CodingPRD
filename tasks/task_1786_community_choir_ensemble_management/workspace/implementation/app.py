"""Flask entry point: auth pipeline (PRD 2.8 tiers 1-2), route dispatch,
envelope error handling.  The store starts empty on every boot."""

import os
import re

from flask import Flask, request

import store
from envelope import error_response
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False

DECLARED_ROLES = ("President", "Treasurer", "ChoirDirector", "Librarian", "Member")

import routes_a  # noqa: E402,F401
import routes_b  # noqa: E402,F401
import routes_c  # noqa: E402,F401
import routes_d  # noqa: E402,F401
import routes_e  # noqa: E402,F401
from routes_common import ROUTES  # noqa: E402

_PARAM_RE = re.compile(r"\{([a-z_]+)\}")


def _authenticate(spec):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in DECLARED_ROLES:
        return None, None, error_response(
            "ERR_UNAUTHENTICATED",
            "X-User-Role and X-User-ID headers are required and the role must be declared",
            401,
        )
    if role not in spec["roles"]:
        return None, None, error_response(
            "ERR_FORBIDDEN", "the acting role may not call this endpoint", 403,
        )
    return role, uid, None


def _make_view(spec):
    def view(**path_params):
        role, uid, err = _authenticate(spec)
        if err is not None:
            return err
        body = {}
        if request.method in ("POST", "PATCH"):
            try:
                body = request.get_json(silent=True, force=False)
            except Exception:
                body = None
            if body is None:
                body = {}
            if not isinstance(body, dict):
                return error_response(
                    "ERR_INVALID_REQUEST", "request body must be a JSON object", 400,
                )
        store.begin_request()
        ctx = {"role": role, "uid": uid, "body": body, "args": request.args, "path": path_params}
        try:
            return spec["fn"](ctx)
        except ApiError as exc:
            return error_response(exc.error_id, exc.message, exc.http_status)
    return view


for _spec in ROUTES:
    _rule = _PARAM_RE.sub(lambda m: "<" + m.group(1) + ">", _spec["path"])
    app.add_url_rule(
        _rule,
        endpoint="%s:%s" % (_spec["method"], _spec["path"]),
        view_func=_make_view(_spec),
        methods=[_spec["method"]],
    )


@app.errorhandler(404)
def not_found(_err):
    return error_response("ERR_NOT_FOUND", "the resource does not exist", 404)


@app.errorhandler(405)
def method_not_allowed(_err):
    return error_response("ERR_NOT_FOUND", "the resource does not exist", 404)


@app.errorhandler(Exception)
def internal_error(exc):
    return error_response("ERR_INVALID_REQUEST", "unhandled error: %s" % exc, 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
