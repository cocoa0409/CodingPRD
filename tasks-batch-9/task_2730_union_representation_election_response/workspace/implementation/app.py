"""Union Representation Election Response API — Flask entry point.

Storage is entirely in memory (see store.py) and starts empty on every boot: no
entity is ever seeded, preloaded or hardcoded at startup. Every row in the system
is created by a client through the declared endpoints.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import envelope
from errors import ApiError
from routes import (ballots, charges, classifications, clock, communications, agreements,
                    entries, objections, petitions, rounds, sessions, supervisors, voter_lists)

app = Flask(__name__)
app.url_map.strict_slashes = False

for blueprint in (clock.bp, petitions.bp, classifications.bp, agreements.bp, voter_lists.bp,
                  entries.bp, supervisors.bp, communications.bp, rounds.bp, sessions.bp,
                  ballots.bp, objections.bp, charges.bp):
    app.register_blueprint(blueprint)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return envelope.error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_not_found(exc):
    return envelope.error_response("ERR_INVALID_REQUEST", "No such route.", 422)


@app.errorhandler(405)
def handle_method_not_allowed(exc):
    return envelope.error_response("ERR_INVALID_REQUEST",
                                   "That method is not allowed on this route.", 422)


@app.errorhandler(HTTPException)
def handle_http_exception(exc):
    if exc.code in (400, 415):
        return envelope.error_response("ERR_INVALID_REQUEST", "Malformed request.", 422)
    return envelope.error_response("ERR_INVALID_REQUEST", exc.description or "Request failed.",
                                   422)


@app.errorhandler(Exception)
def handle_unexpected(exc):  # pragma: no cover - defensive
    app.logger.exception("Unhandled error while serving a request")
    return envelope.error_response("ERR_INVALID_REQUEST", "Unexpected server failure.", 422)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
