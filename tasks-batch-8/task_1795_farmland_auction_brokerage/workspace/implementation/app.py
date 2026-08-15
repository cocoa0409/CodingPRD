"""Farmland Auction & Brokerage API — Flask entry point.

Storage is in-memory only (module-level dicts in db.py). A fresh process boot
therefore starts from a completely empty store; nothing is seeded.
"""

import os

from flask import Flask, jsonify

from errors import ApiError, ERR_NOT_FOUND
from response import error_body

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False


@app.errorhandler(ApiError)
def handle_api_error(err: ApiError):
    return jsonify(error_body(err.error_id, err.message)), err.http_status


@app.errorhandler(404)
def handle_404(err):
    error_id, status = ERR_NOT_FOUND
    return jsonify(error_body(error_id, "resource not found")), status


@app.errorhandler(405)
def handle_405(err):
    error_id, status = ERR_NOT_FOUND
    return jsonify(error_body(error_id, "method not allowed")), status


@app.errorhandler(500)
def handle_500(err):
    return jsonify(error_body("ERR_INTERNAL", "internal server error")), 500


# Route registration (blueprints import db/services; no state is seeded).
from routes import clock, parties, listings, auctions, escrow, compliance, closings  # noqa: E402

for module in (clock, parties, listings, auctions, escrow, compliance, closings):
    app.register_blueprint(module.bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
