"""Flask application entry point for the Music Royalty Distribution API."""

import os
import traceback

from flask import Flask, request

from errors import APIError
from middleware import authenticate
from response import error_response

# Route blueprints
from routes.rights_holders import bp as rh_bp
from routes.agency_bindings import bp as ab_bp
from routes.works import bp as works_bp
from routes.playback import bp as playback_bp
from routes.distribution_rules import bp as rules_bp
from routes.pools import bp as pools_bp
from routes.disputes import bp as disputes_bp
from routes.payouts import bp as payouts_bp
from routes.admin import bp as admin_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    API_PREFIX = "/royalty"

    @app.before_request
    def _auth():
        # Authentication applies to all /royalty endpoints.
        if request.path.startswith(API_PREFIX):
            authenticate()

    @app.errorhandler(APIError)
    def _handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def _handle_404(e):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def _handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def _handle_unexpected(e):
        traceback.print_exc()
        return error_response("ERR_VALIDATION", f"Internal error: {str(e)[:200]}", 422)

    # Register blueprints under /royalty
    app.register_blueprint(rh_bp, url_prefix=API_PREFIX)
    app.register_blueprint(ab_bp, url_prefix=API_PREFIX)
    app.register_blueprint(works_bp, url_prefix=API_PREFIX)
    app.register_blueprint(playback_bp, url_prefix=API_PREFIX)
    app.register_blueprint(rules_bp, url_prefix=API_PREFIX)
    app.register_blueprint(pools_bp, url_prefix=API_PREFIX)
    app.register_blueprint(disputes_bp, url_prefix=API_PREFIX)
    app.register_blueprint(payouts_bp, url_prefix=API_PREFIX)
    app.register_blueprint(admin_bp, url_prefix=API_PREFIX)

    @app.route("/health", methods=["GET"])
    def health():
        return {"status": "ok"}, 200

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
