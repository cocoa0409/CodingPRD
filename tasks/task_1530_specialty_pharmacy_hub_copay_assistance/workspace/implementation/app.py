"""Specialty Pharmacy Hub API — Flask entry point.

The store starts empty on every boot; no entity is seeded. Auth headers
(X-User-ID, X-User-Role) are validated on every request before any route
handler runs. Errors are rendered in the standard envelope.
"""

import os

from flask import Flask

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_VALIDATION
from middleware import get_auth
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    from routes.config import bp as config_bp
    from routes.enrollments import bp as enrollments_bp
    from routes.prior_auth import bp as pa_bp
    from routes.assistance import bp as assistance_bp
    from routes.nurse_visits import bp as visits_bp
    from routes.shipments import bp as shipments_bp
    from routes.adverse_events import bp as ae_bp
    from routes.outcome_reports import bp as reports_bp

    app.register_blueprint(config_bp)
    app.register_blueprint(enrollments_bp)
    app.register_blueprint(pa_bp)
    app.register_blueprint(assistance_bp)
    app.register_blueprint(visits_bp)
    app.register_blueprint(shipments_bp)
    app.register_blueprint(ae_bp)
    app.register_blueprint(reports_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Route not found.", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_METHOD_NOT_ALLOWED",
                              "Method not allowed.", 405)

    @app.errorhandler(500)
    def handle_500(err):
        return error_response("ERR_INTERNAL", "Internal server error.", 500)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
