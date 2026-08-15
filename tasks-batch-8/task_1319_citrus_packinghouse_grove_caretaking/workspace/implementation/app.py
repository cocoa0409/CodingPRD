"""Citrus Packinghouse & Grove Caretaking API — Flask entry point."""
import os

from flask import Flask

from core import ApiError, error_response, ERR_NOT_FOUND
import routes_core1
import routes_line
import routes_money
import routes_compliance

app = Flask(__name__)
app.json.sort_keys = False

app.register_blueprint(routes_core1.bp)
app.register_blueprint(routes_line.bp)
app.register_blueprint(routes_money.bp)
app.register_blueprint(routes_compliance.bp)


@app.errorhandler(ApiError)
def _handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def _handle_404(e):
    return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))


@app.errorhandler(405)
def _handle_405(e):
    return error_response(ApiError(ERR_NOT_FOUND, 404, "Resource not found"))


@app.errorhandler(Exception)
def _handle_unexpected(e):
    if isinstance(e, ApiError):
        return error_response(e)
    app.logger.exception("Unexpected error")
    return error_response(ApiError("ERR_INTERNAL", 500, str(e)))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
