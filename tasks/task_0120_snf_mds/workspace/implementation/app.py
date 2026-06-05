"""SNF-MDS API — entry point, error handlers, route registration.

In-memory storage only (see db.py); nothing is seeded at startup. Validation
order follows PRD §2.7: auth -> role -> existence (left-to-right) -> body schema
-> state -> business rules.
"""
import os

from flask import Flask

import errors
import response
from routes import (
    admissions,
    assessments,
    bed_holds,
    care_plans,
    claims,
    facilities,
    residents,
    therapy,
)

app = Flask(__name__)
app.url_map.strict_slashes = False


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(errors.ApiError)
def handle_api_error(e):
    return response.error(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return response.error(errors.ERR_NOT_FOUND, "route not found", 404)


@app.errorhandler(405)
def handle_405(e):
    # Method-not-allowed on a known path surfaces as not-found per the catalog
    # (no dedicated 405 error id).
    return response.error(errors.ERR_NOT_FOUND, "method not allowed", 404)


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, errors.ApiError):
        return response.error(e.error_id, e.message, e.http_status)
    return response.error(errors.ERR_INVALID_REQUEST, "unexpected error: %s" % e, 422)


# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------
facilities.register(app)
residents.register(app)
admissions.register(app)
assessments.register(app)
therapy.register(app)
care_plans.register(app)
bed_holds.register(app)
claims.register(app)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
