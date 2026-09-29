"""Trade Show Organization -- Exhibitor Sales API (Python + Flask).

The store is in-memory only and starts completely empty on every boot: no
entity is seeded, preloaded or hardcoded anywhere in this process.
"""
import os

from flask import Flask, jsonify

from errors import ApiError
from response import error_response
from routes import (appointments, booths, clock, contracts, exhibitors, floor,
                    registrations, shows, sponsorship, venue_contracts)

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (venue_contracts, shows, booths, exhibitors, appointments, contracts,
               floor, sponsorship, registrations, clock):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(error):
    return error_response(error.error_id, error.message, error.http_status)


@app.errorhandler(404)
def handle_not_found(error):
    return error_response("ERR_NOT_FOUND", "no such route", 404)


@app.errorhandler(405)
def handle_method_not_allowed(error):
    return error_response("ERR_METHOD_NOT_ALLOWED",
                          "the method is not allowed for this route", 405)


@app.errorhandler(400)
def handle_bad_request(error):
    return error_response("ERR_VALIDATION", "the request body is not valid JSON", 422)


@app.errorhandler(Exception)
def handle_unexpected(error):
    if isinstance(error, ApiError):
        return handle_api_error(error)
    app.logger.exception("unhandled error")
    return error_response("ERR_INTERNAL", "unexpected server error", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=False, debug=False, use_reloader=False)
