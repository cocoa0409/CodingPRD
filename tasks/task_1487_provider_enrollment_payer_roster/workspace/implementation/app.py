"""Entry point: Flask app assembly, error handlers, blueprint registration."""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
from response import error_response
from routes import (
    agreements,
    applications,
    caqh,
    claims,
    clock,
    payers,
    practice_groups,
    records,
    rosters,
)


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    for module in (
        practice_groups,
        payers,
        caqh,
        applications,
        records,
        agreements,
        rosters,
        claims,
        clock,
    ):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(ERR_NOT_FOUND, 404, "Resource not found")

    @app.errorhandler(500)
    def handle_500(e):
        return error_response("ERR_INTERNAL", 500, "Internal server error")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
