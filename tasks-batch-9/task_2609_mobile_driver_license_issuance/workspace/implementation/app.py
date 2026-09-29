"""Mobile Driver License Issuance and Verification Platform.

A single-process Flask application holding every byte of state in memory.
No entity data is seeded: the API is the only way rows come into existence.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import routes_credential
import routes_device
import routes_holder
import routes_presentation
import routes_profile
import routes_proofing
import routes_update
import routes_verifier
from envelope import err
from errors import DEFAULT_MESSAGES, ApiError


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False
    app.url_map.strict_slashes = False

    for module in (routes_profile, routes_holder, routes_proofing, routes_device,
                   routes_credential, routes_update, routes_verifier,
                   routes_presentation):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(error):
        return err(error.error_id, error.message, error.http_status)

    @app.errorhandler(404)
    def handle_not_found(error):
        return err("ERR_NOT_FOUND", "The requested route does not exist.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(error):
        return err("ERR_NOT_FOUND",
                   "The requested method is not allowed on this route.", 405)

    @app.errorhandler(HTTPException)
    def handle_http_exception(error):
        if error.code == 400:
            return err("ERR_INVALID_REQUEST",
                       DEFAULT_MESSAGES.get("ERR_INVALID_REQUEST", "Bad request."),
                       400)
        return err("ERR_INVALID_REQUEST", error.description or "Request failed.",
                   error.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected(error):  # pragma: no cover - defensive
        return err("ERR_INVALID_REQUEST", str(error), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
