"""Multi-Tiered System of Supports (MTSS/RTI) API — Flask application entry point."""

import os
from flask import Flask

from db import DB
from errors import ApiError, ERR_INVALID_REQUEST
from response import error_response

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ERR_INVALID_REQUEST, "Route not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response(ERR_INVALID_REQUEST, "Method not allowed", 405)


@app.errorhandler(500)
def handle_500(e):
    return error_response(ERR_INVALID_REQUEST, f"Internal error: {e}", 500)


# Serialize requests through a single re-entrant lock: the in-memory store is
# mutated by multi-step cascades that must stay atomic.
@app.before_request
def _acquire_lock():
    DB.lock.acquire()


@app.teardown_request
def _release_lock(exc):
    DB.lock.release()


# Register route blueprints
from routes.districts import bp as districts_bp
from routes.students import bp as students_bp
from routes.windows import bp as windows_bp
from routes.catalog import bp as catalog_bp
from routes.interventionists import bp as interventionists_bp
from routes.plans import bp as plans_bp
from routes.movements import bp as movements_bp
from routes.meetings import bp as meetings_bp
from routes.referrals import bp as referrals_bp
from routes.reports import bp as reports_bp

app.register_blueprint(districts_bp)
app.register_blueprint(students_bp)
app.register_blueprint(windows_bp)
app.register_blueprint(catalog_bp)
app.register_blueprint(interventionists_bp)
app.register_blueprint(plans_bp)
app.register_blueprint(movements_bp)
app.register_blueprint(meetings_bp)
app.register_blueprint(referrals_bp)
app.register_blueprint(reports_bp)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threaded=True)
