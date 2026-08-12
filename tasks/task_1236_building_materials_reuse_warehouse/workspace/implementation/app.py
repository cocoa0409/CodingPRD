"""Building Materials Reuse Warehouse API — Flask entry point.

The store starts completely empty on every boot; all state is built by API
calls at runtime. The logical clock starts at exactly 2026-05-01T00:00:00Z.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import routes_core
    import routes_offers
    import routes_jobs
    import routes_store
    import routes_trade
    import routes_fleet

    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_offers.bp)
    app.register_blueprint(routes_jobs.bp)
    app.register_blueprint(routes_store.bp)
    app.register_blueprint(routes_trade.bp)
    app.register_blueprint(routes_fleet.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(
            ApiError("ERR_NOT_FOUND", 404, "The requested resource was not found")
        )

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(
            ApiError("ERR_INVALID_REQUEST", 405, "Method not allowed")
        )

    @app.errorhandler(500)
    def handle_500(e):
        return error_response(
            ApiError("ERR_INTERNAL", 500, "Internal server error")
        )

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
