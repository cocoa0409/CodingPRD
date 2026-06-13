"""SDU (State Disbursement Unit) child-support disbursement API — entry point.

Registers every route blueprint under the /sdu prefix, installs the standard
error handlers (PRD 2.2 envelope), and runs the Flask dev server in the
foreground on 0.0.0.0:$PORT (default 10000).

Storage is in-memory only (see db.py): no seeding, no disk persistence. Each
start.sh re-invocation produces a fresh empty process state.
"""

import os

from flask import Flask
from werkzeug.exceptions import HTTPException

from errors import ApiError
from response import error_response

# Route blueprints
from routes.parties import bp as parties_bp
from routes.support_orders import bp as support_orders_bp
from routes.iwos import bp as iwos_bp
from routes.remittances import bp as remittances_bp
from routes.ledger_entries import bp as ledger_entries_bp
from routes.disbursements import bp as disbursements_bp
from routes.modifications import bp as modifications_bp
from routes.enforcement import bp as enforcement_bp
from routes.clock import bp as clock_bp

API_PREFIX = "/sdu"


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    for bp in (
        parties_bp,
        support_orders_bp,
        iwos_bp,
        remittances_bp,
        ledger_entries_bp,
        disbursements_bp,
        modifications_bp,
        enforcement_bp,
        clock_bp,
    ):
        app.register_blueprint(bp, url_prefix=API_PREFIX)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_not_found(err):
        # Unknown route -> standard ERR_NOT_FOUND envelope.
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_bad_request(err):
        return error_response("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Re-raise framework HTTP exceptions to their specific handlers above.
        if isinstance(err, HTTPException):
            return err
        return error_response("ERR_INVALID_REQUEST", "Unexpected error: %s" % err, 400)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
