"""Entry point: Flask app, error handlers, blueprint registration."""
import os

from flask import Flask

from core import ApiError, error_envelope
import routes_admin
import routes_flow
import routes_money

app = Flask(__name__)
app.register_blueprint(routes_admin.bp)
app.register_blueprint(routes_flow.bp)
app.register_blueprint(routes_money.bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_envelope(e)


@app.errorhandler(404)
def handle_not_found(e):
    return error_envelope(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return error_envelope(ApiError("ERR_METHOD_NOT_ALLOWED", 405,
                                   "Method not allowed"))


@app.errorhandler(500)
def handle_internal_error(e):
    return error_envelope(ApiError("ERR_INTERNAL", 500, "Internal server error"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
