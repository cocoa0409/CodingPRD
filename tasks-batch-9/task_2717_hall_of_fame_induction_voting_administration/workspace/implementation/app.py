"""Hall of Fame Induction & Voting Administration API.

Storage is in-memory only: every collection starts empty on every boot and every
row is created by a client through a declared endpoint.  Nothing is seeded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError, ERROR_STATUS
from routes.ballot_routes import bp as ballot_bp
from routes.candidacy_routes import bp as candidacy_bp
from routes.ceremony_routes import bp as ceremony_bp
from routes.config_routes import bp as config_bp
from routes.cycle_routes import bp as cycle_bp
from routes.vote_routes import bp as vote_bp

DEFAULT_PORT = 10000


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.config["PROPAGATE_EXCEPTIONS"] = False

    app.register_blueprint(config_bp)
    app.register_blueprint(cycle_bp)
    app.register_blueprint(candidacy_bp)
    app.register_blueprint(ballot_bp)
    app.register_blueprint(vote_bp)
    app.register_blueprint(ceremony_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        body = response.error_body(exc.error_id, exc.message)
        return body, exc.http_status

    @app.errorhandler(HTTPException)
    def handle_http_error(exc):
        if exc.code == 404:
            error_id = "ERR_NOT_FOUND"
        elif exc.code == 405:
            error_id = "ERR_METHOD_NOT_ALLOWED"
        elif exc.code == 400:
            error_id = "ERR_INVALID_REQUEST"
        else:
            error_id = "ERR_INVALID_REQUEST" if exc.code and exc.code < 500 else "ERR_INTERNAL"
        status = exc.code or ERROR_STATUS.get(error_id, 400)
        body = response.error_body(error_id, exc.description or error_id)
        return body, status

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        body = response.error_body("ERR_INTERNAL", "An unexpected server error occurred.")
        return body, 500

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", str(DEFAULT_PORT)))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
