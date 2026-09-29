"""Beverage Program and Wine List Management API.

Entry point: registers the route blueprints and the error handlers. The store is
in-memory and starts completely empty on every boot; nothing is ever seeded.
"""
import os

from flask import Flask

from core import ApiError, respond_error
import routes_master
import routes_alloc
import routes_lists
import routes_ops
import routes_events
import routes_reports


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(routes_master.bp)
    app.register_blueprint(routes_alloc.bp)
    app.register_blueprint(routes_lists.bp)
    app.register_blueprint(routes_ops.bp)
    app.register_blueprint(routes_events.bp)
    app.register_blueprint(routes_reports.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return respond_error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return respond_error("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return respond_error("ERR_INVALID_REQUEST", "No such route.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return respond_error("ERR_INVALID_REQUEST", "Method not allowed on this route.", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return respond_error(exc.error_id, exc.message, exc.http_status)
        return respond_error("ERR_INVALID_REQUEST", "Unhandled server error: %s" % exc, 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
        debug=False,
        use_reloader=False,
    )
