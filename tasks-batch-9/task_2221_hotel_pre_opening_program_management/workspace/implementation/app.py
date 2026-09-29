"""Hotel Pre-Opening Program Management API.

Flask application factory. All state lives in process memory (see db.py) and
nothing is ever seeded: every boot starts with an entirely empty store.
"""
import os

from flask import Flask, request
from werkzeug.exceptions import HTTPException

import response
import tx
from errors import ApiError
from routes.budget import bp as budget_bp
from routes.clock_route import bp as clock_bp
from routes.milestones import bp as milestones_bp
from routes.permits import bp as permits_bp
from routes.programs import bp as programs_bp
from routes.punchlist import bp as punchlist_bp
from routes.reservations import bp as reservations_bp
from routes.staffing import bp as staffing_bp
from routes.systems import bp as systems_bp

BLUEPRINTS = (
    programs_bp,
    milestones_bp,
    permits_bp,
    systems_bp,
    staffing_bp,
    budget_bp,
    reservations_bp,
    punchlist_bp,
    clock_bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.before_request
    def _open_tx():
        if request.method != "GET":
            tx.begin()

    @app.teardown_request
    def _close_tx(exc):
        tx.discard()

    @app.errorhandler(ApiError)
    def _api_error(err):
        return response.error(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def _not_found(err):
        return response.error("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def _method_not_allowed(err):
        return response.error("ERR_METHOD_NOT_ALLOWED",
                              "The HTTP method is not allowed for this resource.", 405)

    @app.errorhandler(HTTPException)
    def _http_error(err):
        if err.code == 400:
            return response.error("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)
        return response.error("ERR_INTERNAL", err.description or "Unexpected error.",
                              err.code or 500)

    @app.errorhandler(Exception)
    def _unexpected(err):
        return response.error("ERR_INTERNAL", "An unexpected error occurred.", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
