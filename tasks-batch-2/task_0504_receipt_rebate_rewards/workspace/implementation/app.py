"""Receipt-Rebate Rewards API — entry point, route registration, error handlers.

Storage is fully in-memory (see state.py / db.py): every collection starts empty
on each fresh process, so re-invoking start.sh wipes all state. Nothing is seeded.
"""
import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response
from state import store

# Route blueprints.
from routes.merchants import bp as merchants_bp
from routes.offers import bp as offers_bp
from routes.members import bp as members_bp
from routes.ledger import bp as ledger_bp
from routes.clickthroughs import bp as clickthroughs_bp
from routes.receipt_scans import bp as receipt_scans_bp
from routes.reward_claims import bp as reward_claims_bp
from routes.cashouts import bp as cashouts_bp
from routes.referrals import bp as referrals_bp
from routes.return_events import bp as return_events_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        merchants_bp,
        offers_bp,
        members_bp,
        ledger_bp,
        clickthroughs_bp,
        receipt_scans_bp,
        reward_claims_bp,
        cashouts_bp,
        referrals_bp,
        return_events_bp,
        clock_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(store.clock, e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(store.clock, "ERR_NOT_FOUND", "Resource not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(store.clock, "ERR_NOT_FOUND", "Method not allowed.", 404)

    @app.errorhandler(HTTPException)
    def handle_http(e):
        # Map any other werkzeug HTTP error into the envelope.
        code = e.code or 500
        if code == 400:
            return error_response(store.clock, "ERR_VALIDATION", e.description, 400)
        return error_response(store.clock, "ERR_VALIDATION", str(e), code)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return error_response(store.clock, "ERR_VALIDATION", "Internal error: %s" % e, 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
