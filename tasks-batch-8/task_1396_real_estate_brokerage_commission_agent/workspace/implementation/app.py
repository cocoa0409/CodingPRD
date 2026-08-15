"""Real Estate Brokerage Commission API — Flask entry point.

In-memory store (db.py dicts), logical clock starting 2026-08-01T00:00:00Z,
no seeding of any entity at startup.
"""

import os

from flask import Flask

from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND
from response import error_resp

app = Flask(__name__)

from routes.clock import bp as clock_bp
from routes.agents import bp as agents_bp
from routes.plans import bp as plans_bp
from routes.enrollments import bp as enrollments_bp
from routes.periods import bp as periods_bp
from routes.deals import bp as deals_bp
from routes.settlements import bp as settlements_bp
from routes.legs import bp as legs_bp
from routes.ledger import bp as ledger_bp
from routes.tax_forms import bp as tax_forms_bp
from routes.trust import bp as trust_bp

for bp in (clock_bp, agents_bp, plans_bp, enrollments_bp, periods_bp, deals_bp,
           settlements_bp, legs_bp, ledger_bp, tax_forms_bp, trust_bp):
    app.register_blueprint(bp)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_resp(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_resp(ERR_NOT_FOUND, 404, "resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_resp(ERR_NOT_FOUND, 404, "resource not found")


@app.errorhandler(400)
def handle_400(e):
    return error_resp(ERR_INVALID_REQUEST, 400, "malformed request")


@app.errorhandler(Exception)
def handle_unexpected(e):
    return error_resp(ERR_INVALID_REQUEST, 400, "unexpected error: %s" % type(e).__name__)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
