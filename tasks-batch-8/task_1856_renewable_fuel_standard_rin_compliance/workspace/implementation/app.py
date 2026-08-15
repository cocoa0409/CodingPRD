"""Entry point: app factory, error handlers, route registration."""
import os
from flask import Flask

from errors import ApiError, not_found, invalid_request
from response import error_response

from routes import clock, accounts, years, vendors, lots, trades, batches, reports, engagements, state_programs, quotes


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(clock.bp)
    app.register_blueprint(accounts.bp)
    app.register_blueprint(years.bp)
    app.register_blueprint(vendors.bp)
    app.register_blueprint(lots.bp)
    app.register_blueprint(trades.bp)
    app.register_blueprint(batches.bp)
    app.register_blueprint(reports.bp)
    app.register_blueprint(engagements.bp)
    app.register_blueprint(state_programs.bp)
    app.register_blueprint(quotes.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(not_found("Resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(not_found("Resource not found"))

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(invalid_request("Malformed request"))

    @app.errorhandler(500)
    def handle_500(err):
        return error_response(ApiError("ERR_INTERNAL", "Internal server error", 500))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
