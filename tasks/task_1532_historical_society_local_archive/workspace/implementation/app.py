"""Historical Society & Local Archive API — Flask entry point."""

from __future__ import annotations

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from response import error_response

from routes.clock import bp as clock_bp
from routes.zones import bp as zones_bp
from routes.collections import bp as collections_bp
from routes.accessions import bp as accessions_bp
from routes.items import bp as items_bp
from routes.assessments import bp as assessments_bp
from routes.finding_aids import bp as finding_aids_bp
from routes.projects import bp as projects_bp
from routes.tickets import bp as tickets_bp
from routes.researchers import bp as researchers_bp
from routes.requests import bp as requests_bp
from routes.appointments import bp as appointments_bp
from routes.orders import bp as orders_bp
from routes.proposals import bp as proposals_bp
from routes.oral import bp as oral_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp, zones_bp, collections_bp, accessions_bp, items_bp,
        assessments_bp, finding_aids_bp, projects_bp, tickets_bp,
        researchers_bp, requests_bp, appointments_bp, orders_bp,
        proposals_bp, oral_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(ERR_INVALID_REQUEST, "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err: Exception):
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    try:
        from waitress import serve
        serve(app, host="0.0.0.0", port=port, threads=8, channel_timeout=30)
    except ImportError:
        app.run(host="0.0.0.0", port=port, threaded=True)
