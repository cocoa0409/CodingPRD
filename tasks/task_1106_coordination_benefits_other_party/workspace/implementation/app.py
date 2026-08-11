"""Flask app entry point: error handlers and route registration."""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error as error_response


def create_app():
    app = Flask(__name__)

    from routes import (
        rule_configs, providers, members, coverages, leads, surveys,
        questionnaires, determinations, claims, adjustments, recovery,
        savings_periods, clock,
    )
    for mod in (
        rule_configs, providers, members, coverages, leads, surveys,
        questionnaires, determinations, claims, adjustments, recovery,
        savings_periods, clock,
    ):
        app.register_blueprint(mod.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        eid, status = ERR_NOT_FOUND
        return error_response(eid, "Resource not found", status)

    @app.errorhandler(405)
    def handle_405(err):
        eid, status = ERR_NOT_FOUND
        return error_response(eid, "Resource not found", status)

    @app.errorhandler(400)
    def handle_400(err):
        eid, status = ERR_INVALID_REQUEST
        return error_response(eid, "Bad request", status)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Surface as 500 with the standard error envelope
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
