"""Flask entry point: registers blueprints and error handlers."""
import os

from flask import Flask

from errors import ApiError
from response import error_response


def create_app():
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    from routes.events import bp as events_bp
    from routes.catalog import bp as catalog_bp
    from routes.shifts import bp as shifts_bp
    from routes.groups import bp as groups_bp
    from routes.volunteers import bp as volunteers_bp
    from routes.training import bp as training_bp
    from routes.signups import bp as signups_bp
    from routes.supplies import bp as supplies_bp
    from routes.hour_logs import bp as hour_logs_bp
    from routes.debriefs import bp as debriefs_bp

    for bp in (events_bp, catalog_bp, shifts_bp, groups_bp, volunteers_bp,
               training_bp, signups_bp, supplies_bp, hour_logs_bp, debriefs_bp):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "The requested resource was not found.", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_METHOD_NOT_ALLOWED", "Method not allowed.", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        # Never leak a stack trace; return a structured 500.
        return error_response("ERR_INTERNAL", f"Internal server error: {e}", 500)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
