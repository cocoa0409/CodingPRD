"""Ballot Production & Logic and Accuracy Testing API.

Entry point: registers the route blueprints and the JSON error handlers.
The in-memory store starts empty on every boot -- nothing is seeded.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
import routes_election
import routes_print
import routes_style
import routes_tab
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(routes_election.bp)
app.register_blueprint(routes_style.bp)
app.register_blueprint(routes_print.bp)
app.register_blueprint(routes_tab.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return envelope.error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(exc):
    return envelope.error("ERR_NOT_FOUND", "The requested resource does not exist.", 404)


@app.errorhandler(405)
def handle_405(exc):
    return envelope.error("ERR_METHOD_NOT_ALLOWED",
                          "The method is not allowed for this resource.", 405)


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    if exc.code == 400:
        return envelope.error("ERR_INVALID_REQUEST", "The request body is not valid JSON.", 400)
    return envelope.error("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                          exc.code or 400)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    return envelope.error("ERR_INTERNAL", "%s: %s" % (type(exc).__name__, exc), 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
