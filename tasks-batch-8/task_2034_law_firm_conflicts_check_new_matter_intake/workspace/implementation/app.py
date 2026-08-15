"""Law Firm Intake API — Flask entry point.

Mounts all /intake resources plus the /_clock test-driving endpoint, and
renders every response in the PRD 2.2 envelope. State lives entirely in
process memory (db.py); nothing is seeded at startup.
"""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
from response import error_body


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes import (
        parties, attorneys, matters, conflicts, walls, waivers, letters,
        credit, clock,
    )
    for module in (parties, attorneys, matters, conflicts, walls, waivers,
                   letters, credit, clock):
        app.register_blueprint(module.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_body(err)

    @app.errorhandler(404)
    def handle_not_found(err):
        return error_body(ApiError(ERR_NOT_FOUND, 404,
                                   "Resource not found"))

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Never leak a stack trace through the envelope contract.
        return error_body(ApiError("ERR_INTERNAL", 500, "Internal error"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
