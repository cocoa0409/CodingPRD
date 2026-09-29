"""Nonprofit newsroom membership and grant funding service.

Entry point: registers the route blueprints and the error handlers that render
the PRD's §2.2 envelope.  All state lives in process memory (core.DB) and the
store starts completely empty on every boot -- nothing is seeded here.
"""

import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from core import ApiError, error_body
import routes_collab
import routes_contributions
import routes_firewall
import routes_fiscal
import routes_gifts
import routes_grants
import routes_membership


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.json.sort_keys = False

    app.register_blueprint(routes_fiscal.bp)
    app.register_blueprint(routes_membership.bp)
    app.register_blueprint(routes_firewall.bp)
    app.register_blueprint(routes_gifts.bp)
    app.register_blueprint(routes_grants.bp)
    app.register_blueprint(routes_contributions.bp)
    app.register_blueprint(routes_collab.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return jsonify(error_body(error.error_id, error.message)), error.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        return (jsonify(error_body("ERR_INVALID_REQUEST", error.description or "")),
                error.code)

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        return jsonify(error_body("ERR_INVALID_REQUEST", str(error))), 422

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
