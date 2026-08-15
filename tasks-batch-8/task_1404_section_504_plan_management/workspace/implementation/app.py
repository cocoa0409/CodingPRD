"""Section 504 Plan Management API — entry point.

Boot contract (INSTRUCTION.md): foreground process, 0.0.0.0:$PORT (default
10000). Store is in-memory only and starts empty on every boot.
"""
import os

from flask import Flask

from db import db
from errors import ApiError
from response import error_response

app = Flask(__name__)
app.url_map.strict_slashes = False


@app.before_request
def _acquire_lock():
    db.lock.acquire()


@app.teardown_request
def _release_lock(exc):
    db.lock.release()


@app.errorhandler(ApiError)
def _handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def _handle_404(err):
    return error_response("ERR_NOT_FOUND", 404, "Resource does not exist")


@app.errorhandler(405)
def _handle_405(err):
    return error_response("ERR_NOT_FOUND", 404, "Resource does not exist")


@app.errorhandler(Exception)
def _handle_unexpected(err):
    return error_response("ERR_INVALID_REQUEST", 400, str(err))


from routes import (schools, staff, students, referrals, evaluations, plans,  # noqa: E402
                    accommodations, acks, logs, reviews, testing, consents,
                    grievances, audit, clock)

for module in (schools, staff, students, referrals, evaluations, plans,
               accommodations, acks, logs, reviews, testing, consents,
               grievances, audit, clock):
    app.register_blueprint(module.bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
