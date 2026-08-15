"""Entry point — Flask app, error handlers, route registration."""

import os
from flask import Flask

import errors
from response import error_response

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(errors.ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_not_found(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_method_not_allowed(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(500)
def handle_internal_error(e):
    return error_response("ERR_VALIDATION", str(e), 500)


# ---------------------------------------------------------------------------
# Register blueprints
# ---------------------------------------------------------------------------

from routes.securities import bp as securities_bp
from routes.owners_borrowers import bp_owners, bp_borrowers
from routes.limit_overrides import bp as overrides_bp
from routes.positions_requests import bp_positions, bp_requests
from routes.loans import bp as loans_bp
from routes.pledges import bp as pledges_bp
from routes.margin_calls import bp as margin_calls_bp
from routes.recalls import bp as recalls_bp
from routes.reinvestments import bp as reinvestments_bp
from routes.ledger import bp as ledger_bp
from routes.ops_reports import bp as ops_bp

app.register_blueprint(securities_bp)
app.register_blueprint(bp_owners)
app.register_blueprint(bp_borrowers)
app.register_blueprint(overrides_bp)
app.register_blueprint(bp_positions)
app.register_blueprint(bp_requests)
app.register_blueprint(loans_bp)
app.register_blueprint(pledges_bp)
app.register_blueprint(margin_calls_bp)
app.register_blueprint(recalls_bp)
app.register_blueprint(reinvestments_bp)
app.register_blueprint(ledger_bp)
app.register_blueprint(ops_bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
