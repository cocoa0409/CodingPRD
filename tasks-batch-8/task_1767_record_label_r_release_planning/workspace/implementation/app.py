"""Record Label Release Planning API — Flask entry point."""

import os

from flask import Flask

from errors import ApiError
from response import error_body
from routes import labels_artists, deals, contracts, projects, releases, marketing, tours, royalties

app = Flask(__name__)

app.register_blueprint(labels_artists.bp)
app.register_blueprint(deals.bp)
app.register_blueprint(contracts.bp)
app.register_blueprint(projects.bp)
app.register_blueprint(releases.bp)
app.register_blueprint(marketing.bp)
app.register_blueprint(tours.bp)
app.register_blueprint(royalties.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_body(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_not_found(_err):
    return error_body("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error_body("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(400)
def handle_bad_request(err):
    api_err = getattr(err, "_api_error", None)
    if isinstance(api_err, ApiError):
        return error_body(api_err.error_id, api_err.message, api_err.http_status)
    return error_body("ERR_INVALID_REQUEST", "Bad request", 400)


@app.errorhandler(500)
def handle_internal(err):
    original = getattr(err, "original_exception", None)
    if isinstance(original, ApiError):
        return error_body(original.error_id, original.message, original.http_status)
    return error_body("ERR_INVALID_REQUEST", "Internal server error", 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
