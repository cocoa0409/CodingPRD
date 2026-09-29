"""Smart Home Interoperability Certification service -- entry point.

Storage is in-memory only (see db.py) and the store starts empty on every boot:
nothing is seeded, preloaded or read from disk.
"""

import os

from flask import Flask

from errors import ApiError, ERROR_HTTP
from response import error_response
from routes.cases import bp as cases_bp
from routes.clock import bp as clock_bp
from routes.feature_sets import bp as feature_sets_bp
from routes.laboratories import bp as laboratories_bp
from routes.listings import bp as listings_bp
from routes.members import bp as members_bp
from routes.plugfests import bp as plugfests_bp
from routes.specifications import bp as specifications_bp
from routes.test_plans import bp as test_plans_bp
from routes.test_sessions import bp as test_sessions_bp
from routes.submissions import bp as submissions_bp

app = Flask(__name__)
app.url_map.strict_slashes = False
app.json.sort_keys = False

for blueprint in (
    clock_bp,
    specifications_bp,
    feature_sets_bp,
    members_bp,
    laboratories_bp,
    submissions_bp,
    test_plans_bp,
    test_sessions_bp,
    plugfests_bp,
    listings_bp,
    cases_bp,
):
    app.register_blueprint(blueprint)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(exc):
    return error_response("ERR_NOT_FOUND", "the requested resource does not exist", 404)


@app.errorhandler(405)
def handle_405(exc):
    return error_response("ERR_NOT_FOUND", "the method is not allowed on this path", 405)


@app.errorhandler(400)
def handle_400(exc):
    return error_response("ERR_INVALID_REQUEST", "the request could not be parsed", 400)


@app.errorhandler(Exception)
def handle_uncaught(exc):
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    app.logger.exception("unhandled error")
    return error_response("ERR_INTERNAL", str(exc), 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
