"""Bank Capital Planning API — Flask entry point."""

from __future__ import annotations

import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.clock import bp as clock_bp
from routes.banks import bp as banks_bp
from routes.periods import bp as periods_bp
from routes.instruments import bp as instruments_bp
from routes.exposures import bp as exposures_bp
from routes.call_reports import bp as call_reports_bp
from routes.scenarios import bp as scenarios_bp
from routes.plans import bp as plans_bp
from routes.distributions import bp as distributions_bp
from routes.subdebt import bp as subdebt_bp
from routes.pca_events import bp as pca_events_bp
from routes.icaap import bp as icaap_bp
from routes.flat import bp as flat_bp


def create_app() -> Flask:
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(banks_bp)
    app.register_blueprint(periods_bp)
    app.register_blueprint(instruments_bp)
    app.register_blueprint(exposures_bp)
    app.register_blueprint(call_reports_bp)
    app.register_blueprint(scenarios_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(distributions_bp)
    app.register_blueprint(subdebt_bp)
    app.register_blueprint(pca_events_bp)
    app.register_blueprint(icaap_bp)
    app.register_blueprint(flat_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed", 405)

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
