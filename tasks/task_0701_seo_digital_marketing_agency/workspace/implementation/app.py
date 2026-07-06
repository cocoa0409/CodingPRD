"""Entry point: app construction, error handlers, blueprint registration."""
import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.resellers import bp as resellers_bp
from routes.clients import bp as clients_bp
from routes.keywords import bp as keywords_bp
from routes.retainers import bp as retainers_bp
from routes.contracts import bp as contracts_bp
from routes.sprints import bp as sprints_bp
from routes.deliverables import bp as deliverables_bp
from routes.campaigns import bp as campaigns_bp
from routes.disputes import bp as disputes_bp
from routes.gbp import bp as gbp_bp
from routes.reports import bp as reports_bp
from routes.clock_ctl import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        resellers_bp, clients_bp, keywords_bp, retainers_bp, contracts_bp,
        sprints_bp, deliverables_bp, campaigns_bp, disputes_bp, gbp_bp,
        reports_bp, clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.http_status, e.message)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", 404, "Resource not found")

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", 404, "Method not allowed")

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        if isinstance(e, ApiError):
            return error_response(e.error_id, e.http_status, e.message)
        return error_response("ERR_INVALID_REQUEST", 422, f"Unexpected error: {e}")

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
