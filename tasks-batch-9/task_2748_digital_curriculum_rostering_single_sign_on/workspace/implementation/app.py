"""Digital Curriculum Rostering and Single Sign-On -- Flask entry point.

State lives in module-level dicts only (see store.py): a fresh process starts
with an empty district and the logical clock at 2026-08-01T00:00:00Z.
"""
import os

from flask import Flask, jsonify

import envelope
import routes_identity
import routes_license
import routes_pipeline
import routes_reads
import routes_ref
import routes_roster
import store
from errors import ApiError


def create_app():
    app = Flask(__name__)
    # Field order is part of the contract, so never sort JSON keys.
    try:
        app.json.sort_keys = False
    except AttributeError:  # Flask < 2.2
        app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    app.register_blueprint(routes_reads.bp)
    app.register_blueprint(routes_ref.bp)
    app.register_blueprint(routes_roster.bp)
    app.register_blueprint(routes_license.bp)
    app.register_blueprint(routes_identity.bp)
    app.register_blueprint(routes_pipeline.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return envelope.failure(error.error_id, error.message, error.http_status)

    @app.errorhandler(400)
    def handle_bad_request(error):
        return envelope.failure("ERR_INVALID_REQUEST",
                                "The request body or query is malformed.", 400)

    @app.errorhandler(404)
    def handle_not_found(error):
        return envelope.failure("ERR_INVALID_REQUEST", "No such route.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(error):
        return envelope.failure("ERR_INVALID_REQUEST",
                                "The method is not allowed on this route.", 405)

    @app.errorhandler(415)
    def handle_unsupported_media(error):
        return envelope.failure("ERR_INVALID_REQUEST",
                                "The request body must be JSON.", 400)

    @app.errorhandler(500)
    def handle_server_error(error):
        return envelope.failure("ERR_INVALID_REQUEST", "Internal error.", 500)

    @app.errorhandler(Exception)
    def handle_unexpected(error):
        if isinstance(error, ApiError):
            return handle_api_error(error)
        code = getattr(error, "code", None)
        if isinstance(code, int):
            return envelope.failure("ERR_INVALID_REQUEST",
                                    getattr(error, "description", "Request refused."),
                                    code)
        return envelope.failure("ERR_INVALID_REQUEST", "Internal error.", 500)

    @app.get("/_health")
    def health():
        return jsonify({"status": "ok", "now": store.fmt_instant(store.clock_now())}), 200

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False,
            use_reloader=False)
