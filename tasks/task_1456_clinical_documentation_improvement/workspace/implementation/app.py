"""Clinical Documentation Improvement (CDI) API — Flask entry point.

In-memory only: all state lives in module-level dicts in db.py and is rebuilt
from nothing on every process boot. No seeding, no persistence.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response

app = Flask(__name__, static_folder=None)
app.url_map.strict_slashes = False

from routes.cases import bp as cases_bp
from routes.clock_admin import bp as clock_admin_bp
from routes.education import bp as education_bp
from routes.policies import bp as policies_bp
from routes.programs import bp as programs_bp
from routes.providers import bp as providers_bp
from routes.queries import bp as queries_bp
from routes.reconciliations import bp as reconciliations_bp
from routes.reviews import bp as reviews_bp
from routes.snapshots import bp as snapshots_bp
from routes.targets import bp as targets_bp

for bp in (
    programs_bp,
    policies_bp,
    providers_bp,
    cases_bp,
    reviews_bp,
    queries_bp,
    reconciliations_bp,
    targets_bp,
    education_bp,
    snapshots_bp,
    clock_admin_bp,
):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.http_status, exc.message)


@app.errorhandler(404)
def handle_404(exc):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(exc):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return error_response(exc.error_id, exc.http_status, exc.message)
    return error_response("ERR_INVALID_REQUEST", 400, str(exc))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
