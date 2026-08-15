"""Entry point: error handlers and route registration."""
import os

from flask import Flask

from errors import ApiError
from response import error_response
from routes import plan_years, territories, rules_accounts, rep_assignments
from routes import allocations, submissions, reconciliation, change_requests
from routes import credit_events, disputes


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(plan_years.bp)
    app.register_blueprint(territories.bp)
    app.register_blueprint(rules_accounts.bp)
    app.register_blueprint(rep_assignments.bp)
    app.register_blueprint(allocations.bp)
    app.register_blueprint(submissions.bp)
    app.register_blueprint(reconciliation.bp)
    app.register_blueprint(change_requests.bp)
    app.register_blueprint(credit_events.bp)
    app.register_blueprint(disputes.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Never leak a stack trace as a bare 500; wrap in the error envelope.
        import traceback
        traceback.print_exc()
        return error_response("ERR_INTERNAL", f"Internal error: {err}", 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
