"""Senior Benefit Card API - Flask entry point."""
import os
import random
import string
import traceback

from flask import Flask, jsonify

from errors import ApiError
from util import error_response, now_iso

API_PREFIX = "/senior-benefits"


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=24))


def _generic_error_body(error_id, message):
    return {
        "meta": {"api_request_id": _request_id(), "api_request_timestamp": now_iso()},
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes import BLUEPRINTS
    for bp in BLUEPRINTS:
        app.register_blueprint(bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err)

    @app.errorhandler(404)
    def handle_404(err):
        return jsonify(_generic_error_body("ERR_NOT_FOUND", "Resource not found")), 404

    @app.errorhandler(405)
    def handle_405(err):
        return jsonify(_generic_error_body("ERR_METHOD_NOT_ALLOWED",
                                           "Method not allowed")), 405

    @app.errorhandler(Exception)
    def handle_exception(err):
        traceback.print_exc()
        return jsonify(_generic_error_body("ERR_INTERNAL", str(err))), 500

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
