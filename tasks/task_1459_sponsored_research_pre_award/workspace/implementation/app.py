"""Sponsored Research Pre-Award API — Flask entry point."""

import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
from response import error_response, ok_object
from utils import new_request_id, now_request_ts
from flask import jsonify

import routes_core
import routes_proposals
import routes_workflow
import routes_reviews

app = Flask(__name__)
app.url_map.strict_slashes = False

app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_proposals.bp)
app.register_blueprint(routes_workflow.bp)
app.register_blueprint(routes_reviews.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": now_request_ts(),
        },
        "response_type": "error",
        "data": {"error_id": ERR_NOT_FOUND, "message": "Resource not found"},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(err):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": now_request_ts(),
        },
        "response_type": "error",
        "data": {"error_id": ERR_NOT_FOUND, "message": "Method not allowed"},
    }
    return jsonify(body), 405


@app.errorhandler(Exception)
def handle_unexpected(err):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": now_request_ts(),
        },
        "response_type": "error",
        "data": {"error_id": "ERR_INTERNAL_SERVER_ERROR",
                 "message": "Internal server error"},
    }
    return jsonify(body), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
