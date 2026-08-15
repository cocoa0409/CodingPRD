"""Entry point: Flask app assembly, request gauntlet (auth -> sweep), error
handlers, and the foreground server loop."""

import os

from flask import Flask

import store
from envelope import error, ok
from errors import ApiError, not_found
from helpers import authenticate

import routes_roster
import routes_holds
import routes_negotiation
import routes_ticketing
import routes_production
import routes_finance

app = Flask(__name__)
app.url_map.strict_slashes = False

for bp in (routes_roster.bp, routes_holds.bp, routes_negotiation.bp,
           routes_ticketing.bp, routes_production.bp, routes_finance.bp):
    app.register_blueprint(bp)


@app.before_request
def gauntlet():
    # Lazy time-based transitions run before every read/write (PRD 2.7)
    store.sweep_time_transitions()
    # Authentication is step 1 of the validation pipeline (PRD 2.8)
    authenticate()


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error(err)


@app.errorhandler(404)
def handle_404(err):
    return error(not_found("Resource not found"))


@app.errorhandler(405)
def handle_405(err):
    return error(not_found("Resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error(err)
    return error(ApiError("ERR_INTERNAL", "Internal server error", 500))


@app.get("/")
def root():
    return ok({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
