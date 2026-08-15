"""Entry point: Flask app, error handlers, route registration.

In-memory only: every process boot starts with an empty store (core.db).
"""
import os

from flask import Flask, jsonify

from core import APIError, error_body
import routes_a
import routes_b
import routes_c

app = Flask(__name__)
app.register_blueprint(routes_a.bp)
app.register_blueprint(routes_b.bp)
app.register_blueprint(routes_c.bp)


@app.errorhandler(APIError)
def handle_api_error(exc):
    body, status = error_body(exc.error_id, exc.message)
    return jsonify(body), status


@app.errorhandler(404)
def handle_404(exc):
    body, status = error_body("ERR_NOT_FOUND", "Resource not found")
    return jsonify(body), status


@app.errorhandler(405)
def handle_405(exc):
    body, status = error_body("ERR_NOT_FOUND", "Method not allowed")
    return jsonify(body), status


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, APIError):
        body, status = error_body(exc.error_id, exc.message)
        return jsonify(body), status
    body, status = error_body("ERR_INVALID_REQUEST", str(exc))
    return jsonify(body), status


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
