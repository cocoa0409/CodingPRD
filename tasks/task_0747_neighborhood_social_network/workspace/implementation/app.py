"""Flask entry point for the Neighborhood Social & Safety Network API.

Boot cleanly on every invocation — the test harness uses
`prd-bench-local-run --isolation per-test-server`, which kills and re-launches
the server via start.sh before every individual pytest test. The store is
in-memory and starts empty on boot; no seeding.
"""
from __future__ import annotations

import os

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

from errors import ApiError, InvalidRequest, NotFound
from response import error as error_response


def _register_blueprints(app: Flask) -> None:
    # Late-imported to keep startup fast and avoid circular imports.
    from routes.neighborhoods import bp as bp_neighborhoods
    from routes.residents import bp as bp_residents
    from routes.posts import bp as bp_posts
    from routes.marketplace import bp as bp_marketplace
    from routes.incidents import bp as bp_incidents
    from routes.civic_notices import bp as bp_civic
    from routes.flags import bp as bp_flags
    from routes.moderation import bp as bp_moderation
    from routes.businesses import bp as bp_businesses
    from routes.local_ads import bp as bp_local_ads
    from routes.groups import bp as bp_groups
    from routes.events import bp as bp_events
    from routes.clock_ep import bp as bp_clock

    for bp in (
        bp_neighborhoods, bp_residents, bp_posts, bp_marketplace,
        bp_incidents, bp_civic, bp_flags, bp_moderation, bp_businesses,
        bp_local_ads, bp_groups, bp_events, bp_clock,
    ):
        app.register_blueprint(bp)


def create_app() -> Flask:
    app = Flask(__name__)

    _register_blueprints(app)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(
            "ERR_NOT_FOUND",
            "Resource or route not found",
            404,
        )

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(
            "ERR_INVALID_REQUEST",
            "Method not allowed for this route",
            400,
        )

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(
            "ERR_INVALID_REQUEST",
            str(getattr(err, "description", "Bad request")),
            400,
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(err: HTTPException):
        # Fallback for anything werkzeug throws
        error_id = "ERR_INVALID_REQUEST"
        http_status = err.code or 400
        if http_status == 404:
            error_id = "ERR_NOT_FOUND"
        elif http_status == 401:
            error_id = "ERR_UNAUTHENTICATED"
        elif http_status == 403:
            error_id = "ERR_FORBIDDEN"
        return error_response(error_id, err.description or "", http_status)

    @app.errorhandler(Exception)
    def handle_unhandled(err: Exception):
        # Do not leak internals; return the closest generic 400.
        return error_response("ERR_INVALID_REQUEST", str(err), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Do not use the reloader/debug — this must be a plain foreground process.
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
