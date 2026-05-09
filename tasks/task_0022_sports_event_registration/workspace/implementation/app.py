"""Sports Event Registration API — Flask entrypoint."""
import os

from flask import Flask, jsonify

from errors import APIError, ERROR_CATALOG
from response import error_response


def create_app():
    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # Register blueprints
    from routes.events import bp as events_bp
    from routes.participants import bp as participants_bp
    from routes.referees import bp as referees_bp
    from routes.matches import bp as matches_bp
    from routes.doping import bp as doping_bp
    from routes.sanctions import bp as sanctions_bp
    from routes.rankings import bp as rankings_bp
    from routes.audit_sync import bp as audit_sync_bp
    from routes.system import bp as system_bp

    for bp in (events_bp, participants_bp, referees_bp, matches_bp, doping_bp,
               sanctions_bp, rankings_bp, audit_sync_bp, system_bp):
        app.register_blueprint(bp)

    @app.errorhandler(APIError)
    def handle_api_error(e: APIError):
        return error_response(e.error_id, e.message, e.http_status)

    @app.errorhandler(404)
    def handle_404(e):
        return error_response("ERR_NOT_FOUND", "Route or resource not found", 404)

    @app.errorhandler(405)
    def handle_405(e):
        return error_response("ERR_NOT_FOUND", "Method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(e):
        return error_response("ERR_VALIDATION", "Bad request", 422)

    @app.errorhandler(Exception)
    def handle_exc(e):
        # Last-resort handler for unexpected exceptions
        if isinstance(e, APIError):
            return error_response(e.error_id, e.message, e.http_status)
        return error_response("ERR_VALIDATION", str(e) or "Internal error", 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
