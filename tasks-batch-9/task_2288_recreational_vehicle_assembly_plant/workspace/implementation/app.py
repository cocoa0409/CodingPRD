"""RV assembly plant API — Flask entry point.

The store is in memory and starts empty on every boot: nothing is seeded,
preloaded or hardcoded. Every row a caller needs is created through the API.
"""
import os

import response
from errors import ApiError
from flask import Flask
from routes import builds, master, ops, orders, quality, recalls, supply, warranty


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:  # keep the declared field order in responses where Flask allows it
        app.json.sort_keys = False
    except Exception:
        app.config["JSON_SORT_KEYS"] = False

    for blueprint in (
        master.bp,
        supply.bp,
        ops.bp,
        orders.bp,
        builds.bp,
        quality.bp,
        warranty.bp,
        recalls.bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return response.error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(404)
    def handle_404(error):
        return response.error_response(
            "ERR_INVALID_REQUEST", "No route matches the requested path.", 404
        )

    @app.errorhandler(405)
    def handle_405(error):
        return response.error_response(
            "ERR_INVALID_REQUEST", "The HTTP method is not allowed on this path.", 405
        )

    @app.errorhandler(400)
    def handle_400(error):
        return response.error_response("ERR_INVALID_REQUEST", "The request is malformed.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        if isinstance(error, ApiError):
            return handle_api_error(error)
        app.logger.exception("unhandled error")
        return response.error_response(
            "ERR_INVALID_REQUEST", "Unexpected server error: {}".format(error), 500
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
