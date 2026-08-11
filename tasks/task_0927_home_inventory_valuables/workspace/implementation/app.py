"""Flask entry point: route registration, the H2 posture hook, the ladder and
the error envelope."""

import os

from flask import Flask, request

import derive
import envelope
import ladder
import registry
import store
from constants import HEADER_USER_ID, HEADER_USER_ROLE
from errors import ApiError


def _read_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        return body
    return {}


def _make_view(spec):
    def view(**path_params):
        store.begin_request()
        body = _read_body() if spec.method in ("POST", "PATCH", "PUT", "DELETE") else {}
        if spec.template.startswith("/vault"):
            # PRD 2.7 hook H2 runs before ladder rung 1 is considered.
            derive.hook_h2(ladder.reachable_households(spec, path_params, body, request.args))
        ctx = registry.Ctx(
            spec,
            request.headers.get(HEADER_USER_ROLE),
            request.headers.get(HEADER_USER_ID),
            body,
            request.args,
            path_params,
        )
        ladder.run_ladder(ctx)
        return spec.handler(ctx)

    view.__name__ = spec.name
    return view


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import routes  # noqa: F401  - importing registers every endpoint

    for spec in registry.ENDPOINTS:
        app.add_url_rule(
            spec.flask_rule,
            endpoint="%s %s" % (spec.method, spec.template),
            view_func=_make_view(spec),
            methods=[spec.method],
        )

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return envelope.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return envelope.error_response("ERR_REFERENCE_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def _not_allowed(_exc):
        return envelope.error_response("ERR_REFERENCE_NOT_FOUND", "Method not allowed.", 404)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
