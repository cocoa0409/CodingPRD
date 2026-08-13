"""Entry point: Flask app, error handlers, route registration, clock endpoint."""

import os

from flask import Flask

import errors
import middleware
from clock import iso_z, parse_iso
from errors import ApiError
from helpers import get_body, validate_body
from response import error_response, success_object
from state import CLOCK

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(err):
    return error_response(errors.ERR_NOT_FOUND, "Resource not found", 404)


@app.errorhandler(405)
def handle_405(err):
    return error_response(errors.ERR_NOT_FOUND, "Method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(err):
    # Never leak a bare 500 HTML page; surface as a schema-style 400 only when
    # it is a client-body problem, otherwise a generic 400 per envelope.
    return error_response(errors.ERR_INVALID_REQUEST, str(err) or "Bad request", 400)


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    middleware.authenticate()
    middleware.require_roles("BankAdmin")
    body = get_body()
    fields = validate_body(body, [("to_iso8601", "iso", True, None)])
    target = parse_iso(fields["to_iso8601"])
    if target is None:
        raise errors.invalid_request("to_iso8601 is not a valid ISO 8601 timestamp")
    CLOCK.set(target)
    return success_object({"current_utc": iso_z(CLOCK.now())}, 200)


import routes_accounts
import routes_disputes
import routes_chargebacks

app.register_blueprint(routes_accounts.bp)
app.register_blueprint(routes_disputes.bp)
app.register_blueprint(routes_chargebacks.bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
