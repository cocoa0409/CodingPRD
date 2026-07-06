"""Branding & Design Studio API — Flask entry point.

In-memory only; nothing is seeded at startup. The store (db.py) starts empty on
every boot. Run via start.sh; binds 0.0.0.0:$PORT (default 10000) in foreground.
"""
import os

from flask import Flask

from errors import ApiError
from response import error as error_response

from routes.clock_routes import bp as clock_bp
from routes.studios import bp as studios_bp
from routes.clients import bp as clients_bp
from routes.projects import bp as projects_bp
from routes.moodboards import bp as moodboards_bp
from routes.concepts import bp as concepts_bp
from routes.milestones import bp as milestones_bp
from routes.invoices import bp as invoices_bp
from routes.deliverables import bp as deliverables_bp
from routes.licenses import bp as licenses_bp
from routes.change_orders import bp as change_orders_bp
from routes.retainers import bp as retainers_bp
from routes.care_cycles import bp as care_cycles_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        clock_bp,
        studios_bp,
        clients_bp,
        projects_bp,
        moodboards_bp,
        concepts_bp,
        milestones_bp,
        invoices_bp,
        deliverables_bp,
        licenses_bp,
        change_orders_bp,
        retainers_bp,
        care_cycles_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        # Unknown route — treat as not found in our envelope.
        from errors import ERR_NOT_FOUND, HTTP_STATUS
        return error_response(ERR_NOT_FOUND, "Resource not found",
                              HTTP_STATUS[ERR_NOT_FOUND])

    @app.errorhandler(405)
    def handle_405(e):
        from errors import ERR_NOT_FOUND, HTTP_STATUS
        return error_response(ERR_NOT_FOUND, "Resource not found",
                              HTTP_STATUS[ERR_NOT_FOUND])

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.message, e.http_status)
        # Last-resort: surface as a generic invalid request rather than HTML.
        from errors import ERR_INVALID_REQUEST, HTTP_STATUS
        return error_response(ERR_INVALID_REQUEST, str(e),
                              HTTP_STATUS[ERR_INVALID_REQUEST])

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
