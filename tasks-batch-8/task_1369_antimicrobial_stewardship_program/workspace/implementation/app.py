"""Antimicrobial Stewardship Program API — entry point.

Flask app wiring blueprints, error handlers, and the server bootstrap.
State is in-memory only (see db.py); every process start is a clean slate.
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.core_resources import bp as core_bp
    from routes.allergy_culture import bp as allergy_bp
    from routes.orders_approvals import bp as orders_bp
    from routes.interventions_opportunities import bp as interventions_bp
    from routes.surveillance_reporting import bp as surveillance_bp

    app.register_blueprint(core_bp)
    app.register_blueprint(allergy_bp)
    app.register_blueprint(orders_bp)
    app.register_blueprint(interventions_bp)
    app.register_blueprint(surveillance_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response("ERR_INVALID_REQUEST", "Malformed request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        return error_response("ERR_INVALID_REQUEST", f"Unexpected error: {err}", 400)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
