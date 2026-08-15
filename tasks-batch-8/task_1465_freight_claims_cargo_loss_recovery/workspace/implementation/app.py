"""Freight Claims & Cargo Loss Recovery API — Flask entry point.

State is entirely in-memory (module-level dicts) and starts empty on every
boot. The server listens on 0.0.0.0:$PORT (default 10000).
"""

import os
import traceback

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes_core import bp as core_bp
    from routes_claims import bp as claims_bp
    from routes_docs_salvage import bp as docs_salvage_bp
    from routes_negotiation import bp as negotiation_bp
    from routes_recovery import bp as recovery_bp
    from routes_analytics import bp as analytics_bp

    app.register_blueprint(core_bp)
    app.register_blueprint(claims_bp)
    app.register_blueprint(docs_salvage_bp)
    app.register_blueprint(negotiation_bp)
    app.register_blueprint(recovery_bp)
    app.register_blueprint(analytics_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_response(ERR_INVALID_REQUEST, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response(ERR_INVALID_REQUEST, "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        traceback.print_exc()
        return error_response("ERR_INTERNAL", f"Internal error: {err}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
