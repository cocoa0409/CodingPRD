"""Application entry point: Flask app, error handlers, route registration.

Storage is in-memory only (see db.py). No seeding is performed at startup.
"""

import os

from flask import Flask

import errors as err_mod
from errors import ApiError
from response import error_response

from routes.plans import bp as plans_bp
from routes.participants import bp as participants_bp
from routes.loans import bp as loans_bp
from routes.remittances import bp as remittances_bp
from routes.hardship import bp as hardship_bp
from routes.approval_tasks import bp as approval_tasks_bp
from routes.tax_events import bp as tax_events_bp
from routes.suspensions import bp as suspensions_bp
from routes.clock import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(plans_bp)
    app.register_blueprint(participants_bp)
    app.register_blueprint(loans_bp)
    app.register_blueprint(remittances_bp)
    app.register_blueprint(hardship_bp)
    app.register_blueprint(approval_tasks_bp)
    app.register_blueprint(tax_events_bp)
    app.register_blueprint(suspensions_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response(err_mod.ERR_INVALID_REQUEST, "Not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response(err_mod.ERR_INVALID_REQUEST, "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        import traceback
        traceback.print_exc()
        return error_response(err_mod.ERR_INVALID_REQUEST,
                              f"Internal error: {type(e).__name__}: {e}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
