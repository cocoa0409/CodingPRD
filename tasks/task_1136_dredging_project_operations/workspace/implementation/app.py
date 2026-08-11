"""Entry point: Flask app factory, error handlers, blueprint registration."""
import os

from flask import Flask

from errors import ApiError, ERR_NOT_FOUND
from response import err


def create_app():
    app = Flask(__name__, static_folder=None)
    app.url_map.strict_slashes = False

    from routes.clock import bp as clock_bp
    from routes.projects import bp as projects_bp
    from routes.permits import bp as permits_bp
    from routes.reaches import bp as reaches_bp
    from routes.plants import bp as plants_bp
    from routes.plans import bp as plans_bp
    from routes.surveys import bp as surveys_bp
    from routes.events import bp as events_bp
    from routes.monitoring import bp as monitoring_bp
    from routes.disposal import bp as disposal_bp
    from routes.claims import bp as claims_bp
    from routes.certs import bp as certs_bp

    for bp in (
        clock_bp,
        projects_bp,
        permits_bp,
        reaches_bp,
        plants_bp,
        plans_bp,
        surveys_bp,
        events_bp,
        monitoring_bp,
        disposal_bp,
        claims_bp,
        certs_bp,
    ):
        app.register_blueprint(bp)

    @app.errorhandler(ApiError)
    def handle_api_error(e):
        return err(e.error_id, e.message, e.status)

    @app.errorhandler(404)
    def handle_not_found(e):
        return err(ERR_NOT_FOUND, "Resource not found", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(e):
        return err(ERR_NOT_FOUND, "Method not allowed on this path", 405)

    @app.errorhandler(Exception)
    def handle_unexpected(e):
        return err("ERR_INTERNAL", "Internal server error: %s" % e, 500)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
