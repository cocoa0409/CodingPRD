"""Entry point for the TI Project Management API server.

Registers all blueprints, error handlers, and starts the Flask app.
"""

import os
from flask import Flask

from errors import APIError
from response import error_response

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(APIError)
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
    return error_response("ERR_INVALID_REQUEST", str(e), 500)


# ---------------------------------------------------------------------------
# Register blueprints
# ---------------------------------------------------------------------------

from routes.clock import bp as clock_bp
from routes.portfolio import bp as portfolio_bp
from routes.contractors import bp as contractors_bp
from routes.projects import bp as projects_bp
from routes.work_letters import bp as work_letters_bp
from routes.plans import bp as plans_bp
from routes.engagements import bp as engagements_bp
from routes.milestones import bp as milestones_bp
from routes.change_orders import bp as change_orders_bp
from routes.disbursements import bp as disbursements_bp
from routes.punch_items import bp as punch_items_bp
from routes.invoices import bp as invoices_bp

app.register_blueprint(clock_bp)
app.register_blueprint(portfolio_bp)
app.register_blueprint(contractors_bp)
app.register_blueprint(projects_bp)
app.register_blueprint(work_letters_bp)
app.register_blueprint(plans_bp)
app.register_blueprint(engagements_bp)
app.register_blueprint(milestones_bp)
app.register_blueprint(change_orders_bp)
app.register_blueprint(disbursements_bp)
app.register_blueprint(punch_items_bp)
app.register_blueprint(invoices_bp)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
