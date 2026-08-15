"""Hospital Emergency Preparedness & Surge Plan API — entry point."""

import os

from flask import Flask, jsonify

from envelope import error_envelope
from errors import ApiError
from routes import after_action, callbacks, clock, command, exercises, hva
from routes import incidents, patients, plans, reports, sites, staff, supply

app = Flask(__name__)
app.url_map.strict_slashes = False

for module in (staff, hva, plans, exercises, after_action, incidents, command,
               callbacks, supply, sites, patients, reports, clock):
    app.register_blueprint(module.bp, url_prefix="/emergency")


@app.errorhandler(ApiError)
def handle_api_error(err):
    return jsonify(error_envelope(err.error_id, err.message)), err.http_status


@app.errorhandler(404)
def handle_not_found(_err):
    return jsonify(error_envelope("ERR_NOT_FOUND", "resource not found")), 404


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return jsonify(error_envelope("ERR_NOT_FOUND", "method not allowed")), 405


@app.errorhandler(Exception)
def handle_unexpected(err):
    return jsonify(error_envelope("ERR_INTERNAL", "internal server error")), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
