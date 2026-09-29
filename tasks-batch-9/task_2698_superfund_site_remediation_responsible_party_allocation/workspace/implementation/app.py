"""Superfund Remediation Allocation API.

Flask application factory.  Every collection lives in process memory and boots
empty: no entity data is ever seeded, preloaded or hardcoded, so a fresh
process is a fresh system and the test harness can relaunch at will.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError
from routes import (
    actions,
    contracts,
    decrees,
    evidence,
    prps,
    reads,
    ri,
    rod,
    rounds,
    sites,
)

BLUEPRINTS = (
    reads.bp,
    sites.bp,
    prps.bp,
    evidence.bp,
    ri.bp,
    rod.bp,
    rounds.bp,
    decrees.bp,
    contracts.bp,
    actions.bp,
)


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    try:
        app.json.sort_keys = False
    except AttributeError:  # Flask < 2.3
        app.config["JSON_SORT_KEYS"] = False

    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)

    @app.errorhandler(ApiError)
    def _api_error(error):
        return envelope.err(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        if error.code == 404:
            return envelope.err("ERR_NOT_FOUND", "No such route.", 404)
        if error.code == 405:
            return envelope.err(
                "ERR_NOT_FOUND", "The method is not allowed for this route.", 405
            )
        if error.code in (400, 415):
            return envelope.err(
                "ERR_INVALID_REQUEST", "The request is malformed.", 422
            )
        return envelope.err(
            "ERR_INTERNAL", error.description or "Request failed.", error.code or 500
        )

    @app.errorhandler(Exception)
    def _unexpected(error):
        return envelope.err("ERR_INTERNAL", "%s: %s" % (type(error).__name__, error), 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        debug=False,
        use_reloader=False,
        threaded=True,
    )
