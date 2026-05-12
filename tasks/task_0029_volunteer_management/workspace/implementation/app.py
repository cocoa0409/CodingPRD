"""Flask app entry point — registers blueprints and global error handlers."""
import logging
import os
import traceback

from flask import Flask, jsonify

from errors import APIError, ERR_INVALID_INPUT, ERR_NOT_FOUND, err
from response import error_response


def create_app() -> Flask:
    app = Flask(__name__)
    # Disable Flask's default 404 HTML — we handle it ourselves
    app.url_map.strict_slashes = False

    # Register blueprints
    from routes.activities import bp as activities_bp
    from routes.applications import bp as applications_bp
    from routes.audit import bp as audit_bp
    from routes.certificates import bp as certificates_bp
    from routes.clock_routes import bp as clock_bp
    from routes.hour_adjustments import bp as hour_adj_bp
    from routes.point_mall import bp as point_mall_bp
    from routes.skills import bp as skills_bp
    from routes.volunteers import bp as volunteers_bp

    app.register_blueprint(volunteers_bp)
    app.register_blueprint(skills_bp)
    app.register_blueprint(activities_bp)
    app.register_blueprint(applications_bp)
    app.register_blueprint(hour_adj_bp)
    app.register_blueprint(point_mall_bp)
    app.register_blueprint(certificates_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(clock_bp)

    @app.errorhandler(APIError)
    def handle_api_error(exc: APIError):
        return error_response(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_404(_e):
        return error_response("ERR_NOT_FOUND", "route not found", 404)

    @app.errorhandler(405)
    def handle_405(_e):
        return error_response("ERR_NOT_FOUND", "method not allowed", 404)

    @app.errorhandler(400)
    def handle_400(_e):
        return error_response(ERR_INVALID_INPUT, "bad request", 422)

    @app.errorhandler(Exception)
    def handle_generic(exc):
        logging.exception("unhandled exception")
        traceback.print_exc()
        return error_response("ERR_INVALID_INPUT", str(exc) or "internal error", 422)

    return app


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    # Bind 0.0.0.0 per INSTRUCTION.md
    app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False)
