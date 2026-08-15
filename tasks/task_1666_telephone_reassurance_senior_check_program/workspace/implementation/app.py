"""Senior Check-In API — entry point. In-memory store; no seeding."""
import os

from flask import Flask

from envelope import error_body
from errors import ApiError


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    import routes_programs
    import routes_participants
    import routes_volunteers
    import routes_assignments
    import routes_escalations
    import routes_referrals
    import routes_reports

    app.register_blueprint(routes_programs.bp)
    app.register_blueprint(routes_participants.bp)
    app.register_blueprint(routes_volunteers.bp)
    app.register_blueprint(routes_assignments.bp)
    app.register_blueprint(routes_escalations.bp)
    app.register_blueprint(routes_referrals.bp)
    app.register_blueprint(routes_reports.bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_body(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_body("ERR_NOT_FOUND", "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_body("ERR_NOT_FOUND", "Method not allowed", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        import traceback
        traceback.print_exc()
        return error_body("ERR_INTERNAL", "Internal error: %s" % e, 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")),
            threaded=True)
