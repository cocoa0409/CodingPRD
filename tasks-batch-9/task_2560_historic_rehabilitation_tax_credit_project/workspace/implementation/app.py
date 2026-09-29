"""Historic Rehabilitation Tax Credit API — Flask application factory.

Storage is process memory only; nothing is seeded at import time.
"""

import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_body


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    from routes.identity import bp as identity_bp
    from routes.projects import bp as projects_bp
    from routes.part_applications import bp as applications_bp
    from routes.costs import bp as costs_bp
    from routes.amendments import bp as amendments_bp
    from routes.investors import bp as investors_bp
    from routes.compliance import bp as compliance_bp

    for blueprint in (
        identity_bp,
        projects_bp,
        applications_bp,
        costs_bp,
        amendments_bp,
        investors_bp,
        compliance_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return jsonify(error_body(err.error_id, err.message)), err.http_status

    @app.errorhandler(404)
    def handle_not_found(err):
        return jsonify(error_body("ERR_INVALID_REQUEST", "No such route.")), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return (
            jsonify(error_body("ERR_INVALID_REQUEST", "Method not allowed for this route.")),
            405,
        )

    @app.errorhandler(400)
    def handle_bad_request(err):
        return jsonify(error_body("ERR_INVALID_REQUEST", "The request could not be parsed.")), 400

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return handle_api_error(err)
        return (
            jsonify(
                {
                    "meta": error_body("ERR_INVALID_REQUEST", "")["meta"],
                    "response_type": "error",
                    "data": {
                        "error_id": "ERR_INTERNAL",
                        "message": "Unexpected server error: %s" % err,
                    },
                }
            ),
            500,
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
