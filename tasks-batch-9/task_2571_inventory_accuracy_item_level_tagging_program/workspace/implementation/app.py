"""Inventory Accuracy & Item-Level Tagging Program — Flask application factory.

Every entity lives in a plain in-memory dict (see db.py) that starts EMPTY on
every boot: the harness relaunches this process before each test and creates all
of its own fixtures through the declared endpoints. Nothing is ever seeded here.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response

import routes_counts
import routes_investigations
import routes_physical
import routes_positions
import routes_reference
import routes_shrink
import routes_tags


BLUEPRINTS = (
    routes_reference.bp,
    routes_positions.bp,
    routes_tags.bp,
    routes_counts.bp,
    routes_investigations.bp,
    routes_shrink.bp,
    routes_physical.bp,
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
        return error_response(ApiError("ERR_INVALID_REQUEST", "no such route"))

    @app.errorhandler(405)
    def _method_not_allowed(_err):
        return error_response(ApiError("ERR_INVALID_REQUEST", "method not allowed"))

    @app.errorhandler(Exception)
    def _unhandled(err):
        if isinstance(err, ApiError):
            return error_response(err)
        app.logger.exception("unhandled error: %s", err)
        return error_response(ApiError("ERR_INVALID_REQUEST", str(err)))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
