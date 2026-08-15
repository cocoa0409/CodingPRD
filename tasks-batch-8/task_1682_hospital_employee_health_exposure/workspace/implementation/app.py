"""Hospital Employee Health & Exposure Management API — Flask entry point."""
import os

from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False

from routes import (campaigns, clearances, clock, contacts, cycles, employees,  # noqa: E402
                    events, exposures, holds, injuries, participations, pep,
                    restrictions, screenings, serology, titers)

for module in (
    clock, employees, screenings, titers, cycles, holds, exposures, pep, serology,
    restrictions, clearances, events, contacts, injuries, campaigns, participations,
):
    app.register_blueprint(module.bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_not_found(_err):
    return error_response(ApiError("ERR_NOT_FOUND", "Resource not found"))


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return error_response(ApiError("ERR_NOT_FOUND", "Resource not found"))


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err)
    app.logger.exception("unexpected error")
    resp, _status = error_response(ApiError("ERR_INVALID_REQUEST", "Unexpected server error"))
    return resp, 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
