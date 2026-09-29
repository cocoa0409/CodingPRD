"""Nonprofit Merger & Affiliation API — Flask application entry point.

Storage is in-memory only and starts completely empty on every boot: the harness
kills and relaunches this process before every individual test.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

import routes_ag
import routes_approvals
import routes_deal
import routes_diligence
import routes_funds
import routes_letters
import routes_ops
import routes_read
import routes_registry
import routes_tasks
from errors import ApiError, DEFAULT_MESSAGES
from response import error_body


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    app.register_blueprint(routes_read.bp)
    app.register_blueprint(routes_registry.bp)
    app.register_blueprint(routes_deal.bp)
    app.register_blueprint(routes_letters.bp)
    app.register_blueprint(routes_diligence.bp)
    app.register_blueprint(routes_funds.bp)
    app.register_blueprint(routes_approvals.bp)
    app.register_blueprint(routes_ag.bp)
    app.register_blueprint(routes_tasks.bp)
    app.register_blueprint(routes_ops.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return jsonify(error_body(exc.error_id, exc.message)), exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            error_id = "ERR_NOT_FOUND"
            message = "The requested route does not exist."
        elif exc.code == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
            message = "The HTTP method is not allowed for this route."
        elif exc.code == 400:
            error_id = "ERR_INVALID_REQUEST"
            message = DEFAULT_MESSAGES.get("ERR_INVALID_REQUEST", "Invalid request.")
        else:
            error_id = "ERR_INTERNAL"
            message = exc.description or "Request failed."
        return jsonify(error_body(error_id, message)), exc.code

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        return jsonify(error_body("ERR_INTERNAL", str(exc))), 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
