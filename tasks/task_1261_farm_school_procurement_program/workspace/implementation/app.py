"""Farm School Procurement API — entry point. In-memory store; no seeding."""
import os

from flask import Flask, jsonify

from errors import ApiError
from util import error_response, meta

app = Flask(__name__)
app.url_map.strict_slashes = False

import routes_agreements
import routes_billing
import routes_catalog
import routes_core

app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_catalog.bp)
app.register_blueprint(routes_agreements.bp)
app.register_blueprint(routes_billing.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return jsonify({
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Route not found"},
    }), 404


@app.errorhandler(405)
def handle_405(err):
    return jsonify({
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_METHOD_NOT_ALLOWED", "message": "Method not allowed"},
    }), 405


@app.errorhandler(Exception)
def handle_exception(err):
    if isinstance(err, ApiError):
        return error_response(err)
    return jsonify({
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": str(err)},
    }), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
