"""Problem Loan Workout & Special Assets API — Flask entry point."""
import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_body
from routes import collateral, core, exits, flat, impairments, ledger, legal, plans, proposals


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for module in (core, plans, proposals, collateral, impairments, legal,
                   ledger, exits, flat):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_body(err)

    @app.errorhandler(404)
    def handle_404(_err):
        return error_body(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(405)
    def handle_405(_err):
        return error_body(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Never leak a stack trace; surface a clean 400 for malformed input
        # classes (e.g. JSON parse failures raised inside Flask).
        status = getattr(err, "code", 500)
        if isinstance(status, int) and 400 <= status < 500:
            return error_body(ApiError(ERR_INVALID_REQUEST, status, str(err)))
        return error_body(
            ApiError(ERR_INVALID_REQUEST, 400, "Request could not be processed")
        )

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
