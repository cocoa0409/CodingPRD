"""Entry point: Flask app, error handlers, blueprint registration.

The evaluator contract is `bash start.sh`; the server listens on PORT
(default 10000), bound to 0.0.0.0, in the foreground. All state is in-memory
and starts empty on every boot.
"""

import os

from flask import Flask

from errors import ApiError, err_not_found
from response import error_response
import routes_core
import routes_workflow
import routes_quality


def create_app():
    app = Flask(__name__)
    app.register_blueprint(routes_core.bp)
    app.register_blueprint(routes_workflow.bp)
    app.register_blueprint(routes_quality.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(err_not_found("Resource not found"))

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(err_not_found("Resource not found"))

    @app.errorhandler(500)
    def handle_500(err):
        api_err = ApiError("ERR_INTERNAL", "Internal server error", 500)
        return error_response(api_err)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
