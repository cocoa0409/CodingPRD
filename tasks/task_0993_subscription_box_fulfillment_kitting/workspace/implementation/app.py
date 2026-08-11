"""Subscription-Box Fulfillment & Kitting Service — entry point."""
import os

from flask import Flask, jsonify

from core import ApiError, error_body, req_meta
import routes_core
import routes_ops

app = Flask(__name__)
app.register_blueprint(routes_core.bp)
app.register_blueprint(routes_ops.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_body(e)


@app.errorhandler(404)
def handle_404(e):
    return jsonify({"meta": req_meta(), "response_type": "error",
                    "data": {"error_id": "ERR_NOT_FOUND",
                             "message": "Resource not found"}}), 404


@app.errorhandler(405)
def handle_405(e):
    return jsonify({"meta": req_meta(), "response_type": "error",
                    "data": {"error_id": "ERR_NOT_FOUND",
                             "message": "Method not allowed"}}), 405


@app.errorhandler(Exception)
def handle_500(e):
    return jsonify({"meta": req_meta(), "response_type": "error",
                    "data": {"error_id": "ERR_INVALID_REQUEST",
                             "message": "Internal server error"}}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
