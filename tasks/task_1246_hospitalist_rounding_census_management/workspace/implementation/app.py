"""Hospitalist Census API — entry point.

Registers all blueprints and the global error handler producing the
standard error envelope.
"""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

from routes.roster import bp as roster_bp
from routes.admissions import bp as admissions_bp
from routes.discharges import bp as discharges_bp
from routes.handoffs import bp as handoffs_bp
from routes.consults import bp as consults_bp
from routes.productivity import bp as productivity_bp
from routes.coverage import bp as coverage_bp
from routes.ops import bp as ops_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(roster_bp)
    app.register_blueprint(admissions_bp)
    app.register_blueprint(discharges_bp)
    app.register_blueprint(handoffs_bp)
    app.register_blueprint(consults_bp)
    app.register_blueprint(productivity_bp)
    app.register_blueprint(coverage_bp)
    app.register_blueprint(ops_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(400)
    def handle_bad_request(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response(ERR_INVALID_REQUEST, "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response(ERR_INVALID_REQUEST, str(err), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
