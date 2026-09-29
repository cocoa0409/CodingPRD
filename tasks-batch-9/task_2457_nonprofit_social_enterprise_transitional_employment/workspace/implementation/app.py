"""Nonprofit Social Enterprise & Transitional Employment API.

A single Flask process holding every row in memory.  Re-launching the process
wipes all state; nothing is ever persisted and no entity is ever seeded.
"""

import os

from flask import Flask, g
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from routes import intake, ledger, placements, trading


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.config["JSON_SORT_KEYS"] = False
    app.json.sort_keys = False

    for module in (intake, trading, placements, ledger):
        app.register_blueprint(module.bp)

    @app.before_request
    def _begin_request():
        # One version increment per mutated row per request (PRD 2.4).
        g.touched_rows = set()

    @app.errorhandler(ApiError)
    def _api_error(error):
        return error_response(error.error_id, error.message, error.http_status)

    @app.errorhandler(HTTPException)
    def _http_error(error):
        return error_response("ERR_INVALID_REQUEST",
                              error.description or "The request could not be processed.",
                              error.code or 400)

    @app.errorhandler(Exception)
    def _unexpected(error):
        return error_response("ERR_INVALID_REQUEST", "Unexpected server error: %s" % error, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=False, debug=False, use_reloader=False)
