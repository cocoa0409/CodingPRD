"""Credit Union Membership & Field of Membership API — Flask entry point."""
import os
import sys
import traceback

from flask import Flask

from errors import ApiError
from response import error_body
import routes


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_body(err)

    @app.errorhandler(404)
    def handle_not_found(_e):
        return error_body(ApiError("ERR_NOT_FOUND", "resource not found"))

    @app.errorhandler(405)
    def handle_method_not_allowed(_e):
        return error_body(ApiError("ERR_NOT_FOUND", "method not allowed"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        traceback.print_exc(file=sys.stderr)
        wrapped = ApiError("ERR_INTERNAL", f"internal error: {err}")
        wrapped.http_status = 500
        return error_body(wrapped)

    routes.register_all(app)
    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
