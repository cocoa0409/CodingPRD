"""Flask entry point: route registration, the auth ladder (rungs 1-2), the
per-request version-bump scope, and the error envelope."""

import os
import threading

from flask import Flask, request

import db
import middleware
import response
from constants import HEADER_USER_ID, HEADER_USER_ROLE
from errors import ApiError

_LOCK = threading.RLock()


def _read_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        return body
    return {}


def _make_view(spec):
    def view(**path_params):
        with _LOCK:
            db.begin_request()
            body = _read_body() if spec.method in ("POST", "PATCH", "PUT", "DELETE") else {}
            role = request.headers.get(HEADER_USER_ROLE)
            user_id = request.headers.get(HEADER_USER_ID)
            # Ladder rung 1 (authentication) then rung 2 (authorization),
            # before any handler logic.
            middleware.authenticate(role, user_id)
            middleware.authorize(spec, role)
            ctx = middleware.Ctx(spec, role, user_id, body, request.args, path_params)
            return spec.handler(ctx)

    view.__name__ = spec.name
    return view


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import routes  # noqa: F401 - importing registers every endpoint

    for spec in middleware.ENDPOINTS:
        app.add_url_rule(
            spec.flask_rule,
            endpoint="%s %s" % (spec.method, spec.template),
            view_func=_make_view(spec),
            methods=[spec.method],
        )

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return response.error_response("ERR_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return response.error_response("ERR_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return response.error_response("ERR_INVALID_REQUEST", "Unhandled server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
