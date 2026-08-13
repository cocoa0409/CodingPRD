import os

from flask import Flask, jsonify

from core import ApiError, error_response, meta
from routes import (awards, cells, clock, commitments, holds, instruments,
                    invitations, panelists, publications, refresh, responses,
                    snapshots, translations, waves)

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

for module in (clock, cells, panelists, instruments, translations, waves,
               invitations, responses, awards, snapshots, publications,
               commitments, holds, refresh):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc)


@app.errorhandler(404)
def handle_not_found(_exc):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Route not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_method_not_allowed(_exc):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed"},
    }
    return jsonify(body), 405


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return error_response(exc)
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL", "message": "Internal server error"},
    }
    return jsonify(body), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
