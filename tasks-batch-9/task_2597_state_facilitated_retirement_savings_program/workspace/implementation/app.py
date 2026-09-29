"""State-facilitated retirement savings programme -- REST API entry point.

Every request is served from process-local memory; nothing is persisted and
nothing is seeded.  A fresh process is therefore a fresh, empty programme whose
logical clock reads exactly 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
import routes_accounts
import routes_config
import routes_employers
import routes_enforcement
import routes_ops
import routes_participants
import routes_portability
import routes_remittances

BLUEPRINTS = (
    routes_config.bp,
    routes_employers.bp,
    routes_participants.bp,
    routes_accounts.bp,
    routes_remittances.bp,
    routes_enforcement.bp,
    routes_portability.bp,
    routes_ops.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def _not_found(_err):
        return error_response(ApiError("ERR_NOT_FOUND", "no such route"))

    @app.errorhandler(405)
    def _method_not_allowed(_err):
        return error_response(
            ApiError("ERR_METHOD_NOT_ALLOWED", "that method is not allowed here"))

    @app.errorhandler(Exception)
    def _internal(err):
        if isinstance(err, ApiError):
            return error_response(err)
        app.logger.exception("unhandled error")
        return error_response(ApiError("ERR_INTERNAL", "internal server error"))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
