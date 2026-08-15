"""Flask entry point: app factory, error handlers, blueprint registration."""

import os

from flask import Flask

from httpkit import ApiError, respond_error

import routes_aircraft
import routes_cards
import routes_invoices
import routes_members
import routes_ops
import routes_programs
import routes_refunds
import routes_trips


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (routes_programs, routes_members, routes_cards,
                   routes_aircraft, routes_trips, routes_invoices,
                   routes_refunds, routes_ops):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return respond_error(err)

    @app.errorhandler(404)
    def handle_404(err):
        return respond_error(ApiError(
            "ERR_NOT_FOUND", 404, "Path-referenced resource does not exist"))

    @app.errorhandler(405)
    def handle_405(err):
        return respond_error(ApiError(
            "ERR_NOT_FOUND", 404, "Path-referenced resource does not exist"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return respond_error(ApiError("ERR_INTERNAL", 500, str(err)))

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
