"""Keg Pool Asset Recovery API -- application entry point.

Storage is in-memory only and starts completely empty on every boot: every
entity in this system is created through the API surface described in PRD 4.
"""
import os

from flask import Flask

import response
from errors import ApiError
from routes import floats, parties, pools, recovery, scans, service


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(parties.bp)
    app.register_blueprint(pools.bp)
    app.register_blueprint(scans.bp)
    app.register_blueprint(floats.bp)
    app.register_blueprint(service.bp)
    app.register_blueprint(recovery.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return response.error("ERR_INVALID_REQUEST",
                              "No such resource path.", 404)

    @app.errorhandler(405)
    def handle_bad_method(exc):
        return response.error("ERR_INVALID_REQUEST",
                              "That method is not allowed on this path.", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return response.error(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error")
        return response.error("ERR_INVALID_REQUEST", str(exc), 400)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
