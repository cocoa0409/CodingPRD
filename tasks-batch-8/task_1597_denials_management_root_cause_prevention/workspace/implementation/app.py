"""Denials Management API — Flask entry point.

Binds 0.0.0.0:$PORT (default 10000). Storage is in-memory only; every process
boot starts with an empty store and the default logical clock.
"""

import os

from flask import Flask, jsonify

from envelope import error_body
from errors import ApiError, ERR_NOT_FOUND, ERR_VALIDATION


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    from routes_admin import bp as admin_bp
    from routes_appeals import bp as appeals_bp
    from routes_denials import bp as denials_bp
    from routes_scorecards import bp as scorecards_bp
    from routes_tasks import bp as tasks_bp
    from routes_writeoffs import bp as writeoffs_bp

    for module_bp in (
        admin_bp,
        denials_bp,
        appeals_bp,
        tasks_bp,
        writeoffs_bp,
        scorecards_bp,
    ):
        app.register_blueprint(module_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return jsonify(error_body(err.error_id, err.message)), err.status

    @app.errorhandler(404)
    def handle_not_found(_err):
        return jsonify(error_body(ERR_NOT_FOUND, "Resource not found")), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(_err):
        return jsonify(error_body(ERR_NOT_FOUND, "Method not allowed")), 405

    @app.errorhandler(400)
    def handle_bad_request(_err):
        return jsonify(error_body(ERR_VALIDATION, "Bad request")), 400

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return (
            jsonify(error_body("ERR_INTERNAL", "Internal error: %s" % err)),
            500,
        )

    return app


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
        threaded=True,
    )
