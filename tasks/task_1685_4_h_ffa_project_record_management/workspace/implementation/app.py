"""FFA 4-H Project Records API -- entry point.

Registers every route group under the /api prefix, installs the error-envelope
handlers (PRD 2.2), and serves on 0.0.0.0:$PORT (default 10000).

Storage is in-memory only (module-level dicts in db.py). The store starts
empty on every boot: nothing is seeded, preloaded, or hardcoded here.
"""

import os

from flask import Flask

import response
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from routes import (clock_routes, clubs, volunteers, members, projects,
                    animal_tags, record_books, ledger_entries, meetings, fair,
                    awards, scholarships, treasury)

API_PREFIX = "/api"

app = Flask(__name__)
app.url_map.strict_slashes = False

for blueprint in (
    clock_routes.bp,
    clubs.bp,
    volunteers.bp,
    members.bp,
    projects.bp,
    animal_tags.bp,
    record_books.bp,
    ledger_entries.bp,
    meetings.rooms_bp,
    meetings.bp,
    meetings.attendance_bp,
    fair.pens_bp,
    fair.bp,
    fair.stalls_bp,
    awards.bp,
    scholarships.bp,
    treasury.bp,
):
    app.register_blueprint(blueprint, url_prefix=API_PREFIX)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return response.error(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_not_found(_err):
    return response.error(ERR_NOT_FOUND, "A referenced resource id does not exist", 404)


@app.errorhandler(405)
def handle_method_not_allowed(_err):
    return response.error(ERR_INVALID_REQUEST, "Method not allowed for this path", 405)


@app.errorhandler(Exception)
def handle_unexpected(err):
    # Flask's HTTPExceptions with other codes land here; surface their status.
    status = getattr(err, "code", 500)
    if not isinstance(status, int) or status < 400:
        status = 500
    error_id = ERR_INVALID_REQUEST if status == 400 else "ERR_INTERNAL"
    return response.error(error_id, str(err), status)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
