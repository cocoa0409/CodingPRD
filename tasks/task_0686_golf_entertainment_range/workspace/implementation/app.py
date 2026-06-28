"""Golf Entertainment Range API — entry point, error handlers, route registration.

In-memory only. No seeding: the store starts empty on every boot; tests build all
preconditions via the declared API surface (PRD §2.4).
"""

import os

from flask import Flask

from errors import ApiError
from response import error_response

from routes.venues import bp as venues_bp
from routes.members import bp as members_bp
from routes.reservations import bp as reservations_bp
from routes.sessions import bp as sessions_bp
from routes.event_packages import bp as event_packages_bp
from routes.fb_tabs import bp as fb_tabs_bp
from routes.queue_tickets import bp as queue_tickets_bp
from routes.lessons import bp as lessons_bp
from routes.charges import bp as charges_bp
from routes.clock_route import bp as clock_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(venues_bp)
    app.register_blueprint(members_bp)
    app.register_blueprint(reservations_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(event_packages_bp)
    app.register_blueprint(fb_tabs_bp)
    app.register_blueprint(queue_tickets_bp)
    app.register_blueprint(lessons_bp)
    app.register_blueprint(charges_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response("ERR_NOT_FOUND", "resource not found", 404)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        # Surface unexpected server errors in the standard envelope.
        return error_response("ERR_INTERNAL", str(err), 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
