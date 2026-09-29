"""Employee Handbook & Policy Acknowledgment API."""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

import response
from errors import ApiError

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.errorhandler(ApiError)
def _api_error(exc):
    return response.error(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def _not_found(exc):
    return response.error("ERR_RESOURCE_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def _bad_method(exc):
    return response.error("ERR_RESOURCE_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(HTTPException)
def _http_error(exc):
    if exc.code == 400:
        return response.error("ERR_VALIDATION", "Malformed request", 422)
    return response.error("ERR_VALIDATION", exc.description or "Request error", exc.code or 422)


@app.errorhandler(Exception)
def _unhandled(exc):
    app.logger.exception("unhandled error")
    return response.error("ERR_VALIDATION", "Unexpected server error: %s" % exc, 500)


from routes import directory, authoring, review, localization, release, distribution, escalation, exceptions, ops  # noqa: E402

for module in (directory, authoring, review, localization, release, distribution, escalation, exceptions, ops):
    app.register_blueprint(module.bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
