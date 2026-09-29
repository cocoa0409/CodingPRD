"""Water Rights Transfer & Adjudication Support Service.

Flask application factory + error envelope handlers. All state lives in
process memory (see db.py) and nothing is seeded at boot.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ERROR_CATALOG, ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    from routes.clock_routes import bp as clock_bp
    from routes.claimants import bp as claimants_bp
    from routes.water_rights import bp as water_rights_bp
    from routes.beneficial_use import bp as beneficial_use_bp
    from routes.points_of_diversion import bp as pods_bp
    from routes.hcu_studies import bp as studies_bp
    from routes.transfer_applications import bp as apps_bp
    from routes.injury_analyses import bp as analyses_bp
    from routes.protests import bp as protests_bp
    from routes.approval_conditions import bp as conditions_bp
    from routes.water_bank import bp as bank_bp
    from routes.leases import bp as leases_bp
    from routes.adjudication import bp as adjudication_bp

    for blueprint in (
        clock_bp,
        claimants_bp,
        water_rights_bp,
        beneficial_use_bp,
        pods_bp,
        studies_bp,
        apps_bp,
        analyses_bp,
        protests_bp,
        conditions_bp,
        bank_bp,
        leases_bp,
        adjudication_bp,
    ):
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(exc):
        return response.error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(exc):
        if exc.code == 404:
            error_id = "ERR_NOT_FOUND"
            message = "The requested resource does not exist."
        elif exc.code == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
            message = "The HTTP method is not allowed for this resource."
        elif exc.code == 400:
            error_id = "ERR_INVALID_REQUEST"
            message = "Request payload is malformed."
        else:
            error_id = "ERR_INTERNAL"
            message = exc.description or "Unexpected error."
        status = exc.code or ERROR_CATALOG.get(error_id, 500)
        return response.error_response(error_id, message, status)

    @app.errorhandler(Exception)
    def _unhandled(exc):
        return response.error_response(
            "ERR_INTERNAL", "Unexpected error: %s" % exc, 500
        )

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
