"""Demolition Contracting & Salvage API — entry point.

Flask app with in-memory storage (empty on every boot, no seeding), a
server-side logical clock, and the standard response envelope. Listens on
0.0.0.0:$PORT (default 10000) in the foreground.
"""

import os

from flask import Flask, request

from errors import ApiError, err, ERR_NOT_FOUND, ERR_VALIDATION
from response import error
from services import run_permit_expiry_sweep
from routes.projects import bp as projects_bp
from routes.surveys import bp as surveys_bp
from routes.utilities import bp as utilities_bp
from routes.permits import bp as permits_bp
from routes.engineering import bp as engineering_bp
from routes.salvage import bp as salvage_bp
from routes.notifications import bp as notifications_bp
from routes.dust import bp as dust_bp
from routes.tickets import bp as tickets_bp
from routes.backfill import bp as backfill_bp
from routes.inspections import bp as inspections_bp
from routes.clock import bp as clock_bp

app = Flask(__name__)
app.url_map.strict_slashes = False

for bp in (projects_bp, surveys_bp, utilities_bp, permits_bp, engineering_bp,
           salvage_bp, notifications_bp, dust_bp, tickets_bp, backfill_bp,
           inspections_bp, clock_bp):
    app.register_blueprint(bp)


@app.before_request
def sweep_on_project_interaction():
    # The permit expiry sweep runs on the clock setter and on any permit or
    # project interaction; every /demolition call is one.
    if request.path.startswith("/demolition"):
        run_permit_expiry_sweep()


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "resource not found")


@app.errorhandler(400)
def handle_400(e):
    return error(ERR_VALIDATION[0], ERR_VALIDATION[1], "bad request")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
