"""Fire Protection System Design & Hydraulic Calculation service.

Entry point: registers every route group and the uniform error envelope.
No entity data is seeded at startup; the store is empty on every boot.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes import (
    acceptance,
    aux_systems,
    calculations,
    comments,
    directory,
    evaluations,
    flow_tests,
    hazard_areas,
    iterations,
    projects,
    pumps,
    shop_drawings,
    submittals,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (
        directory,
        projects,
        hazard_areas,
        flow_tests,
        calculations,
        iterations,
        evaluations,
        pumps,
        aux_systems,
        shop_drawings,
        submittals,
        comments,
        acceptance,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.error(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            return response.error("ERR_NOT_FOUND", "No such resource.", 404)
        if exc.code == 405:
            return response.error(
                "ERR_METHOD_NOT_ALLOWED", "That method is not allowed here.", 405
            )
        if exc.code == 400:
            return response.error(
                "ERR_INVALID_REQUEST", "The request could not be parsed.", 422
            )
        return response.error(
            "ERR_INVALID_REQUEST", exc.description or "Request refused.", exc.code or 500
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return response.error("ERR_INTERNAL", "%s: %s" % (type(exc).__name__, exc), 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=False,
        debug=False,
        use_reloader=False,
    )
