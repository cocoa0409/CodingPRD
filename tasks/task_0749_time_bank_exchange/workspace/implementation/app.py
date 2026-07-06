"""Entry point — Flask app, error handlers, blueprint registration."""
import os
from flask import Flask, jsonify

from errors import APIError, raise_err, ERR_RESOURCE_NOT_FOUND, ERR_INVALID_REQUEST
from response import envelope_error


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    # --- Global error handlers ---

    @app.errorhandler(APIError)
    def handle_api_error(err: APIError):
        return envelope_error(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(_e):
        return envelope_error("ERR_RESOURCE_NOT_FOUND", "Route not found", 404)

    @app.errorhandler(405)
    def handle_405(_e):
        return envelope_error("ERR_INVALID_REQUEST", "Method not allowed", 400)

    @app.errorhandler(400)
    def handle_400(_e):
        return envelope_error("ERR_INVALID_REQUEST", "Bad request", 400)

    @app.errorhandler(Exception)
    def handle_generic(err):
        # Any unexpected error: 500 wrapped in error envelope.
        import traceback
        traceback.print_exc()
        return envelope_error("ERR_INVALID_REQUEST", f"Internal error: {err}", 500)

    # --- Register routes ---
    from routes.clock import bp as clock_bp
    from routes.members import bp as members_bp
    from routes.skill_offers import bp as offers_bp
    from routes.skill_requests import bp as requests_bp
    from routes.exchanges import bp as exchanges_bp
    from routes.ledger import bp as ledger_bp
    from routes.redemptions import bp as redemptions_bp
    from routes.credentials import bp as credentials_bp
    from routes.group_projects import bp as projects_bp
    from routes.shifts import bp as shifts_bp
    from routes.assignments import bp as assignments_bp
    from routes.disputes import bp as disputes_bp
    from routes.impact_reports import bp as impact_bp

    app.register_blueprint(clock_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(offers_bp)
    app.register_blueprint(requests_bp)
    app.register_blueprint(exchanges_bp)
    app.register_blueprint(ledger_bp)
    app.register_blueprint(redemptions_bp)
    app.register_blueprint(credentials_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(shifts_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(disputes_bp)
    app.register_blueprint(impact_bp)

    return app


app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
