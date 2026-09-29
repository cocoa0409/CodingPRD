"""Airline Loyalty Partner & Co-Brand Program Economics API.

Every entity lives in process memory and the store starts empty on every boot:
nothing is seeded, cached on disk or persisted between runs.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_body
from routes.awards import bp as awards_bp
from routes.governance import bp as governance_bp
from routes.issuers import bp as issuers_bp
from routes.members import bp as members_bp
from routes.ops import bp as ops_bp
from routes.programs import bp as programs_bp


def create_app():
    app = Flask(__name__)
    app.json.sort_keys = False
    app.url_map.strict_slashes = False

    app.register_blueprint(programs_bp)
    app.register_blueprint(issuers_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(awards_bp)
    app.register_blueprint(governance_bp)
    app.register_blueprint(ops_bp)

    @app.errorhandler(ApiError)
    def _api_error(err):
        return error_body(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def _not_found(_err):
        return error_body("ERR_NOT_FOUND", "No such route.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(_err):
        return error_body("ERR_INVALID_REQUEST",
                          "The HTTP method is not allowed for this path.", 405)

    @app.errorhandler(Exception)
    def _unexpected(err):
        if isinstance(err, ApiError):
            return error_body(err.error_id, err.message, err.http_status)
        app.logger.exception("unhandled error")
        return error_body("ERR_INTERNAL", str(err) or "Internal server error.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
