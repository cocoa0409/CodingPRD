"""Bridge Inspection & Load Rating Program API — application entry point.

State lives entirely in memory (see db.py) and starts empty on every boot, so
the process may be killed and relaunched between tests without residue.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError
from routes_core import bp as core_bp
from routes_findings import bp as findings_bp
from routes_inspections import bp as inspections_bp
from routes_permits import bp as permits_bp
from routes_program import bp as program_bp
from routes_ratings import bp as ratings_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.register_blueprint(core_bp)
    app.register_blueprint(inspections_bp)
    app.register_blueprint(findings_bp)
    app.register_blueprint(ratings_bp)
    app.register_blueprint(permits_bp)
    app.register_blueprint(program_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return response.error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def handle_http_exception(error):
        status = error.code or 500
        if status == 404:
            error_id = "ERR_BRIDGE_NOT_FOUND"
            message = "The requested resource does not exist."
        elif status == 405:
            error_id = "ERR_INVALID_REQUEST"
            message = "The HTTP method is not allowed for this resource."
            status = 400
        elif status == 400:
            error_id = "ERR_INVALID_REQUEST"
            message = "The request could not be parsed."
        else:
            error_id = "ERR_INVALID_REQUEST"
            message = getattr(error, "description", "Request failed.")
        return response.error_response(error_id, message, status)

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        if isinstance(error, (ApiError, HTTPException)):
            raise error
        return response.error_response("ERR_INVALID_REQUEST", str(error), 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
