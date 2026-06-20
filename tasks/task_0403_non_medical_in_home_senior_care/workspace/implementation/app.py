"""In-Home Senior Care API — entry point, error handlers, route registration.

Storage is in-memory only (db.py). The store starts EMPTY on every boot; no
entities are seeded, preloaded, or hardcoded at startup.
"""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes.agencies import bp as agencies_bp
from routes.caregivers import bp as caregivers_bp
from routes.clients import bp as clients_bp
from routes.care_plans import bp as care_plans_bp
from routes.matches import bp as matches_bp
from routes.visits import bp as visits_bp
from routes.invoices import bp as invoices_bp
from routes.claims import bp as claims_bp
from routes.clock_admin import bp as clock_admin_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

for bp in (
    agencies_bp, caregivers_bp, clients_bp, care_plans_bp, matches_bp,
    visits_bp, invoices_bp, claims_bp, clock_admin_bp,
):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(err):
    return error_response("ERR_AGENCY_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(err):
    return error_response("ERR_INVALID_REQUEST", 405, "Method not allowed")


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return error_response(err.error_id, err.http_status, err.message)
    return error_response("ERR_INVALID_REQUEST", 500, "Internal server error: %s" % err)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
