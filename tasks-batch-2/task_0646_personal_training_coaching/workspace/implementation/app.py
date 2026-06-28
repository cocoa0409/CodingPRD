"""Flask entry point for the Personal Training & Online Coaching API.

Wires every blueprint, registers the standard error envelope handlers, and runs
the server in the foreground on 0.0.0.0:$PORT (default 10000). The in-memory
store starts EMPTY on every boot — no seeding.
"""

import os

from flask import Flask

import errors
from response import error_response

from routes.clock_route import bp as clock_bp
from routes.trainers import bp as trainers_bp
from routes.clients import bp as clients_bp
from routes.engagements import bp as engagements_bp
from routes.session_packs import bp as session_packs_bp
from routes.bookings import bp as bookings_bp
from routes.program_assignments import bp as program_assignments_bp
from routes.macro_plans import bp as macro_plans_bp
from routes.check_ins import bp as check_ins_bp
from routes.habit_logs import bp as habit_logs_bp
from routes.messages import bp as messages_bp


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    app.register_blueprint(clock_bp)
    app.register_blueprint(trainers_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(engagements_bp)
    app.register_blueprint(session_packs_bp)
    app.register_blueprint(bookings_bp)
    app.register_blueprint(program_assignments_bp)
    app.register_blueprint(macro_plans_bp)
    app.register_blueprint(check_ins_bp)
    app.register_blueprint(habit_logs_bp)
    app.register_blueprint(messages_bp)

    @app.errorhandler(errors.ApiError)
    def handle_api_error(err):
        return error_response(err.error_id, err.message, err.http_status)

    @app.errorhandler(404)
    def handle_404(err):
        return error_response(errors.ERR_ENGAGEMENT_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_405(err):
        return error_response(errors.ERR_INVALID_REQUEST, "Method not allowed", 422)

    @app.errorhandler(400)
    def handle_400(err):
        return error_response(errors.ERR_INVALID_REQUEST, "Malformed request", 422)

    @app.errorhandler(Exception)
    def handle_unexpected(err):
        if isinstance(err, errors.ApiError):
            return error_response(err.error_id, err.message, err.http_status)
        return error_response("ERR_INTERNAL", "Internal server error", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
