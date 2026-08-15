"""Entry point: Flask app, error handlers, route registration."""

import os
from flask import Flask

import errors
from response import error_response

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Error handler — catches our ApiError and formats the standard envelope
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
def handle_internal(e):
    return error_response("ERR_INTERNAL", str(e), 500)


# ---------------------------------------------------------------------------
# Register blueprints
# ---------------------------------------------------------------------------

from routes.clock import bp as clock_bp
from routes.watch_groups import bp as groups_bp
from routes.blocks import bp as blocks_bp
from routes.members import bp as members_bp
from routes.captain_assignments import bp as captains_bp
from routes.incident_reports import bp as incidents_bp
from routes.alerts import bp as alerts_bp
from routes.liaison_officers import bp as officers_bp
from routes.liaison_meetings import bp as meetings_bp
from routes.data_share_agreements import bp as agreements_bp
from routes.training_sessions import bp as training_bp
from routes.community_events import bp as events_bp
from routes.certification_reviews import bp as reviews_bp

app.register_blueprint(clock_bp)
app.register_blueprint(groups_bp)
app.register_blueprint(blocks_bp)
app.register_blueprint(members_bp)
app.register_blueprint(captains_bp)
app.register_blueprint(incidents_bp)
app.register_blueprint(alerts_bp)
app.register_blueprint(officers_bp)
app.register_blueprint(meetings_bp)
app.register_blueprint(agreements_bp)
app.register_blueprint(training_bp)
app.register_blueprint(events_bp)
app.register_blueprint(reviews_bp)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
