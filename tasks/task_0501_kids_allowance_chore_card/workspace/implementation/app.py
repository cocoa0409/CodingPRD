"""Entry point: app factory, error handlers, blueprint registration.

In-memory only — state lives in db.py module dicts and is wiped on every boot.
No seeding at startup.
"""
import os

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import api_error_response, error_response
from routes.families import bp as families_bp
from routes.chores import bp as chores_bp
from routes.cards import bp as cards_bp
from routes.allowances import bp as allowances_bp
from routes.interest import bp as interest_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(families_bp)
    app.register_blueprint(chores_bp)
    app.register_blueprint(cards_bp)
    app.register_blueprint(allowances_bp)
    app.register_blueprint(interest_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return api_error_response(exc)

    @app.errorhandler(404)
    def handle_404(exc):
        return error_response("ERR_NOT_FOUND", "Resource not found")

    @app.errorhandler(405)
    def handle_405(exc):
        return error_response("ERR_NOT_FOUND", "Method not allowed")

    @app.errorhandler(400)
    def handle_400(exc):
        return error_response("ERR_INVALID_REQUEST", "Bad request")

    @app.errorhandler(HTTPException)
    def handle_http(exc):
        # Map any other werkzeug HTTP error into the standard envelope.
        if exc.code == 404:
            return error_response("ERR_NOT_FOUND", "Resource not found")
        if exc.code == 400:
            return error_response("ERR_INVALID_REQUEST", "Bad request")
        return error_response("ERR_INVALID_REQUEST", exc.description or "Error")

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        # Last-resort: never leak a raw 500 HTML page; keep the envelope shape.
        body = {
            "meta": {},
            "response_type": "error",
            "data": {"error_id": "ERR_INTERNAL", "message": str(exc)},
        }
        return jsonify(body), 500

    return app


app = create_app()


if __name__ == "__main__":
    # Quiet the Werkzeug dev server: the per-test-server isolation reboots this
    # process before every test, and the 8-round stability sweep runs those
    # reboots ~8x concurrently. Silencing request logging and the startup banner
    # cuts per-boot/per-request I/O so boot reliably completes within the
    # runner's restart deadline even under peak CPU contention (otherwise the
    # restart boundary can race into "could not be restarted"/RemoteDisconnected
    # for whichever test sits at that boundary). Response behavior is unchanged.
    import logging

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    import flask.cli

    flask.cli.show_server_banner = lambda *a, **k: None

    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
