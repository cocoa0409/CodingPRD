"""Senior Games & Masters Competition API.

Entry point. The store is empty on every boot: no entity is seeded, preloaded
or hardcoded here, and every row is created through the declared API surface.
"""
import os

from flask import Flask, jsonify

import r_athlete
import r_catalog
import r_edition
import r_entry
import r_medical
import r_results
import r_schedule
import r_sponsor
import r_staff
import r_village
import store
from core import ApiError, error_body

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

for module in (
    r_edition,
    r_catalog,
    r_schedule,
    r_athlete,
    r_entry,
    r_medical,
    r_staff,
    r_results,
    r_village,
    r_sponsor,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return jsonify(error_body(store.CLOCK, exc.error_id, exc.message)), exc.http_status


@app.errorhandler(404)
def handle_not_found(_exc):
    body = error_body(store.CLOCK, "ERR_INVALID_REQUEST", "No such route")
    return jsonify(body), 404


@app.errorhandler(405)
def handle_method_not_allowed(_exc):
    body = error_body(store.CLOCK, "ERR_INVALID_REQUEST", "Method not allowed")
    return jsonify(body), 405


@app.errorhandler(400)
def handle_bad_request(_exc):
    body = error_body(store.CLOCK, "ERR_INVALID_REQUEST", "Malformed request")
    return jsonify(body), 400


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    body = error_body(store.CLOCK, "ERR_INVALID_REQUEST", "Unhandled: %s" % exc)
    return jsonify(body), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=False)
